# CLAUDE.md — conventions for reviewers and AI sessions

One page, under 6,000 characters so the PR review agent reads it whole. The
full story, including the tuning rules, is in the README.

## What this is

A personal job-search agent. A deterministic Python pipeline sweeps public ATS
APIs, filters, scores and dedups roles into `data/jobs.json`; a local board
server renders them for triage. Claude does only the judgment work — LinkedIn
discovery through Claude in Chrome, the skill-match assessment, company briefs,
tailored materials — orchestrated through the skills in `skills/`.

## Layout

```
scripts/
  pipeline.py       the deterministic backbone: sweep, ingest, filter,
                    score, dedup, write (2,100 lines; no LLM, no browser)
  serve.py          the local board server on 127.0.0.1:8000
  render.py         pure HTML rendering; markup/CSS/JS in scripts/assets/
  skill_match.py    --list-pending / --apply / --stats  (I/O only)
  web_enrich.py     same shape, for source-only roles with no ATS API
  title_rescue.py   title-tier rescue rules
skills/    job-search-setup, daily-job-search, tailored-materials,
           interview-prep — the Claude-facing entry points
data/      jobs.json (source of truth), state.json (your decisions),
           profile.json, inbox/, queue/, logs/, applications/
ops/       launchd plist templates + cloudflared config for remote access
tests/     stdlib unittest, 20 files, offline (ATS calls mocked)
```

## Conventions (hold a change to these)

- **Standard library only.** `requirements.txt` is deliberately empty of
  third-party packages — the pipeline and server use `urllib`, `http.server`
  and `json` so the whole thing runs on a bare `python3` and stays portable.
  Adding a dependency is a real decision, not a convenience.
- **Deterministic Python decides; the model only judges.** Filtering, scoring,
  dedup and the location/salary/title rules are plain Python driven by
  `data/profile.json`. Nothing is hardcoded in the skills. If a number is
  wrong, the bug is in `pipeline.py`.
- **`state.json` is the user's.** The daily run never overwrites a decision.
- **Assessments are cached and never deleted.** A role is skill-matched once,
  when first discovered, and the result is cached on the role. A role whose JD
  changes is *flagged* for deliberate re-assessment and keeps its existing
  score until then — never silently recomputed, never dropped. This is what
  keeps steady-state cost to the handful of new roles per day.
- **Nothing is ever auto-sent.** Tailored resumes, cover letters and outreach
  are staged as drafts under `data/applications/{role-id}/`; `agentic.autoSend`
  is false. Self-tuning proposals are *proposed*, never silently applied.
- **A flaky source never blocks the run.** Tier 1 is the official ATS APIs
  (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) and is the dependable
  backbone; Tier 2 (LinkedIn, hiring.cafe, Wellfound, Built In NYC) is
  best-effort discovery, enriched through Tier 1 where possible.
- **Every rejection is explainable.** Counts alone cannot answer "why isn't
  *this* role on my board", so each rejected posting is appended to
  `data/logs/rejects-YYYY-MM-DD.jsonl` with both the `reason` bucket the
  breakdown counts and the `detail` it drops. Appended, not overwritten;
  newest 14 days kept; `--dry-run` writes nothing. A new rejection path must
  log its detail too.
- **`foundDate` comes from the system clock, never the payload** (RC1-311) —
  a posting's own date is not when you found it.
- **Personal data stays out of git.** Only the scripts, the skills and the
  `*.example.json` templates are tracked; profile, resume, discovered roles,
  decisions and generated materials are git-ignored. A change that would commit
  any of those is a defect.

## Testing

- `python3 -m unittest discover -s tests` from the repo root. No pip install,
  no network — ATS calls are mocked and the fixtures carry a self-contained
  profile, so tests do not break when `profile.json` is tuned.
- Tests are plain `unittest.TestCase`, so `pytest` discovers them too.
- They lock in the title tiers (Program vs Project Manager), the salary rule,
  the NYC-metro + US-remote location logic, scoring and penalties, dedup, the
  full `run()` and `--reenrich` paths, and the `skill_match` / `web_enrich` I/O
  round-trips. A change to any of those should move a test.
- **CI runs the suite on every push and PR** (`.github/workflows/ci.yml`,
  RC1-403) on Python 3.14, with no install step — the workflow must stay
  dependency-free for the same reason the repo is.

## Commands

```bash
python3 scripts/pipeline.py                # full run: sweep + re-enrich
python3 scripts/pipeline.py --dry-run      # preview, writes nothing
python3 scripts/pipeline.py --sweep-only   # discovery sweep only
python3 scripts/serve.py                   # the board, 127.0.0.1:8000
python3 scripts/skill_match.py --list-pending
python3 -m unittest discover -s tests
```

## Workflow

One branch per ticket, `rc1-NNN-slug`; never commit on `main`. Commit subject
`RC1-NNN: what changed`, short body, **no Co-Authored-By trailer**. Claude
opens the PR; Reid merges.
