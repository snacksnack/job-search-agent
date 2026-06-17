#!/usr/bin/env python3
"""
web_enrich.py — I/O helper for one-time browser enrichment of source-only roles.

Some roles (LinkedIn / hiring.cafe finds with no Greenhouse/Lever/Ashby API behind
them) arrive with only a thin snippet. They can't be enriched via the ATS APIs
(`pipeline.py --reenrich` handles those); instead the full job description has to be
read from the posting page in the browser via Claude in Chrome.

This script is the deterministic plumbing around that LLM/browser step — it does NO
browsing itself:

  --list-pending   Print roles that still need browser enrichment: source-only,
                   thin description, with a link to visit. Sorted by matchPercent
                   (highest-value first) so a partial pass still does the best roles.
                   Use --limit to chunk the work and --source to filter by site.

  --apply FILE     Merge browser-extracted descriptions back into data/jobs.json
                   atomically. FILE is JSON: a list (or {id: {...}} map) of
                   {id, fullDescription, [salaryMin], [salaryMax], [location],
                   [postedDate]}. Rescoring uses pipeline.score; when a description
                   materially grows, the cached skillMatch is cleared so the next
                   Cowork run re-assesses it on the full text.

Stdlib only. Python 3.11+.
"""
import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import score, make_rationale  # reuse the deterministic scorer

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
JOBS_PATH = DATA / "jobs.json"

THIN_CHARS = 300       # below this a description counts as "needs enrichment"
GROW_GAIN = 200        # apply must add at least this many chars to count as an upgrade
ATS_HOSTS = ("greenhouse.io", "lever.co", "ashbyhq.com")


def load_jobs():
    with open(JOBS_PATH) as f:
        return json.load(f)


def atomic_write_json(path, obj):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _desc(r):
    return r.get("fullDescription") or r.get("description") or ""


def _has_ats(r):
    u = r.get("atsUrl") or ""
    return any(h in u for h in ATS_HOSTS)


def _link(r):
    return r.get("sourceUrl") or r.get("url") or ""


def is_pending(r):
    if r.get("enrichStatus") == "expired":   # confirmed dead posting; don't keep retrying
        return False
    return (not _has_ats(r)) and len(_desc(r)) < THIN_CHARS and bool(_link(r))


def list_pending(limit=None, source=None):
    jobs = load_jobs()
    rows = []
    for r in jobs.get("roles", []):
        if not is_pending(r):
            continue
        link = _link(r)
        host = urlparse(link).netloc.lower()
        if source == "linkedin" and "linkedin" not in host:
            continue
        if source == "hiringcafe" and "hiring.cafe" not in host:
            continue
        rows.append({
            "id": r.get("id"),
            "company": r.get("company"),
            "title": r.get("title"),
            "matchPercent": r.get("matchPercent", 0),
            "url": link,
            "currentDescLen": len(_desc(r)),
        })
    rows.sort(key=lambda x: -x["matchPercent"])
    if limit:
        rows = rows[:limit]
    return rows


def apply_enrichments(path):
    with open(path) as f:
        payload = json.load(f)
    if isinstance(payload, dict) and "enrichments" in payload:
        payload = payload["enrichments"]
    if isinstance(payload, list):
        by_id = {e["id"]: e for e in payload if e.get("id")}
    elif isinstance(payload, dict):
        by_id = payload
    else:
        raise ValueError("apply file must be a list or an object")

    with open(DATA / "profile.json") as f:
        profile = json.load(f)
    jobs = load_jobs()
    index = {r.get("id"): r for r in jobs.get("roles", [])}
    updated, recleared, unknown, skipped = 0, 0, [], 0

    for rid, e in by_id.items():
        role = index.get(rid)
        if not role:
            unknown.append(rid)
            continue
        new_desc = (e.get("fullDescription") or "").strip()
        old_len = len(_desc(role))
        if len(new_desc) < old_len + GROW_GAIN:
            skipped += 1
            continue
        role["fullDescription"] = new_desc
        for k in ("salaryMin", "salaryMax"):
            if e.get(k) is not None:
                role[k] = e[k]
        if e.get("location"):
            role["location"] = e["location"]
        if e.get("postedDate"):
            role["postedDate"] = e["postedDate"]
        role["enrichedVia"] = "web"
        pct, is_priority = score(role, profile)
        role["matchPercent"] = pct
        role["isPriorityDomain"] = is_priority
        role["rationale"] = make_rationale(role)
        if role.pop("skillMatch", None) is not None:
            recleared += 1
        updated += 1

    atomic_write_json(JOBS_PATH, jobs)
    return updated, recleared, skipped, unknown


def main():
    ap = argparse.ArgumentParser(description="Browser-enrichment I/O helper (source-only roles)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list-pending", action="store_true", help="print roles needing browser enrichment")
    g.add_argument("--apply", metavar="FILE", help="merge a browser-extracted enrichment JSON file")
    g.add_argument("--stats", action="store_true", help="print pending counts by source")
    ap.add_argument("--limit", type=int, default=None, help="with --list-pending: cap how many to emit")
    ap.add_argument("--source", choices=["linkedin", "hiringcafe", "all"], default="all",
                    help="with --list-pending: filter by posting host")
    args = ap.parse_args()

    if args.stats:
        rows = list_pending()
        li = sum(1 for r in rows if "linkedin" in urlparse(r["url"]).netloc)
        hc = sum(1 for r in rows if "hiring.cafe" in urlparse(r["url"]).netloc)
        print(f"pending={len(rows)} linkedin={li} hiringcafe={hc} other={len(rows) - li - hc}")
        return 0

    if args.list_pending:
        rows = list_pending(limit=args.limit, source=(None if args.source == "all" else args.source))
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if args.apply:
        updated, recleared, skipped, unknown = apply_enrichments(args.apply)
        print(f"Applied {updated} enrichment(s); skipped {skipped} (no material gain).")
        if recleared:
            print(f"  Cleared {recleared} cached skill-match assessment(s) for re-assessment.")
        if unknown:
            print(f"  {len(unknown)} unknown id(s): {', '.join(unknown[:8])}"
                  + (" …" if len(unknown) > 8 else ""), file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
