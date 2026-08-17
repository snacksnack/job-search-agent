#!/usr/bin/env python3
"""
title_rescue.py — I/O helper for the LLM title-rescue pass (RC1-277).

The keyword title filter in scripts/pipeline.py drops nonstandard phrasings it
can't enumerate ("PgM III", "Program Mgr", "Technical Programme Manager"). Each
run the pipeline saves fresh title-rejected postings to
data/queue/title-rescue.json; the judgment call — which of those titles are
plausibly in-scope — is LLM work done by the daily-job-search skill. This script
does only the deterministic plumbing around it:

  --list-pending   Print the DISTINCT pending titles, numbered, with posting
                   counts and sample companies (titles only — the review is cheap
                   by design; no JDs are sent).

  --apply FILE     FILE is JSON: {"approved": ["<exact title>", ...]} (or a bare
                   list of titles). Every queued posting whose title matches an
                   approved title (case-insensitive) re-enters the filter cascade
                   with the title check skipped: employer/salary/location/
                   description checks still apply, then the role is scored,
                   flagged `titleRescued`, deduped against jobs.json/state.json,
                   and appended to jobs.json. The queue file is then cleared.

  --stats          Queue date + posting/title counts.

Conservative by contract: the reviewing session should approve only titles a
senior program/delivery/solutions/customer-engineering candidate would credibly
hold — never SWE/product/marketing/sales/support/people-leadership titles.
Failure of the review is non-fatal: the queue is simply replaced on the next run.

Stdlib only. Python 3.11+.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import (salary_ok, location_ok, description_ok, employer_ok,  # noqa: E402
                      score, make_rationale, role_content_hash)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
QUEUE_PATH = DATA / "queue" / "title-rescue.json"
JOBS_PATH = DATA / "jobs.json"


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


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


def _queue_roles():
    return load_json(QUEUE_PATH, {}).get("roles", [])


def list_pending():
    """Distinct titles with counts + sample companies, cheapest-possible review unit."""
    by_title = {}
    for r in _queue_roles():
        t = (r.get("title") or "").strip()
        if not t:
            continue
        e = by_title.setdefault(t, {"title": t, "count": 0, "companies": []})
        e["count"] += 1
        c = r.get("company") or ""
        if c and c not in e["companies"] and len(e["companies"]) < 3:
            e["companies"].append(c)
    return sorted(by_title.values(), key=lambda e: (-e["count"], e["title"].lower()))


def apply_verdicts(path):
    """Re-run approved-title postings through the cascade (title check skipped)."""
    payload = load_json(path, None)
    if payload is None:
        raise ValueError(f"cannot read verdict file {path}")
    approved = payload.get("approved", payload) if isinstance(payload, dict) else payload
    if not isinstance(approved, list):
        raise ValueError('verdict file must be {"approved": [titles]} or a list of titles')
    approved_lc = {str(t).strip().lower() for t in approved}

    profile = load_json(DATA / "profile.json", {})
    jobs = load_json(JOBS_PATH, {"schemaVersion": 2, "roles": [], "meta": {}})
    state = load_json(DATA / "state.json", {"jobs": {}})
    roles = jobs.get("roles", [])
    seen_ids = {r.get("id") for r in roles} | set(state.get("jobs", {}).keys())
    seen_urls = {(r.get("url") or "").rstrip("/") for r in roles}

    rescued, filtered, duplicate = [], 0, 0
    for role in _queue_roles():
        if (role.get("title") or "").strip().lower() not in approved_lc:
            continue
        ukey = (role.get("url") or "").rstrip("/")
        if role.get("id") in seen_ids or (ukey and ukey in seen_urls):
            duplicate += 1
            continue
        ok = employer_ok(role.get("company"), profile)
        reason = None if ok else "skipEmployer"
        for check in (salary_ok, location_ok, description_ok):
            if ok:
                ok, reason = check(role, profile)
        if not ok:
            filtered += 1
            continue
        pct, is_priority = score(role, profile)
        role["matchPercent"] = pct
        role["isPriorityDomain"] = is_priority
        role["titleRescued"] = True
        role["rationale"] = (make_rationale(role)
                             + " Title-rescued by LLM review — double-check role scope.")
        role["contentHash"] = role_content_hash(role)
        rescued.append(role)
        seen_ids.add(role.get("id"))
        if ukey:
            seen_urls.add(ukey)

    if rescued:
        jobs["roles"] = roles + rescued
        jobs.setdefault("meta", {})["totalRoles"] = len(jobs["roles"])
        atomic_write_json(JOBS_PATH, jobs)
    # Clear the queue either way: verdicts were rendered for this batch.
    if QUEUE_PATH.exists():
        atomic_write_json(QUEUE_PATH, {"date": load_json(QUEUE_PATH, {}).get("date"), "roles": []})
    return rescued, filtered, duplicate


def main():
    ap = argparse.ArgumentParser(description="I/O plumbing for the LLM title-rescue pass.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list-pending", action="store_true",
                   help="print distinct pending titles (JSON) for LLM review")
    g.add_argument("--apply", metavar="FILE",
                   help='merge verdicts: {"approved": ["<title>", ...]}')
    g.add_argument("--stats", action="store_true", help="queue counts")
    args = ap.parse_args()

    if args.stats:
        q = load_json(QUEUE_PATH, {})
        roles = q.get("roles", [])
        print(f"queue date={q.get('date')} postings={len(roles)} "
              f"titles={len({(r.get('title') or '').lower() for r in roles})}")
        return
    if args.list_pending:
        print(json.dumps(list_pending(), indent=2, ensure_ascii=False))
        return
    rescued, filtered, duplicate = apply_verdicts(args.apply)
    print(f"Title-rescue: {len(rescued)} role(s) rescued onto the board, "
          f"{filtered} approved-title role(s) failed later filters, "
          f"{duplicate} duplicate(s) skipped.")
    for r in rescued:
        print(f"  {r.get('matchPercent'):>3}  {r.get('company')} — {r.get('title')}")


if __name__ == "__main__":
    main()
