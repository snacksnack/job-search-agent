# Job Scout — Personalized Job Search Agent

A Claude plugin that runs a personalized daily job search for **Technical Program Manager, Solutions Engineer, and Forward Deployed Engineer** roles (configurable to any target titles), scores each posting against your resume and preferences, and serves a local, interactive job board. **Local JSON files are the source of truth** and the deterministic fetch/dedup/filter/score work runs in plain Python (no LLM tokens); Claude is used only for the parts that need judgment.

All matching is driven by `data/profile.json` and `data/search.json` — copy the bundled `data/profile.example.json` / `data/search.example.json` templates (or run the `job-search-setup` skill) to make it yours. Nothing is hardcoded in the skills.

Adapted from an open-source job-search plugin, retuned end-to-end for a custom set of target roles, salary, location rule, and dealbreakers.

## Architecture

The deterministic core is plain Python in `scripts/` (standard library only — no pip installs, Python 3.11+):

- **`scripts/pipeline.py`** — sweeps the Greenhouse/Lever/Ashby/Workable/SmartRecruiters public APIs for every watchlist company, ingests raw LinkedIn finds from `data/inbox/*.json`, enriches ATS-hosted postings, then deduplicates, filters, scores, and writes `data/jobs.json`. Run: `python3 scripts/pipeline.py` (`--dry-run` to preview).
- **`scripts/serve.py`** — the local board server. Run `python3 scripts/serve.py`, open http://127.0.0.1:8000. Renders live from `jobs.json` + `state.json`; each card has a **status dropdown** (New / Applied / Interviewing / Offer / Rejected / Hidden) that writes the decision straight to `state.json`, and a **Draft Cover Letter** button that queues the role in `data/queue/cover-letters.json`.
- **`scripts/render.py`** — shared HTML renderer (also writes a static `data/board.html` if run directly). Markup/styles/client JS live in `scripts/assets/` (`board.html` shell, `board.css`, `board.js`); `render.py` is pure logic that inlines them into one self-contained page.
- **`scripts/skill_match.py`** — I/O helper for the skill-match feature: `--list-pending` (roles needing an assessment), `--apply` (merge assessments into `jobs.json`), `--stats`. It does only the deterministic plumbing; the actual matching is LLM judgment (see below).
- **`scripts/web_enrich.py`** — I/O helper for browser enrichment of source-only (LinkedIn / hiring.cafe) roles that have no ATS API behind them: `--list-pending` / `--apply` / `--stats`. The browsing/extraction is done by Claude in Chrome (see below); the script only lists and merges.

Claude (via Cowork) handles only the judgment work: LinkedIn discovery through Claude in Chrome (writing raw finds to `data/inbox/`), the skill-match assessment, company briefs, self-tuning proposals, and drafting tailored materials on demand.

### Skill match (resume ↔ job description)

Each board card shows how your resume lines up with the role: green chips for skills/experience the JD asks for that you have, amber chips for skills the JD wants that aren't in your profile ("gaps"), plus a one-line rationale. Your canonical skill list lives in `profile.json` under `candidate.skills`.

This is computed by an **LLM, not keyword matching**, so it understands synonyms ("Postgres" ≈ "PostgreSQL") and transferable experience. To keep it cheap, each role is assessed **once, when first discovered**, and the result is cached on the role in `jobs.json` — later runs never re-assess it. The assessment runs as a **subagent pinned to the Sonnet model** during the Cowork-orchestrated daily run, so it uses your Claude subscription (no API key, no separate billing) and is independent of whichever model your Cowork session happens to be set to. Steady-state cost is therefore just the handful of new roles per day; the existing board is a one-time backfill. If you change your resume/skills, `python3 scripts/skill_match.py --list-pending --all` forces a re-assessment.

## What a daily run does

1. **LinkedIn discovery** (Claude in Chrome) captures raw postings into `data/inbox/linkedin-<date>.json`.
2. **The pipeline** sweeps the watchlist via the official Greenhouse/Lever/Ashby/Workable/SmartRecruiters APIs, ingests the inbox, enriches ATS postings, then **filters, scores, dedups** (against `jobs.json` and your decisions in `state.json`) and writes new roles to `jobs.json`.
3. **Skill-match assessment** — a Sonnet subagent assesses each newly-discovered role against your resume (matched skills + gaps), cached on the role so it's never recomputed.
4. **A morning briefing** summarizes the new top roles; you review and act on them in the local board.

With the agentic options on, it also expands the watchlist, writes company briefs for the top roles, and proposes (never silently applies) self-tuning adjustments to the matching rules.

## How matching is tuned (example configuration)

The values below come from the bundled example profile — they illustrate how the rules compose. Edit `data/profile.json` to set your own.

- **Target titles:** Technical Program Manager (Senior/Staff/Principal), Solutions Engineer (Senior), Forward Deployed Engineer (Senior); Platform/Infra/Backend Engineering only on a strong match. **Technical Project Manager** is a secondary title — it still appears but is scored lower (base 60 vs 95) so true Program Manager roles rank above it; plain non-technical "Project Manager" stays excluded.
- **Salary target:** $150K (a role qualifies if $150K falls *within* the posted range; only skipped when the whole range tops out below it).
- **Location rule (`remote-or-nyc-metro`):** include fully-remote **US** roles OR any NYC-metro role in any arrangement; exclude hybrid/onsite tied outside the NYC metro. The matcher catches NYC-metro variants — "New York", "New York City", "NYC", "New York, NY", and the boroughs (Manhattan, Brooklyn, Queens, the Bronx, Staten Island) — without false-matching upstate NY (Albany, Buffalo, etc.). It also enforces the US remote scope: a remote role tied to a foreign geography ("Remote - Netherlands", "Remote - UK", etc.) is excluded, while a role open to both US and abroad ("US-Remote, London") is kept.
- **Seniority:** Senior + Staff/Principal only.
- **Dealbreaker:** quota-carrying / commission-driven sales roles — but pre-sales SE/FDE roles where the quota is incidental are kept.
- **Priority domains:** platform/infrastructure, data/ML platforms, developer tooling & CI/CD, cloud/AWS (with martech, SaaS, observability, fintech/data as adjacent).

All of these live in `data/profile.json` — nothing is hardcoded in the skills.

## Skills

- **`job-search-setup`** — one-time (or re-run) configuration. Ingests the resume, collects preferences, writes `profile.json` + `search.json`.
- **`daily-job-search`** — the daily run (the core engine). Triggered manually ("run my job search") or on a schedule.
- **`tailored-materials`** — for a chosen role, generates a tailored resume variant, cover letter, and outreach drafts under `data/applications/{role-id}/`. **Never auto-sends.**
- **`interview-prep`** — for a role you're interviewing for, builds a prep pack (likely questions, STAR story bank from your real resume, questions to ask) under `data/interview-prep/{role-id}/`.

## Data files (`data/`)

All of these are **local and git-ignored** — they're your personal data and produced output. The repo ships only the generic `*.example.json` templates; copy them (or run `job-search-setup`) to create your own.

| File | Purpose | Written by | In git? |
| --- | --- | --- | --- |
| `profile.example.json` | Generic profile template | (shipped) | ✅ tracked |
| `search.example.json` | Generic search config + watchlist template | (shipped) | ✅ tracked |
| `profile.json` | Your candidate profile + all preferences | setup (read-only to daily search) | ignored |
| `search.json` | Your search config + watchlist + ATS API templates | setup; daily search appends to `watchlist` | ignored |
| `jobs.json` | Master list of discovered roles — **source of truth** | `scripts/pipeline.py` (roles); `scripts/skill_match.py` (the `skillMatch` block per role) | ignored |
| `state.json` | **Your** applied/hidden/status decisions — **source of truth** | `scripts/serve.py` (board buttons); the pipeline only reads it | ignored |
| `search-log.json` | Per-run audit log | `scripts/pipeline.py` (append) | ignored |
| `inbox/` | Raw LinkedIn finds awaiting ingest | Claude in Chrome | ignored |
| `queue/cover-letters.json` | Cover-letter requests from the board | `scripts/serve.py` | ignored |
| `board.html` | Optional static snapshot (live board is the server) | `scripts/render.py` | ignored |
| `briefs/` | Company briefs for top roles | daily search | ignored |
| `resumes/` | Your resume(s) | setup | ignored |
| `applications/` | Staged tailored materials | tailored-materials | ignored |
| `interview-prep/` | Interview prep packs | interview-prep | ignored |

Tracked in git: the scripts, the skills, and the generic `*.example.json` templates. **All personal data and produced output is git-ignored** (see `.gitignore`) — your profile, resume, discovered roles, decisions, and generated materials never get committed.

## Source reliability

- **Tier 1 — official ATS APIs** (Greenhouse/Lever/Ashby/Workable/SmartRecruiters): the dependable backbone for the watchlist sweep and enrichment.
- **Tier 2 — discovery sources** (hiring.cafe, LinkedIn, Wellfound, Built In NYC): browser/unofficial; searchable by title across companies. Flakier — captured best-effort, then enriched via Tier 1 where possible. A flaky source never blocks the run.

## Running it on your Mac

No dependencies to install — it's standard-library Python only (3.11+; developed on 3.14). From the repo root:

```bash
# 1. The whole pipeline in one command. Hits the live ATS APIs
#    (Greenhouse/Lever/Ashby/Workable/SmartRecruiters) for every watchlist
#    company, writes new roles to data/jobs.json, then immediately runs the
#    re-enrich pass to fill full job descriptions (notably SmartRecruiters,
#    whose sweep is list-only) and rescore. Nothing else to run.
python3 scripts/pipeline.py

# Preview first if you like — same two stages, writes nothing.
python3 scripts/pipeline.py --dry-run

# 2. Open the board — renders live from jobs.json + state.json.
#    Leave it running while you triage; the status dropdown and
#    Draft Cover Letter persist to data/state.json + data/queue/ immediately.
python3 scripts/serve.py
#    then open http://127.0.0.1:8000
```

**One command does everything.** A bare `python3 scripts/pipeline.py` runs both stages back to back: the **discovery sweep** (find + filter + score + write new roles) and then the **re-enrich pass** (refetch full JDs for any role with an enrichable ATS `atsUrl`, rescore, and clear stale `skillMatch` so the next Cowork run re-assesses on the fuller text). Because the sweep persists new roles before the re-enrich pass runs, roles discovered this run — including SmartRecruiters roles, whose sweep is intentionally list-only — get their full descriptions filled in the *same* invocation. Re-enrich only touches Greenhouse/Lever/Ashby/Workable/SmartRecruiters URLs; LinkedIn/source-only roles can't be enriched this way.

Flags, only if you want to run one stage on its own:

```bash
python3 scripts/pipeline.py --sweep-only   # discovery only, skip re-enrich
python3 scripts/pipeline.py --reenrich     # re-enrich existing roles only, no discovery
python3 scripts/pipeline.py --resolve-ats  # attach ATS apply links to source-only roles
python3 scripts/pipeline.py --dry-run      # preview both stages, write nothing
```

**Attaching apply links (`--resolve-ats`).** Roles discovered via LinkedIn/hiring.cafe arrive with only a source link, so the board shows "Apply (ATS) — pending." This pass maps each such role's company to its ATS (e.g. Cohere → Ashby `cohere`), finds the matching posting by a confident title match, and attaches the real `atsUrl` (backfilling salary/location and swapping in the canonical JD when it's fuller). It's conservative — a role only gets a link on a high-confidence title match, so no wrong apply links — and idempotent: resolved and unresolvable roles are flagged (`atsResolveStatus`) so re-runs skip them. Companies on Workday/iCIMS/custom boards won't resolve and stay "pending." Use `--no-guess` to only use known watchlist/existing mappings (no slug guessing) and `--limit N` to cap companies per run.

`--max-age-days N` controls how far back postings can be (default 1 = last 24h). Host/port for the board are overridable with `BOARD_HOST` / `BOARD_PORT` env vars. (Note: under `--dry-run` the sweep writes nothing, so the re-enrich preview reflects roles already in `jobs.json`, not the just-previewed ones — a real run composes the two stages fully.)

**Browser enrichment (LinkedIn / hiring.cafe roles).** Source-only roles with no ATS API behind them get their full JD read from the posting page by Claude in Chrome — an on-demand pass, not part of the daily run. Ask Claude (in Cowork) to "enrich my LinkedIn roles." Under the hood it runs `scripts/web_enrich.py --list-pending` (prioritized by match, chunk with `--limit`), opens each posting in Chrome to extract the description/salary/location, then `scripts/web_enrich.py --apply` merges the results, rescores, and clears the cached `skillMatch` so they re-assess. It's best-effort: you need to be signed in to LinkedIn, and expired postings are skipped.

Other ways to run:

- **Via Claude:** ask "run my job search" — Claude does LinkedIn discovery in Chrome (dropping raw finds into `data/inbox/`), then invokes `pipeline.py`, then gives you a morning briefing.
- **Scheduled:** a daily run at **07:00 America/New_York** (configured in `profile.json.schedule`; set up via the schedule skill). Runs on the laptop.

**Fully hands-off (cron).** Because one command now does the whole pipeline, automating it is a single crontab line. To run it every morning at 07:00 and log the output, run `crontab -e` and add (replace the path with your repo location):

```cron
0 7 * * *  cd /path/to/job-search-agent && /usr/bin/python3 scripts/pipeline.py >> data/cron.log 2>&1
```

That's the entire daily job — sweep and re-enrich together, appended to `data/cron.log`. Your Mac must be awake and online at the scheduled time (use `caffeinate` or a `launchd` agent if you want it to fire on wake instead). The pipeline only reaches the ATS APIs from a machine with open network access; it can't run from inside the Cowork sandbox.

> **Note:** the pipeline can only reach the ATS APIs from a machine with open network access (i.e. your Mac) — they're not reachable from inside the Cowork sandbox, so run the commands above locally. The deterministic pipeline and board are also designed to lift cleanly to AWS later — `pipeline.py` → a scheduled Lambda, `serve.py`'s handlers → API Gateway + Lambda, and the JSON data → S3 — with no rewrite. For now everything is local.

## Tests

The deterministic core is covered by a stdlib `unittest` suite in `tests/` (no pip install, no network — ATS calls are mocked). From the repo root:

```bash
python3 -m unittest discover -s tests
```

It locks in the behavior of the title tiers (Program vs Project Manager), salary rule, NYC-metro + US-remote location logic, scoring/penalties, dedup, the full `run()` and `--reenrich` paths, and the `skill_match` / `web_enrich` I/O round-trips. The fixtures use a self-contained profile, so the tests don't break when `profile.json` is tuned. (Tests are plain `unittest.TestCase`, so `pytest` discovers them too if you prefer it.)

## Safety

- The agent **never** auto-sends outreach, messages, or applications — all materials are staged as drafts (`agentic.autoSend` is false).
- `state.json` is yours; the daily search never overwrites your decisions.
- Materials are tailored by emphasis and framing only — no fabricated experience, metrics, employers, or credentials.
