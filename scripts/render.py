#!/usr/bin/env python3
"""Render the job board to a self-contained HTML page.

Source of truth = local JSON: data/jobs.json (roles) + data/state.json
(applied/hidden/status decisions). This module exposes `render_html(jobs,
state)` which scripts/serve.py imports to render live, and a CLI that writes a
static snapshot to data/board.html.

The board's action buttons (Mark Applied / Hide / Draft Cover Letter) POST to
the local server in scripts/serve.py, which writes decisions straight back to
state.json -- one source of truth, no second store to reconcile.
"""
import json
import html
import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSETS = Path(__file__).resolve().parent / "assets"   # board.html shell, board.css, board.js

# Statuses that are hidden from the default view (revealed by header toggles).
APPLIED_STATUSES = {"applied", "interviewing", "offer", "rejected"}


def _read_asset(name):
    return (ASSETS / name).read_text(encoding="utf-8")


def esc(s):
    return html.escape(str(s)) if s is not None else ""


def salary_str(r):
    lo, hi = r.get("salaryMin"), r.get("salaryMax")
    cur = r.get("salaryCurrency", "USD")
    sym = "$" if cur in ("USD", None) else f"{cur} "
    if lo and hi:
        return f"{sym}{lo // 1000}K\u2013{sym}{hi // 1000}K"
    if lo:
        return f"{sym}{lo // 1000}K+"
    return "Not specified"


def load_json(path, default):
    p = Path(path)
    if not p.exists():
        return default
    with open(p) as f:
        return json.load(f)


def _search_blob(r):
    """Lowercased text blob used for client-side search (board + table)."""
    sm = r.get("skillMatch") or {}
    matched = sm.get("matched", []) or []
    gaps = sm.get("gaps", []) or []
    return " ".join(str(x).lower() for x in [
        r.get("title", ""), r.get("company", ""), " ".join(r.get("tags", [])),
        r.get("location", ""), r.get("domain", ""),
        " ".join(matched), " ".join(gaps),
    ])


def _role_sort_key(r):
    """Default board/table ordering: priority domains first, then match desc."""
    return (not r.get("isPriorityDomain", False), -r.get("matchPercent", 0))


# ----------------------------------------------------------- interview-prep view
import re  # noqa: E402  (kept local to this section's helpers)

PREP_DIR = DATA / "interview-prep"
_ROLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")   # role ids are slugs; guards path traversal


def prep_path(role_id):
    return PREP_DIR / role_id / f"prep-{role_id}.md"


def has_prep(role_id):
    return bool(role_id) and _ROLE_ID_RE.match(role_id) and prep_path(role_id).exists()


def _inline_md(text):
    """Inline markdown -> HTML on already-escaped text: code, links, bold, italic."""
    s = esc(text)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
    return s


def md_to_html(md):
    """Minimal, dependency-free Markdown -> HTML for our own prep packs.
    Handles headings, bold/italic/code/links, fenced code, ordered/unordered
    lists, horizontal rules, and paragraphs."""
    out, para, list_tag, in_code = [], [], None, False

    def flush_para():
        if para:
            out.append("<p>" + "<br>".join(_inline_md(x) for x in para) + "</p>")
            para.clear()

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in (md or "").replace("\r\n", "\n").split("\n"):
        if raw.strip().startswith("```"):
            flush_para(); close_list()
            if in_code:
                out.append("</code></pre>"); in_code = False
            else:
                out.append("<pre><code>"); in_code = True
            continue
        if in_code:
            out.append(esc(raw))
            continue

        line = raw.rstrip()
        if not line.strip():
            flush_para(); close_list(); continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_para(); close_list()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{_inline_md(m.group(2))}</h{lvl}>")
            continue
        if re.match(r"^(---+|\*\*\*+)$", line.strip()):
            flush_para(); close_list(); out.append("<hr>"); continue

        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            flush_para()
            if list_tag != "ul":
                close_list(); out.append("<ul>"); list_tag = "ul"
            out.append(f"<li>{_inline_md(m.group(1))}</li>"); continue
        m = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m:
            flush_para()
            if list_tag != "ol":
                close_list(); out.append("<ol>"); list_tag = "ol"
            out.append(f"<li>{_inline_md(m.group(1))}</li>"); continue

        close_list()
        para.append(line)

    flush_para(); close_list()
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def _prep_page(title, body_html):
    css = _read_asset("board.css")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
{css}
.prepwrap {{ max-width:820px; margin:0 auto; padding:32px 22px 80px; }}
.prepwrap a.back {{ color:var(--muted); font-size:13px; text-decoration:none; }}
.prepwrap a.back:hover {{ color:var(--accent); }}
.prose h1 {{ font-size:24px; margin:18px 0 10px; }}
.prose h2 {{ font-size:19px; margin:24px 0 8px; border-top:1px solid var(--line); padding-top:18px; }}
.prose h3 {{ font-size:16px; margin:18px 0 6px; color:#c6cad8; }}
.prose p {{ color:#c2c7d4; font-size:14px; line-height:1.6; }}
.prose li {{ color:#c2c7d4; font-size:14px; line-height:1.55; margin:3px 0; }}
.prose ul, .prose ol {{ padding-left:22px; }}
.prose code {{ background:var(--card2); padding:1px 5px; border-radius:5px; font-size:13px; }}
.prose pre {{ background:var(--card2); padding:12px 14px; border-radius:9px; overflow:auto; }}
.prose pre code {{ background:none; padding:0; }}
.prose a {{ color:var(--accent); }}
.prose hr {{ border:0; border-top:1px solid var(--line); margin:18px 0; }}
</style></head>
<body><div class="prepwrap">
<a class="back" href="/">\u2190 Back to board</a>
<div class="prose">{body_html}</div>
</div></body></html>"""


def render_prep_page(role_id):
    """Return (status_code, html) for GET /prep/{role_id}. 404 only for an unsafe id;
    a missing pack returns a friendly 'not generated yet' page (200)."""
    if not role_id or not _ROLE_ID_RE.match(role_id):
        return 404, _prep_page("Not found", "<h1>Not found</h1><p>Unknown role.</p>")
    p = prep_path(role_id)
    if not p.exists():
        body = (f"<h1>No interview prep yet</h1><p>Nothing has been generated for "
                f"<code>{esc(role_id)}</code>.</p><p>Queue it with the "
                f"<strong>Interview Prep</strong> button on the board, then run "
                f"\u201cdo my queued interview prep\u201d in Cowork.</p>")
        return 200, _prep_page("Interview prep \u2014 pending", body)
    return 200, _prep_page(f"Interview prep \u2014 {role_id}", md_to_html(p.read_text(encoding="utf-8")))


def _card(r, dec):
    rid = r["id"]
    status = (dec.get("status") or "new").lower()
    hidden = status == "hidden"
    applied = status in APPLIED_STATUSES
    pri = r.get("isPriorityDomain", False)
    prep = has_prep(rid)

    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in r.get("tags", []))
    sources = ", ".join(r.get("appearedInSources", [r.get("source", "")]))
    # Only render the Posted field when we actually have a date (was "Posted \u2014").
    posted = r.get("postedDate")
    posted_span = f'<span>\U0001F4C5 Posted {esc(posted)}</span>' if posted else ""

    # Source + ATS links
    src_url = r.get("sourceUrl") or ""
    ats_url = r.get("atsUrl") or ""
    link_parts = []
    if src_url:
        link_parts.append(f'<a class="jlink src" href="{esc(src_url)}" target="_blank" rel="noopener">\U0001F517 Source listing</a>')
    else:
        link_parts.append('<span class="jlink pending">Source \u2014 pending</span>')
    if ats_url:
        link_parts.append(f'<a class="jlink ats" href="{esc(ats_url)}" target="_blank" rel="noopener">\U0001F4DD Apply (ATS)</a>')
    else:
        link_parts.append('<span class="jlink pending">Apply (ATS) \u2014 pending</span>')
    if has_prep(rid):
        link_parts.append(f'<a class="jlink prep" href="/prep/{esc(rid)}" target="_blank" rel="noopener">\U0001F4CB View Interview Prep</a>')
    links_row = '<div class="links">' + "".join(link_parts) + "</div>"

    # Skill match (matched = green chips, gaps = amber chips), cached on the role
    # by the daily-job-search skill-match subagent. Absent until assessed.
    sm = r.get("skillMatch") or {}
    matched = sm.get("matched", []) or []
    gaps = sm.get("gaps", []) or []
    if matched or gaps:
        chips = "".join(f'<span class="chip chip-match" title="on your resume">{esc(s)}</span>' for s in matched)
        chips += "".join(f'<span class="chip chip-gap" title="requested but not on your resume">{esc(s)}</span>' for s in gaps)
        sm_rat = f'<div class="sm-rationale">{esc(sm.get("rationale"))}</div>' if sm.get("rationale") else ""
        skills_block = (f'<div class="skillmatch"><div class="sm-label">'
                        f'Skill match <span class="sm-counts">{len(matched)} matched \u00b7 {len(gaps)} gaps</span></div>'
                        f'<div class="chips">{chips}</div>{sm_rat}</div>')
    else:
        skills_block = '<div class="skillmatch pending"><span class="sm-pending">Skill match \u2014 pending assessment</span></div>'

    # Search blob for client-side filtering (includes matched + gap skills)
    blob = _search_blob(r)

    status_badge = f'<span class="status status-{esc(status)}">{esc(status).title()}</span>'
    pri_badge = '<span class="pri-badge">Priority</span>' if pri else ""
    prep_badge = '<span class="prep-flag" title="Interview prep pack generated">\U0001F4CB Prep</span>' if prep else ""
    classes = "card" + (" hidden-card" if hidden else "") + (" applied-card" if applied else "") + (" priority" if pri else "")

    status_opts = "".join(
        f'<option value="{v}"{" selected" if status == v else ""}>{label}</option>'
        for v, label in (("new", "New"), ("applied", "Applied"), ("interviewing", "Interviewing"),
                         ("offer", "Offer"), ("rejected", "Rejected"), ("hidden", "Hidden")))

    return f"""
    <div class="{classes}" data-id="{esc(rid)}" data-status="{esc(status)}" data-search="{esc(blob)}" data-priority="{'1' if pri else '0'}" data-prep="{'1' if prep else '0'}">
      <div class="card-head">
        <div class="match">{r.get('matchPercent', 0)}</div>
        <div class="title-wrap">
          <div class="role-title">{esc(r.get('title'))}</div>
          <div class="company">{esc(r.get('company'))}</div>
        </div>
        <div class="badges">{pri_badge}{prep_badge}{status_badge}</div>
      </div>
      <div class="meta">
        <span>\U0001F4B0 {esc(salary_str(r))}</span>
        <span>\U0001F4CD {esc(r.get('location'))}</span>
        <span>\U0001F3E0 {esc(r.get('remoteStatus'))}</span>
        {posted_span}
        <span>\U0001F50E {esc(sources)}</span>
      </div>
      <div class="tags">{tags}</div>
      <div class="rationale">{esc(r.get('rationale'))}</div>
      {skills_block}
      {links_row}
      <div class="actions">
        <label class="status-picker">Status
          <select class="status-select" onchange="decide('{esc(rid)}', this.value, this)">{status_opts}</select>
        </label>
        <button class="btn cover-btn" data-action="cover" onclick="queueCover('{esc(rid)}', this)">Draft Cover Letter</button>
        <button class="btn prep-btn" data-action="prep" onclick="queuePrep('{esc(rid)}', this)">Interview Prep</button>
      </div>
    </div>"""


def render_html(jobs, state, run_date=None):
    roles = jobs.get("roles", [])
    decisions = state.get("jobs", {})
    run_date = run_date or datetime.date.today().isoformat()

    roles_sorted = sorted(roles, key=_role_sort_key)

    total = len(roles_sorted)
    applied = sum(1 for r in roles_sorted if (decisions.get(r["id"], {}).get("status") or "").lower() in APPLIED_STATUSES)
    hidden = sum(1 for r in roles_sorted if (decisions.get(r["id"], {}).get("status") or "").lower() == "hidden")
    active = [r for r in roles_sorted if (decisions.get(r["id"], {}).get("status") or "new").lower() not in (APPLIED_STATUSES | {"hidden"})]
    top_match = max((r.get("matchPercent", 0) for r in active), default=0)

    cards = "".join(_card(r, decisions.get(r["id"], {})) for r in roles_sorted)

    # Assemble the page from the asset files. CSS/JS/cards are inserted by plain
    # string replacement (never str.format), so no brace-escaping is needed in them.
    page = _read_asset("board.html")
    replacements = {
        "{{CSS}}": _read_asset("board.css"),
        "{{JS}}": _read_asset("board.js"),
        "{{CARDS}}": cards,
        "{{RUN_DATE}}": esc(run_date),
        "{{TOTAL}}": str(total),
        "{{APPLIED}}": str(applied),
        "{{HIDDEN}}": str(hidden),
        "{{SHOWN}}": str(len(active)),
        "{{TOP_MATCH}}": str(top_match),
        "{{GENERATED}}": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    for token, value in replacements.items():
        page = page.replace(token, value)
    return page


# --------------------------------------------------------------- compact table view


def _row(r, dec):
    """One <tr> for the compact /table view. Carries the same data-* hooks the
    board cards use (status/search/prep/priority) plus per-column sort values."""
    rid = r["id"]
    status = (dec.get("status") or "new").lower()
    hidden = status == "hidden"
    applied = status in APPLIED_STATUSES
    pri = r.get("isPriorityDomain", False)
    prep = has_prep(rid)
    blob = _search_blob(r)

    posted = r.get("postedDate") or ""
    salary_val = r.get("salaryMax") or r.get("salaryMin") or 0
    sources = ", ".join(r.get("appearedInSources", [r.get("source", "")]))

    src_url = r.get("sourceUrl") or ""
    ats_url = r.get("atsUrl") or ""
    link_bits = []
    if src_url:
        link_bits.append(f'<a class="tlink" href="{esc(src_url)}" target="_blank" rel="noopener" title="Source listing">\U0001F517</a>')
    if ats_url:
        link_bits.append(f'<a class="tlink" href="{esc(ats_url)}" target="_blank" rel="noopener" title="Apply (ATS)">\U0001F4DD</a>')
    links_cell = "".join(link_bits) or '<span class="prep-no">\u2014</span>'

    if prep:
        prep_cell = (f'<a class="tlink prep" href="/prep/{esc(rid)}" target="_blank" '
                     f'rel="noopener" title="View interview prep">\U0001F4CB</a>')
    else:
        prep_cell = '<span class="prep-no" title="No prep pack yet">\u2014</span>'

    status_opts = "".join(
        f'<option value="{v}"{" selected" if status == v else ""}>{label}</option>'
        for v, label in (("new", "New"), ("applied", "Applied"), ("interviewing", "Interviewing"),
                         ("offer", "Offer"), ("rejected", "Rejected"), ("hidden", "Hidden")))

    classes = "row" + (" row-hidden" if hidden else "") + (" row-applied" if applied else "") + (" row-priority" if pri else "")
    pri_dot = '<span class="pri-dot" title="Priority domain">\u25CF</span> ' if pri else ""
    posted_cell = esc(posted) or "\u2014"
    company_key = esc((r.get("company") or "").lower())
    title_key = esc((r.get("title") or "").lower())

    return f"""
    <tr class="{classes}" data-id="{esc(rid)}" data-status="{esc(status)}" data-search="{esc(blob)}" data-prep="{'1' if prep else '0'}" data-priority="{'1' if pri else '0'}" data-score="{r.get('matchPercent', 0)}" data-salary="{salary_val}" data-posted="{esc(posted)}" data-company="{company_key}" data-title="{title_key}">
      <td class="c-score">{r.get('matchPercent', 0)}</td>
      <td class="c-title">{pri_dot}{esc(r.get('title'))}</td>
      <td class="c-company">{esc(r.get('company'))}</td>
      <td class="c-salary">{esc(salary_str(r))}</td>
      <td class="c-loc">{esc(r.get('location'))}</td>
      <td class="c-posted">{posted_cell}</td>
      <td class="c-src">{esc(sources)}</td>
      <td class="c-status">
        <select class="t-status-select status-{esc(status)}" onchange="decide('{esc(rid)}', this.value, this)">{status_opts}</select>
      </td>
      <td class="c-prep">{prep_cell}</td>
      <td class="c-links">{links_cell}</td>
    </tr>"""


def render_table_html(jobs, state, run_date=None):
    roles = jobs.get("roles", [])
    decisions = state.get("jobs", {})
    run_date = run_date or datetime.date.today().isoformat()

    roles_sorted = sorted(roles, key=_role_sort_key)

    total = len(roles_sorted)
    applied = sum(1 for r in roles_sorted if (decisions.get(r["id"], {}).get("status") or "").lower() in APPLIED_STATUSES)
    hidden = sum(1 for r in roles_sorted if (decisions.get(r["id"], {}).get("status") or "").lower() == "hidden")
    active = [r for r in roles_sorted if (decisions.get(r["id"], {}).get("status") or "new").lower() not in (APPLIED_STATUSES | {"hidden"})]
    top_match = max((r.get("matchPercent", 0) for r in active), default=0)

    rows = "".join(_row(r, decisions.get(r["id"], {})) for r in roles_sorted)

    page = _read_asset("table.html")
    replacements = {
        "{{CSS}}": _read_asset("board.css"),
        "{{JS}}": _read_asset("table.js"),
        "{{ROWS}}": rows,
        "{{RUN_DATE}}": esc(run_date),
        "{{TOTAL}}": str(total),
        "{{APPLIED}}": str(applied),
        "{{HIDDEN}}": str(hidden),
        "{{SHOWN}}": str(len(active)),
        "{{TOP_MATCH}}": str(top_match),
        "{{GENERATED}}": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    for token, value in replacements.items():
        page = page.replace(token, value)
    return page


def main():
    jobs = load_json(DATA / "jobs.json", {"roles": []})
    state = load_json(DATA / "state.json", {"jobs": {}})
    out = render_html(jobs, state)
    (DATA / "board.html").write_text(out, encoding="utf-8")
    roles = jobs.get("roles", [])
    print(f"Wrote {DATA / 'board.html'}: {len(roles)} roles")


if __name__ == "__main__":
    main()
