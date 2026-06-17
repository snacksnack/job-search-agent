#!/usr/bin/env python3
"""
skill_match.py — I/O helper for the LLM skill-to-JD assessment (Option B).

The actual matching is judgment work done by the daily-job-search skill via a
Sonnet-pinned subagent (see skills/daily-job-search/SKILL.md). This script does
only the deterministic, token-free plumbing around it:

  --list-pending   Print the roles that still need an assessment (those with no
                   `skillMatch` yet), trimmed to just what the subagent needs to
                   read (id, company, title, location, description). Keeps the
                   subagent's token use scoped to new JDs, not the whole file.

  --apply FILE     Merge assessments back into data/jobs.json atomically. FILE is
                   JSON: either a {id: {matched, gaps, rationale}} map or a list of
                   {id, matched, gaps, rationale} objects. Each role gets a
                   `skillMatch` block stamped with the model and date.

Assessments are cached on each role, so a role is only ever assessed once (the
pipeline dedups, so it appears as "pending" exactly once). Use --all to re-list
everything for a forced re-assessment after the resume/skills change.

Stdlib only. Python 3.11+.
"""
import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline import score, make_rationale  # recompute matchPercent once fit is known

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
JOBS_PATH = DATA / "jobs.json"

DEFAULT_MAX_DESC = 4000  # cap JD text handed to the subagent (plenty for requirements)


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


def list_pending(include_all=False, limit=None, max_desc=DEFAULT_MAX_DESC):
    jobs = load_jobs()
    out = []
    for r in jobs.get("roles", []):
        if not include_all and r.get("skillMatch"):
            continue
        desc = (r.get("fullDescription") or r.get("description") or "")
        if max_desc and len(desc) > max_desc:
            desc = desc[:max_desc] + " …[truncated]"
        out.append({
            "id": r.get("id"),
            "company": r.get("company"),
            "title": r.get("title"),
            "location": r.get("location"),
            "description": desc,
        })
        if limit and len(out) >= limit:
            break
    return out


def apply_assessments(path, model="sonnet"):
    with open(path) as f:
        payload = json.load(f)

    # Accept {id: {...}} or [{id, ...}, ...]
    if isinstance(payload, dict) and "assessments" in payload:
        payload = payload["assessments"]
    if isinstance(payload, list):
        by_id = {a["id"]: a for a in payload if a.get("id")}
    elif isinstance(payload, dict):
        by_id = payload
    else:
        raise ValueError("apply file must be a list or an object")

    jobs = load_jobs()
    profile = _load_profile()
    today = datetime.date.today().isoformat()
    applied, unknown = 0, []
    index = {r.get("id"): r for r in jobs.get("roles", [])}
    for rid, a in by_id.items():
        role = index.get(rid)
        if not role:
            unknown.append(rid)
            continue
        role["skillMatch"] = {
            "matched": list(a.get("matched", [])),
            "gaps": list(a.get("gaps", [])),
            "rationale": a.get("rationale", ""),
            "assessedBy": a.get("assessedBy", model),
            "assessedAt": a.get("assessedAt", today),
        }
        # The fit now feeds matchPercent, so rescore the role against the fresh assessment.
        pct, is_priority = score(role, profile)
        role["matchPercent"] = pct
        role["isPriorityDomain"] = is_priority
        role["rationale"] = make_rationale(role)
        applied += 1

    atomic_write_json(JOBS_PATH, jobs)
    return applied, unknown


def _load_profile():
    try:
        with open(DATA / "profile.json") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    ap = argparse.ArgumentParser(description="Skill-match I/O helper (LLM assessment, Option B)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list-pending", action="store_true", help="print roles needing assessment (JSON)")
    g.add_argument("--apply", metavar="FILE", help="merge an assessments JSON file into jobs.json")
    g.add_argument("--stats", action="store_true", help="print assessed/pending counts")
    ap.add_argument("--all", action="store_true", help="with --list-pending: list ALL roles (force re-assessment)")
    ap.add_argument("--limit", type=int, default=None, help="with --list-pending: cap how many roles to emit")
    ap.add_argument("--max-desc-chars", type=int, default=DEFAULT_MAX_DESC, help="truncate each description")
    ap.add_argument("--model", default="sonnet", help="model label stamped on applied assessments")
    args = ap.parse_args()

    if args.stats:
        jobs = load_jobs()
        roles = jobs.get("roles", [])
        assessed = sum(1 for r in roles if r.get("skillMatch"))
        print(f"total={len(roles)} assessed={assessed} pending={len(roles) - assessed}")
        return 0

    if args.list_pending:
        rows = list_pending(include_all=args.all, limit=args.limit, max_desc=args.max_desc_chars)
        json.dump(rows, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    if args.apply:
        applied, unknown = apply_assessments(args.apply, model=args.model)
        print(f"Applied {applied} assessments to data/jobs.json.")
        if unknown:
            print(f"Skipped {len(unknown)} unknown role id(s): {', '.join(unknown[:10])}"
                  + (" …" if len(unknown) > 10 else ""), file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
