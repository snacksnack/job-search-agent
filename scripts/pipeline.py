#!/usr/bin/env python3
"""Deterministic job-search pipeline (no LLM, no browser).

This is the headless backbone that used to run inside the agent. It does all
the cheap, deterministic work in plain Python so it costs no tokens:

  1. Watchlist sweep   -- fetch each company's Greenhouse/Lever/Ashby/Workable/
                          SmartRecruiters board via public JSON APIs (no auth, no browser).
  2. Inbox ingest      -- read raw postings dropped into data/inbox/*.json by
                          Claude in Chrome (the LinkedIn discovery step) and,
                          where the URL is an ATS board, enrich from that API.
  3. Filter            -- title rules, employer skips, salary, location, and
                          description dealbreakers, all read from profile.json.
  4. Score             -- a transparent matchPercent per the profile's formula.
  5. Dedup + merge     -- by URL and id, against existing jobs.json + state.json.
  6. Write             -- jobs.json (source of truth) and append to search-log.

The LLM (Cowork) is now only used for the fuzzy parts on demand: nuanced
re-scoring, company briefs, and tailored materials.

Usage:
  python3 scripts/pipeline.py                 # full pipeline: sweep + re-enrich, write jobs.json
  python3 scripts/pipeline.py --dry-run       # report only, write nothing (both stages)
  python3 scripts/pipeline.py --sweep-only    # discovery sweep only, skip re-enrich
  python3 scripts/pipeline.py --reenrich      # re-enrich existing roles only, no discovery
  python3 scripts/pipeline.py --max-age-days 3

By default a single run does everything: it sweeps the watchlist for new roles,
writes them, then immediately re-enriches any roles with an enrichable ATS url
(filling full job descriptions — notably for SmartRecruiters, whose sweep is
list-only — and rescoring). One command, no second step.
"""
import argparse
import datetime
import difflib
import json
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
TODAY = datetime.date.today().isoformat()

# Domains that mark a URL as an ATS apply link (vs a human-readable source page)
ATS_HINTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "workable.com",
    "smartrecruiters.com", "jobvite.com", "icims.com", "bamboohr.com", "breezy.hr",
    "rippling.com", "gem.com", "teamtailor.com", "paylocity.com", "jobs.openai.com",
    "openai.com",
)

# Keyword buckets for domain_bonus (derived from profile priority/adjacent domains)
PRIORITY_KW = ["platform", "infrastructure", "infra", "data platform", "ml platform",
               "machine learning", "developer tool", "ci/cd", "devops", "cloud",
               "aws", "kubernetes", "observability", "reliability", "sre"]
ADJACENT_KW = ["martech", "marketing technology", "saas", "fintech", "data product"]

# Positive title signals beyond the profile's explicit lists (inclusive default)
TITLE_KW = ["technical program manager", "tpm", "solutions engineer", "solutions architect",
            "forward deployed", "sales engineer", "pre-sales engineer", "implementation engineer",
            "integration engineer", "customer engineer", "deployment engineer", "field engineer",
            "professional services engineer", "delivery engineer", "onboarding engineer",
            "platform engineer", "infrastructure engineer"]

QUOTA_SIGNALS = ["sales quota", "carry a quota", "quota-carrying", "quota carrying",
                 "individual quota", "ote", "on-target earnings", "commission", "close deals",
                 "closing deals", "revenue target", "bookings target", "pipeline generation"]

# NYC-metro detection. Catches "New York", "New York City", "NYC", "New York, NY",
# the boroughs, etc. The (?<![a-z]) / (?![a-z]) guards act as punctuation-agnostic
# word boundaries so it still matches inside "New York, NY" or "Brooklyn, New York"
# while NOT matching upstate locations like "Albany, NY" or "Buffalo, NY" (those have
# no "new york"/"nyc"/borough token).
NY_METRO_RE = re.compile(
    r"(?<![a-z])("
    r"new york|nyc|manhattan|brooklyn|the bronx|bronx|queens|"
    r"staten island|long island city|ny metro|nyc metro|greater new york"
    r")(?![a-z])"
)

# US-scope detection for the remote rule (profile.locationRule.includeRemoteScope = "US").
# A remote role qualifies only if it is open to US candidates. US_RE finds a positive US
# signal; NON_US_RE finds a foreign country/region. A role with a foreign location and NO
# US signal is excluded (e.g. "Remote - Netherlands"), but one that names both is kept
# (e.g. "US-Remote, London, England UK" is a US-remote role).
US_RE = re.compile(r"(?<![a-z])(u\.?s\.?a?|united states|north america|americas|stateside)(?![a-z])")
NON_US_RE = re.compile(
    r"(?<![a-z])("
    r"netherlands|united kingdom|uk|england|scotland|wales|ireland|"
    r"germany|france|spain|portugal|italy|poland|sweden|norway|denmark|finland|"
    r"switzerland|austria|belgium|netherland|greece|romania|czech|hungary|"
    r"europe|emea|apac|latam|india|canada|australia|new zealand|singapore|"
    r"japan|china|hong kong|brazil|mexico|argentina|colombia|israel|uae|"
    r"london|dublin|berlin|munich|paris|madrid|barcelona|amsterdam|"
    r"toronto|vancouver|bangalore|bengaluru|hyderabad|pune|sydney|melbourne|tokyo"
    r")(?![a-z])"
)


# --------------------------------------------------------------------------- IO
def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with open(p) as f:
        return json.load(f)


def http_get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "job-scout/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slugify(*parts):
    s = "-".join(p for p in parts if p)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)[:80]


def host_of(url):
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).replace("www.", "").lower() if m else ""


def classify_urls(url):
    """Return (sourceUrl, atsUrl) from a single url by domain."""
    if not url:
        return "", ""
    is_ats = any(h in host_of(url) for h in ATS_HINTS)
    return ("", url) if is_ats else (url, "")


# ----------------------------------------------------------------- ATS fetchers
def fetch_greenhouse(slug):
    data = http_get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        out.append({
            "title": j.get("title"),
            "location": (j.get("location") or {}).get("name"),
            "url": j.get("absolute_url"),
            "description": re.sub(r"<[^>]+>", " ", j.get("content", "") or ""),
            "postedDate": (j.get("updated_at") or "")[:10] or None,
            "salaryMin": None, "salaryMax": None, "salaryCurrency": "USD",
        })
    return out


def fetch_lever(slug):
    data = http_get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in data:
        cats = j.get("categories", {}) or {}
        sr = j.get("salaryRange") or {}
        created = j.get("createdAt")
        posted = datetime.datetime.fromtimestamp(created / 1000, datetime.timezone.utc).date().isoformat() if created else None
        out.append({
            "title": j.get("text"),
            "location": cats.get("location"),
            "url": j.get("hostedUrl"),
            "description": j.get("descriptionPlain", "") or "",
            "postedDate": posted,
            "salaryMin": sr.get("min"), "salaryMax": sr.get("max"),
            "salaryCurrency": sr.get("currency", "USD"),
        })
    return out


def fetch_ashby(slug):
    data = http_get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        comp = j.get("compensation") or {}
        cmin = cmax = None
        for c in comp.get("compensationTiers", []) or []:
            for comp_part in c.get("components", []) or []:
                mv = comp_part.get("minValue"); xv = comp_part.get("maxValue")
                if mv:
                    cmin = mv if cmin is None else min(cmin, mv)
                if xv:
                    cmax = xv if cmax is None else max(cmax, xv)
        out.append({
            "title": j.get("title"),
            "location": j.get("location"),
            "url": j.get("jobUrl"),
            "description": j.get("descriptionPlain", "") or "",
            "postedDate": (j.get("publishedAt") or "")[:10] or None,
            "salaryMin": cmin, "salaryMax": cmax, "salaryCurrency": "USD",
        })
    return out


def fetch_workable(slug):
    """Public Workable widget API (no auth). `details=true` returns each posting's
    HTML description/requirements/benefits inline, so the sweep gets full text in
    one call. Workable's public widget does not expose salary, so comp is left null."""
    data = http_get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    out = []
    for j in data.get("jobs", []):
        loc_parts = [j.get("city"), j.get("state"), j.get("country")]
        location = ", ".join(p for p in loc_parts if p)
        if j.get("telecommuting"):
            location = (location + " (Remote)").strip() if location else "Remote"
        html = " ".join(j.get(k, "") or "" for k in ("description", "requirements", "benefits"))
        out.append({
            "title": j.get("title"),
            "location": location or None,
            "url": j.get("url") or j.get("shortlink"),
            "description": re.sub(r"<[^>]+>", " ", html).strip(),
            "postedDate": (j.get("published_on") or j.get("created_at") or "")[:10] or None,
            "salaryMin": None, "salaryMax": None, "salaryCurrency": "USD",
        })
    return out


def _smartrecruiters_detail(slug, jid):
    """Fetch one SmartRecruiters posting's full job ad (used by enrich/--reenrich)."""
    d = http_get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}")
    sections = ((d.get("jobAd") or {}).get("sections")) or {}
    html = " ".join((sections.get(s) or {}).get("text", "") or ""
                    for s in ("companyDescription", "jobDescription", "qualifications",
                              "additionalInformation"))
    loc = d.get("location") or {}
    loc_parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    location = ", ".join(p for p in loc_parts if p)
    if loc.get("remote"):
        location = (location + " (Remote)").strip() if location else "Remote"
    return {
        "title": d.get("name"),
        "location": location or None,
        "url": f"https://jobs.smartrecruiters.com/{slug}/{jid}",
        "description": re.sub(r"<[^>]+>", " ", html).strip(),
        "postedDate": (d.get("releasedDate") or "")[:10] or None,
        "salaryMin": None, "salaryMax": None, "salaryCurrency": "USD",
    }


def fetch_smartrecruiters(slug, max_pages=10):
    """Public SmartRecruiters Posting API (no auth). The list endpoint is cheap but
    carries no job description, so the sweep pulls list-level fields only (title,
    location, url, date); the full JD is filled lazily per-posting via enrich_from_ats
    / --reenrich. Paginated; capped at `max_pages` (100/page) to bound large boards."""
    out = []
    offset, limit = 0, 100
    for _ in range(max_pages):
        data = http_get_json(
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit={limit}&offset={offset}")
        content = data.get("content", []) or []
        for j in content:
            loc = j.get("location") or {}
            loc_parts = [loc.get("city"), loc.get("region"), loc.get("country")]
            location = ", ".join(p for p in loc_parts if p)
            if loc.get("remote"):
                location = (location + " (Remote)").strip() if location else "Remote"
            jid = j.get("id")
            out.append({
                "title": j.get("name"),
                "location": location or None,
                "url": f"https://jobs.smartrecruiters.com/{slug}/{jid}",
                "description": "",   # list endpoint carries no JD; filled via --reenrich
                "postedDate": (j.get("releasedDate") or "")[:10] or None,
                "salaryMin": None, "salaryMax": None, "salaryCurrency": "USD",
            })
        offset += limit
        if not content or offset >= (data.get("totalFound") or 0):
            break
    return out


ATS_FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "workable": fetch_workable,
    "smartrecruiters": fetch_smartrecruiters,
}

# Hosts whose postings can be enriched/re-enriched from a public board API. Kept in one
# place so the inbox-ingest, enrich_from_ats, and --reenrich paths stay in sync.
ENRICHABLE_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "smartrecruiters.com")


# ------------------------------------------------------------------- filtering
def title_decision(title, profile):
    t = (title or "").lower()
    matching = profile.get("matching", {})
    if any(a.lower() in t for a in matching.get("alwaysIncludeTitles", [])):
        return True, None
    for rule in matching.get("skipTitleRules", []):
        for st in rule.get("titles", []):
            if st.lower() in t:
                return False, f"titleMismatch: {rule.get('category')}"
    targets = [x.lower() for x in profile.get("preferences", {}).get("targetTitles", [])]
    if any(tt in t for tt in targets) or any(k in t for k in TITLE_KW):
        return True, None
    secondary = [s.lower() for s in matching.get("secondaryIncludeTitles", {}).get("titles", [])]
    if any(s in t for s in secondary):
        return True, None              # adjacent title (e.g. Technical Project Manager); ranks lower via scoring
    return False, "titleMismatch: no target-title signal"


def employer_ok(company, profile):
    skip = [e.lower() for e in profile.get("matching", {}).get("skipEmployers", [])]
    return (company or "").lower() not in skip


def salary_ok(role, profile):
    target = profile.get("preferences", {}).get("salaryTarget")
    lo, hi = role.get("salaryMin"), role.get("salaryMax")
    if not target or hi is None:           # unknown salary -> qualifies (soft target)
        return True, None
    if hi < target:                        # entire range tops out below target
        return False, f"salaryTooLow: max {hi} < target {target}"
    return True, None


def location_ok(role, profile):
    lr = profile.get("preferences", {}).get("locationRule", {})
    text = f"{role.get('location','')} {role.get('remoteStatus','')} {role.get('remoteNotes','')}".lower()
    metro = [m.lower() for m in lr.get("metroIncludeAnyArrangement", [])]
    if NY_METRO_RE.search(text) or any(m in text for m in metro):
        return True, None                  # NYC metro, any arrangement

    # Enforce US remote scope: a foreign location with no US signal is out of scope.
    if lr.get("includeRemoteScope", "US").upper() == "US":
        if NON_US_RE.search(text) and not US_RE.search(text):
            return False, "locationNonUS: outside US remote scope"

    is_remote = "remote" in text
    if is_remote:
        # remote but tied to a non-US / non-metro geography that requires presence
        if re.search(r"hybrid|on-?site|in-office", text) and not any(m in text for m in metro):
            return False, "locationHybrid: hybrid/onsite outside NYC metro"
        return True, None                  # treat remote (incl. remote-US) as include
    if re.search(r"hybrid|on-?site|in-office", text):
        return False, "locationHybrid: hybrid/onsite outside NYC metro"
    return True, None                      # unknown -> inclusive default


def description_ok(role, profile):
    skips = profile.get("matching", {}).get("descriptionSkips", [])
    if not skips:
        return True, None
    desc = (role.get("fullDescription") or role.get("description") or "").lower()
    title = (role.get("title") or "").lower()
    presales = any(k in title for k in ["solutions engineer", "forward deployed", "sales engineer",
                                        "pre-sales", "solutions architect", "solutions consultant"])
    strong = sum(1 for s in QUOTA_SIGNALS if s in desc)
    # Skip only on strong, central quota signals -- and keep pre-sales SE/FDE roles.
    if strong >= 2 and not presales:
        return False, "descriptionSkip: quota-carrying sales role"
    return True, None


# --------------------------------------------------------------------- scoring
def detect_domain_bonus(text):
    t = text.lower()
    if any(k in t for k in PRIORITY_KW):
        return 100, True
    if any(k in t for k in ADJACENT_KW):
        return 70, False
    return 40, False


# matchPercent = (W_TITLE x title/role-type) + (W_FIT x skill fit) + (W_DOMAIN x domain).
# Weighted toward actual fit so a strong title alone can't carry a poor-fit role.
# 2026-06-11: rebalanced title->fit (0.55/0.35 -> 0.45/0.45) alongside the evidence-aware
# fit calibration below, so a confident skill-match drives ranking more than the title floor.
W_TITLE, W_FIT, W_DOMAIN = 0.45, 0.45, 0.10
NEUTRAL_FIT = 70  # fit baseline used until a role has been skill-matched (or when low-confidence)


def fit_from_skillmatch(role):
    """Return a 0-100 fit score from the role's cached `skillMatch` (matched vs gaps).

    Evidence-aware (2026-06-11): a bare matched/gaps ratio treats 2-matched/0-gaps the
    same as 10-matched/0-gaps and lets a one-sentence JD hit a perfect fit. Instead we:
      - Laplace-smooth the ratio so extreme ratios at low counts pull toward 50;
      - scale confidence by the total signal count (matched + gaps);
      - scale confidence by JD length (a thin JD can't support a confident fit);
      - blend low-confidence results back toward the neutral baseline.

    Until a role has been assessed (no skillMatch), or when an assessment found no
    concrete signal (0 matched / 0 gaps), fall back to the neutral baseline so the role
    is neither rewarded nor unfairly penalized.
    """
    sm = role.get("skillMatch")
    if not sm:
        return NEUTRAL_FIT
    matched = len(sm.get("matched") or [])
    gaps = len(sm.get("gaps") or [])
    if matched + gaps == 0:
        return NEUTRAL_FIT
    ratio = 100.0 * (matched + 0.5) / (matched + gaps + 1)      # smoothed: 2/0 -> ~83, not 100
    evidence_conf = min(1.0, (matched + gaps) / 6.0)            # more signals -> more confidence
    jd = role.get("fullDescription") or role.get("description") or ""
    jd_conf = 1.0 if len(jd) >= 600 else max(0.3, len(jd) / 600.0)  # thin JD -> low confidence
    conf = evidence_conf * jd_conf
    return ratio * conf + NEUTRAL_FIT * (1 - conf)             # toward neutral when low-confidence


def score(role, profile):
    cand = profile.get("candidate", {})
    title = (role.get("title") or "").lower()
    matching = profile.get("matching", {})
    text = " ".join(str(role.get(k, "")) for k in ("title", "domain", "fullDescription", "description"))
    text += " " + " ".join(role.get("tags", []))

    # required_match: strength of the title/role-type signal
    always = [a.lower() for a in matching.get("alwaysIncludeTitles", [])]
    targets = [x.lower() for x in profile.get("preferences", {}).get("targetTitles", [])]
    secondary = [s.lower() for s in matching.get("secondaryIncludeTitles", {}).get("titles", [])]
    if any(a in title for a in always) or any(tt in title for tt in targets):
        required = 95
    elif any(s in title for s in secondary):
        required = 60   # adjacent title (e.g. Technical Project Manager): include but rank below Program Manager
    elif any(k in title for k in TITLE_KW):
        required = 80
    else:
        required = 55

    # seniority nudge
    if any(s in title for s in ["staff", "principal", "senior", "sr."]):
        required = min(100, required + 3)

    # people-management penalty (candidate prefers IC / player-coach)
    desc = (role.get("fullDescription") or role.get("description") or "").lower()
    if re.search(r"manage a team|people management|direct reports|build and lead a team", desc):
        required -= 12

    # experience penalty: role asks for more years than the candidate has
    yrs = cand.get("yearsExperience")
    m = re.search(r"(\d{1,2})\+?\s*years", desc)
    if yrs and m and int(m.group(1)) > yrs:
        required -= 10

    # Fit comes from the cached skill match (matched vs gaps), not a constant -- this is
    # what lets a 0-matched/many-gap role rank below a clean fit with the same title.
    fit = fit_from_skillmatch(role)
    domain_bonus, is_priority = detect_domain_bonus(text)

    pct = W_TITLE * max(0, required) + W_FIT * fit + W_DOMAIN * domain_bonus
    return int(round(max(0, min(100, pct)))), is_priority


# ----------------------------------------------------------------- normalize
def normalize(raw, source):
    title = raw.get("title") or ""
    company = raw.get("company") or raw.get("companyName") or ""
    url = raw.get("url") or ""
    loc = raw.get("location") or ""
    remote_status = raw.get("remoteStatus")
    if not remote_status:
        lt = loc.lower()
        if "remote" in lt:
            remote_status = "remote"
        elif re.search(r"hybrid", lt):
            remote_status = "hybrid"
        elif loc:
            remote_status = "onsite"
        else:
            remote_status = "unknown"
    source_url, ats_url = classify_urls(url)
    # honor explicit fields if the inbox provided them
    source_url = raw.get("sourceUrl", source_url)
    ats_url = raw.get("atsUrl", ats_url)
    return {
        "id": raw.get("id") or slugify(company, title),
        "company": company,
        "title": title,
        "source": source,
        "appearedInSources": raw.get("appearedInSources", [source]),
        "location": loc,
        "remoteStatus": remote_status,
        "remoteNotes": raw.get("remoteNotes", ""),
        "matchPercent": 0,
        "salaryMin": raw.get("salaryMin"),
        "salaryMax": raw.get("salaryMax"),
        "salaryCurrency": raw.get("salaryCurrency", "USD"),
        "url": ats_url or source_url or url,
        "sourceUrl": source_url,
        "atsUrl": ats_url,
        "rationale": "",
        "tags": raw.get("tags", []),
        "isPriorityDomain": False,
        "postedDate": raw.get("postedDate"),
        "foundDate": TODAY,
        "experienceRequired": raw.get("experienceRequired", ""),
        "roleType": raw.get("roleType", ""),
        "domain": raw.get("domain", ""),
        "fullDescription": raw.get("fullDescription") or raw.get("description", ""),
    }


def make_rationale(role, skip_reason=None):
    if skip_reason:
        return skip_reason
    bits = [f"Title '{role['title']}' matches target roles"]
    if role["isPriorityDomain"]:
        bits.append("in a priority domain")
    if role.get("salaryMax"):
        bits.append("salary in range")
    elif role.get("salaryMin"):
        bits.append("salary partially listed")
    else:
        bits.append("salary not listed")
    return "; ".join(bits) + f". Deterministic score {role['matchPercent']}."


# ------------------------------------------------------------------- pipeline
def gather_candidates(search, log):
    """Return list of (raw_posting, source) from watchlist sweep + inbox."""
    candidates = []

    # 1. Watchlist sweep
    for entry in search.get("watchlist", []):
        ats = entry.get("ats"); slug = entry.get("slug"); company = entry.get("company")
        fetcher = ATS_FETCHERS.get(ats)
        if not fetcher or not slug:
            continue
        try:
            for raw in fetcher(slug):
                raw["company"] = company
                candidates.append((raw, ats))
            log["sources"].append({"watchlist": company, "ats": ats, "status": "ok"})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as e:
            log["sources"].append({"watchlist": company, "ats": ats, "status": f"error: {e}"})

    # 2. Inbox ingest (raw finds from Claude in Chrome)
    inbox = DATA / "inbox"
    if inbox.exists():
        for fp in sorted(inbox.glob("*.json")):
            try:
                payload = load_json(fp, [])
                items = payload if isinstance(payload, list) else payload.get("roles", payload.get("items", []))
                for raw in items:
                    src = raw.get("source", "linkedin")
                    # Enrich ATS-hosted postings from the canonical board API
                    url = raw.get("url", "")
                    if any(h in host_of(url) for h in ENRICHABLE_HOSTS):
                        enriched = enrich_from_ats(url)
                        if enriched:
                            enriched["company"] = raw.get("company") or enriched.get("company")
                            raw = {**raw, **{k: v for k, v in enriched.items() if v}}
                    candidates.append((raw, src))
                log["sources"].append({"inbox": fp.name, "count": len(items), "status": "ok"})
            except (ValueError, OSError) as e:
                log["sources"].append({"inbox": fp.name, "status": f"error: {e}"})
    return candidates


def enrich_from_ats(url):
    """Given an ATS posting URL, fetch the canonical record from the board API."""
    h = host_of(url)
    try:
        if "greenhouse.io" in h:
            m = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", url) or re.search(r"/([^/.]+)/jobs/(\d+)", url)
            if not m:
                return None
            slug, jid = m.group(1), m.group(2)
            for r in fetch_greenhouse(slug):
                if jid in (r.get("url") or ""):
                    return r
        elif "lever.co" in h:
            m = re.search(r"lever\.co/([^/]+)/([0-9a-f-]+)", url)
            if not m:
                return None
            slug, jid = m.group(1), m.group(2)
            for r in fetch_lever(slug):
                if jid in (r.get("url") or ""):
                    return r
        elif "ashbyhq.com" in h:
            m = re.search(r"ashbyhq\.com/([^/]+)/", url)
            if not m:
                return None
            for r in fetch_ashby(m.group(1)):
                if url.rstrip("/").split("/")[-1] in (r.get("url") or ""):
                    return r
        elif "workable.com" in h:
            # apply.workable.com/{slug}/j/{CODE}  or  {slug}.workable.com/j/{CODE}
            m = re.search(r"workable\.com/([^/]+)/j/([^/?#]+)", url)
            if m:
                slug, code = m.group(1), m.group(2)
            else:
                m = re.search(r"https?://([^.]+)\.workable\.com/j/([^/?#]+)", url)
                if not m:
                    return None
                slug, code = m.group(1), m.group(2)
            for r in fetch_workable(slug):
                if code in (r.get("url") or ""):
                    return r
        elif "smartrecruiters.com" in h:
            # jobs.smartrecruiters.com/{slug}/{numericId}[-slug-text]
            m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
            if not m:
                return None
            return _smartrecruiters_detail(m.group(1), m.group(2))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None
    return None


def reenrich(dry_run=False, min_gain=200):
    """Re-fetch full job descriptions for existing roles that have a supported ATS
    URL, replacing thin/snippet descriptions with the canonical ATS text. Recomputes
    the deterministic score and, when a description materially changes, clears any
    cached `skillMatch` so the next run re-assesses it on the fuller text.

    Only touches roles with an enrichable ATS url (see ENRICHABLE_HOSTS). For
    SmartRecruiters this is the step that fills the full JD the watchlist sweep
    intentionally skips. LinkedIn/source-only roles can't be enriched this way and
    are left untouched. Network-bound: run on a machine with access to the ATS APIs
    (not the sandbox)."""
    profile = load_json(DATA / "profile.json", {})
    jobs = load_json(DATA / "jobs.json", {"schemaVersion": 2, "roles": [], "meta": {}})
    roles = jobs.get("roles", [])

    updated = recleared = no_ats = not_found = unchanged = 0
    for role in roles:
        ats_url = role.get("atsUrl") or ""
        if not any(h in host_of(ats_url) for h in ENRICHABLE_HOSTS):
            no_ats += 1
            continue
        try:
            enriched = enrich_from_ats(ats_url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            enriched = None
        if not enriched:
            not_found += 1
            continue

        old_desc = role.get("fullDescription") or role.get("description") or ""
        new_desc = enriched.get("description") or ""
        # Treat it as an upgrade if we have new text AND either the role had no
        # description yet (e.g. list-only SmartRecruiters roles -- fill any real JD)
        # or the ATS text is meaningfully longer than what we had (avoid churn).
        is_upgrade = bool(new_desc) and (
            not old_desc.strip() or len(new_desc) >= len(old_desc) + min_gain)
        if not is_upgrade:
            # still backfill missing salary/location/date even if desc didn't grow
            changed = False
            for k_role, k_raw in (("salaryMin", "salaryMin"), ("salaryMax", "salaryMax"),
                                  ("postedDate", "postedDate")):
                if not role.get(k_role) and enriched.get(k_raw):
                    role[k_role] = enriched[k_raw]; changed = True
            if not role.get("location") and enriched.get("location"):
                role["location"] = enriched["location"]; changed = True
            unchanged += 1
            continue

        role["fullDescription"] = new_desc
        for k in ("salaryMin", "salaryMax"):
            if enriched.get(k) and not role.get(k):
                role[k] = enriched[k]
        if enriched.get("location"):
            role["location"] = enriched["location"]
        if enriched.get("postedDate") and not role.get("postedDate"):
            role["postedDate"] = enriched["postedDate"]

        pct, is_priority = score(role, profile)
        role["matchPercent"] = pct
        role["isPriorityDomain"] = is_priority
        role["rationale"] = make_rationale(role)
        if role.pop("skillMatch", None) is not None:
            recleared += 1
        updated += 1

    print(f"Re-enrich: {updated} updated, {unchanged} already-full, "
          f"{not_found} not found on ATS, {no_ats} have no ATS url.")
    if recleared:
        print(f"  Cleared {recleared} cached skill-match assessment(s) for re-assessment.")
    if dry_run:
        print("(dry run: nothing written)")
        return 0
    if updated or unchanged:
        jobs.setdefault("meta", {})["totalRoles"] = len(roles)
        with open(DATA / "jobs.json", "w") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        print(f"Wrote data/jobs.json ({len(roles)} roles).")
    return 0


# --------------------------------------------------------------- ATS resolution
# Map a company -> its ATS apply listing for roles that arrived source-only (LinkedIn
# / hiring.cafe) and so have no atsUrl. Network-bound: run where the ATS APIs are
# reachable (the user's Mac), not the sandbox.
ATS_GUESS_ORDER = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters")
TITLE_MATCH_THRESHOLD = 0.82          # min similarity to confidently attach an apply link
# Expanded symmetrically on both titles before comparison, so abbreviated board titles
# ("TPM, ... Ops") match canonical ATS titles ("Technical Program Manager, ... Operations").
TITLE_ABBREV = {
    "tpm": "technical program manager", "sr": "senior", "ops": "operations",
    "mgr": "manager", "&": "and",
}


def _parse_ats_url(url):
    """(ats, slug) from an existing ATS posting url, or None."""
    h = host_of(url)
    if "greenhouse.io" in h:
        m = re.search(r"greenhouse\.io/(?:[^/]*/)?([^/?]+)/jobs", url) or re.search(r"greenhouse\.io/([^/?]+)", url)
        return ("greenhouse", m.group(1)) if m else None
    if "lever.co" in h:
        m = re.search(r"lever\.co/([^/?]+)", url)
        return ("lever", m.group(1)) if m else None
    if "ashbyhq.com" in h:
        m = re.search(r"ashbyhq\.com/([^/?]+)", url)
        return ("ashby", m.group(1)) if m else None
    if "workable.com" in h:
        m = re.search(r"workable\.com/([^/?]+)", url) or re.search(r"https?://([^.]+)\.workable\.com", url)
        return ("workable", m.group(1)) if m else None
    if "smartrecruiters.com" in h:
        m = re.search(r"smartrecruiters\.com/([^/?]+)", url)
        return ("smartrecruiters", m.group(1)) if m else None
    return None


def slug_candidates(company):
    """Plausible ATS slugs for a company name, most-likely first."""
    c = (company or "").lower()
    base = re.sub(r"[^a-z0-9]+", "", c)                 # "grafanalabs", "cohere"
    hyph = re.sub(r"[^a-z0-9]+", "-", c).strip("-")     # "grafana-labs"
    first = re.sub(r"[^a-z0-9]", "", c.split()[0]) if c.split() else base
    out = []
    for s in (base, hyph, first):
        if s and s not in out:
            out.append(s)
    return out


def _norm_title(t):
    words = re.sub(r"[^a-z0-9& ]", " ", (t or "").lower()).split()
    return " ".join(TITLE_ABBREV.get(w, w) for w in words)


def title_match_score(a, b):
    return difflib.SequenceMatcher(None, _norm_title(a), _norm_title(b)).ratio()


def best_title_match(title, postings):
    """Return (posting, score) of the best title match, or (None, score) if none clears
    the confidence threshold. Conservative by design: a wrong apply link is worse than none."""
    best, best_score = None, 0.0
    for p in postings:
        s = title_match_score(title, p.get("title", ""))
        if s > best_score:
            best, best_score = p, s
    if best is not None and best_score >= TITLE_MATCH_THRESHOLD:
        return best, best_score
    return None, best_score


def _has_ats_url(role):
    return any(h in (role.get("atsUrl") or "") for h in ENRICHABLE_HOSTS)


def resolve_ats(dry_run=False, allow_guess=True, limit=None, min_gain=200):
    """Attach an ATS apply link (atsUrl) to source-only roles by matching them to the
    company's ATS board. Confident-title-match only. Optionally backfills salary/location
    and swaps a thin scraped JD for the canonical ATS one. Idempotent: resolved roles are
    skipped, and companies/roles that can't be resolved are flagged `atsResolveStatus`."""
    profile = load_json(DATA / "profile.json", {})
    search = load_json(DATA / "search.json", {})
    jobs = load_json(DATA / "jobs.json", {"schemaVersion": 2, "roles": [], "meta": {}})
    roles = jobs.get("roles", [])

    # Known company -> (ats, slug): from the watchlist and from roles that already resolve.
    known = {}
    for w in search.get("watchlist", []):
        if w.get("company") and w.get("ats") and w.get("slug"):
            known[w["company"].strip().lower()] = (w["ats"], w["slug"])
    for r in roles:
        if _has_ats_url(r):
            m = _parse_ats_url(r.get("atsUrl") or "")
            if m:
                known.setdefault((r.get("company") or "").strip().lower(), m)

    pending = [r for r in roles
               if not _has_ats_url(r) and r.get("atsResolveStatus") != "unresolved"]
    by_company = {}
    for r in pending:
        by_company.setdefault((r.get("company") or "").strip(), []).append(r)

    board_cache, resolved, unresolved, reassessed, companies = {}, 0, 0, 0, 0
    for company, comp_roles in by_company.items():
        if limit and companies >= limit:
            break
        companies += 1
        key = company.lower()
        if key in known:
            mappings = [known[key]]
        elif allow_guess:
            mappings = [(ats, slug) for slug in slug_candidates(company) for ats in ATS_GUESS_ORDER]
        else:
            mappings = []

        postings = None
        for ats, slug in mappings:
            ck = (ats, slug)
            if ck not in board_cache:
                try:
                    board_cache[ck] = ATS_FETCHERS[ats](slug)
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
                    board_cache[ck] = []
            if board_cache[ck]:
                postings = board_cache[ck]
                break

        if not postings:
            for r in comp_roles:
                r["atsResolveStatus"] = "unresolved"
            unresolved += len(comp_roles)
            continue

        for r in comp_roles:
            best, _ = best_title_match(r.get("title", ""), postings)
            if not best or not best.get("url"):
                r["atsResolveStatus"] = "unresolved"
                unresolved += 1
                continue
            r["atsUrl"] = best["url"]
            r["url"] = best["url"]
            for k in ("salaryMin", "salaryMax"):
                if not r.get(k) and best.get(k):
                    r[k] = best[k]
            if best.get("location"):
                r["location"] = best["location"]
            # Prefer the canonical ATS JD only when it's materially fuller; re-assess it.
            bd = best.get("description") or ""
            if len(bd) > len(r.get("fullDescription") or "") + min_gain:
                r["fullDescription"] = bd
                if r.pop("skillMatch", None) is not None:
                    reassessed += 1
            r["atsResolveStatus"] = "resolved"
            pct, is_priority = score(r, profile)
            r["matchPercent"], r["isPriorityDomain"] = pct, is_priority
            r["rationale"] = make_rationale(r)
            resolved += 1

    print(f"ATS-resolve: {resolved} roles linked, {unresolved} unresolved "
          f"across {companies} companies.")
    if reassessed:
        print(f"  {reassessed} role(s) had a fuller JD pulled in; their skillMatch was cleared "
              f"for re-assessment.")
    if dry_run:
        print("(dry run: nothing written)")
        return 0
    if resolved or unresolved:
        jobs.setdefault("meta", {})["totalRoles"] = len(roles)
        with open(DATA / "jobs.json", "w") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        print(f"Wrote data/jobs.json ({len(roles)} roles).")
    return 0


def run(dry_run=False, max_age_days=1):
    profile = load_json(DATA / "profile.json", {})
    search = load_json(DATA / "search.json", {})
    jobs = load_json(DATA / "jobs.json", {"schemaVersion": 2, "roles": [], "meta": {}})
    state = load_json(DATA / "state.json", {"jobs": {}})

    if not profile:
        print("ERROR: data/profile.json missing. Run job-search-setup first.", file=sys.stderr)
        return 1

    existing = jobs.get("roles", [])
    seen_urls = {(r.get("url") or "").rstrip("/") for r in existing}
    seen_ids = {r.get("id") for r in existing}
    decided = set(state.get("jobs", {}).keys())

    log = {"date": TODAY, "startedAt": datetime.datetime.now().isoformat(timespec="seconds"),
           "sources": [], "counts": {}}
    skip_breakdown = {}
    cutoff = (datetime.date.today() - datetime.timedelta(days=max_age_days)).isoformat()

    candidates = gather_candidates(search, log)
    reviewed = len(candidates)
    new_roles = []
    batch_urls, batch_ids = set(), set()

    for raw, source in candidates:
        role = normalize(raw, source)

        # dedup (existing + within-batch + already decided)
        ukey = (role["url"] or "").rstrip("/")
        if role["id"] in seen_ids or role["id"] in batch_ids or role["id"] in decided:
            continue
        if ukey and (ukey in seen_urls or ukey in batch_urls):
            continue

        # age filter (only when we actually know the posting date)
        if role.get("postedDate") and role["postedDate"] < cutoff:
            skip_breakdown["expired"] = skip_breakdown.get("expired", 0) + 1
            continue

        # filter cascade
        ok, reason = title_decision(role["title"], profile)
        if ok and not employer_ok(role["company"], profile):
            ok, reason = False, "skipEmployer"
        for check in (salary_ok, location_ok, description_ok):
            if ok:
                ok, reason = check(role, profile)
        if not ok:
            key = reason.split(":")[0]
            skip_breakdown[key] = skip_breakdown.get(key, 0) + 1
            continue

        # score
        pct, is_priority = score(role, profile)
        role["matchPercent"] = pct
        role["isPriorityDomain"] = is_priority
        role["rationale"] = make_rationale(role)

        new_roles.append(role)
        batch_ids.add(role["id"])
        if ukey:
            batch_urls.add(ukey)

    log["counts"] = {"reviewed": reviewed, "qualified": len(new_roles), "skipped": skip_breakdown}

    print(f"Reviewed {reviewed} postings -> {len(new_roles)} new qualified roles.")
    if skip_breakdown:
        print("Skips:", ", ".join(f"{k}={v}" for k, v in sorted(skip_breakdown.items())))
    top = sorted(new_roles, key=lambda r: -r["matchPercent"])[:10]
    for r in top:
        print(f"  {r['matchPercent']:>3}  {r['company']} — {r['title']}")

    if dry_run:
        print("(dry run: nothing written)")
        return 0

    jobs["roles"] = existing + new_roles
    jobs.setdefault("meta", {})["lastRun"] = TODAY
    jobs["meta"]["totalRoles"] = len(jobs["roles"])
    with open(DATA / "jobs.json", "w") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)

    sl = load_json(DATA / "search-log.json", {"schemaVersion": 1, "runs": []})
    sl.setdefault("runs", []).append(log)
    with open(DATA / "search-log.json", "w") as f:
        json.dump(sl, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(new_roles)} new roles to data/jobs.json ({len(jobs['roles'])} total).")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Deterministic job-search pipeline. By default a single run does "
                    "the full job: discovery sweep, then a re-enrich pass over roles "
                    "with an enrichable ATS url.")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--max-age-days", type=int, default=1, help="max posting age to include (default 1)")
    ap.add_argument("--reenrich", action="store_true",
                    help="ONLY refetch full JDs for existing ATS roles; skip discovery")
    ap.add_argument("--resolve-ats", action="store_true",
                    help="ONLY resolve & attach ATS apply links for source-only roles; skip discovery")
    ap.add_argument("--no-guess", action="store_true",
                    help="with --resolve-ats: only use known watchlist/existing mappings, no slug guessing")
    ap.add_argument("--limit", type=int, default=None,
                    help="with --resolve-ats: cap how many companies to attempt this run")
    ap.add_argument("--sweep-only", action="store_true",
                    help="ONLY run the discovery sweep; skip the follow-on re-enrich pass")
    args = ap.parse_args()

    # --reenrich: enrich-only, no discovery.
    if args.reenrich:
        sys.exit(reenrich(dry_run=args.dry_run))

    # --resolve-ats: attach apply links to source-only roles, no discovery.
    if args.resolve_ats:
        sys.exit(resolve_ats(dry_run=args.dry_run, allow_guess=not args.no_guess, limit=args.limit))

    # Default: full pipeline in one command -- sweep, then re-enrich. The sweep
    # persists new roles first (unless --dry-run), so the re-enrich pass sees and
    # fills them (e.g. SmartRecruiters JDs) in the same invocation. --sweep-only
    # stops after discovery.
    rc = run(dry_run=args.dry_run, max_age_days=args.max_age_days)
    if rc == 0 and not args.sweep_only:
        print("\n— re-enrich pass —")
        rc = reenrich(dry_run=args.dry_run)
    sys.exit(rc)


if __name__ == "__main__":
    main()
