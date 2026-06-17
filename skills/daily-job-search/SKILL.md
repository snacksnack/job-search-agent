---
name: daily-job-search
description: Run the personalized daily job search for Technical Program Manager, Solutions Engineer, and Forward Deployed Engineer roles. Use when the user says "run my job search", "find new jobs", "check for jobs today", "do my daily job scan", or when the scheduled task triggers. Reads profile.json and search.json from the workspace folder, uses Claude in Chrome to discover roles on LinkedIn (dropping raw finds into data/inbox/), then runs the deterministic Python pipeline (scripts/pipeline.py) which sweeps the Greenhouse/Lever/Ashby public APIs, ingests the inbox, deduplicates, scores, and writes results to jobs.json. Local JSON files are the source of truth; the board is served locally by scripts/serve.py. Appends a run entry to search-log.json and produces a morning briefing. With agentic options on, it also expands the company watchlist, generates company briefs, and proposes self-tuning adjustments. Requires job-search-setup to have been run first.
---

# Daily Job Search

Perform the searches in `data/search.json`, enrich and score the results against `data/profile.json`, write new roles to `data/jobs.json`, log the run to `data/search-log.json`, and deliver a morning briefing. Only include roles posted within the last 24 hours.

## Architecture (local-first, deterministic core)

The deterministic, no-LLM work lives in plain Python so it costs no tokens:

- **`scripts/pipeline.py`** — sweeps the Greenhouse/Lever/Ashby public APIs for every company in `search.json.watchlist`, ingests raw LinkedIn finds from `data/inbox/*.json`, enriches ATS-hosted postings, then deduplicates, applies all filters, scores, and writes `data/jobs.json`. Run it with `python3 scripts/pipeline.py` (add `--dry-run` to preview).
- **`scripts/serve.py`** — the local board server (`python3 scripts/serve.py`, then open http://127.0.0.1:8000). Renders the board live from `jobs.json` + `state.json` and exposes a tiny API so the **Mark Applied / Hide / Restore** buttons write decisions straight to `state.json`, and **Draft Cover Letter** appends to `data/queue/cover-letters.json`.
- **`scripts/render.py`** — shared HTML renderer (imported by the server; also writes a static `data/board.html` snapshot when run directly).

**Local JSON files are the source of truth.** There is no Notion and no second store to reconcile. The LLM (this skill, via Cowork) is used only for the parts that need judgment: LinkedIn discovery through Claude in Chrome, company briefs, self-tuning proposals, and drafting tailored materials on demand.

Your role in a daily run: do the LinkedIn discovery step in Claude in Chrome and write the raw postings to `data/inbox/linkedin-<date>.json` (schema below), then invoke the pipeline, then surface the briefing. Let the Python pipeline do the fetching/dedup/filter/score — do not re-implement that work in the chat.

## First-run guard — read the profile before anything else

Every personal value comes from `data/profile.json`. Do this first:

1. Read `data/profile.json`. If missing, STOP and tell the user "I don't have your profile yet — let's run setup first," then invoke `job-search-setup`.
2. Read `data/search.json`. If missing, also send the user to setup.
3. Read `data/state.json` (your applied/hidden/priority decisions) and `data/jobs.json` (existing roles) so you can deduplicate and avoid re-surfacing things you've acted on.

Placeholders resolve from the profile: **{salaryTarget}** = `preferences.salaryTarget`; **{targetTitles}** = `preferences.targetTitles`; **{locationRule}** = `preferences.locationRule`; **{seniorityLevels}** = `preferences.seniorityLevels`; **{candidate}** = the `candidate` object; **{matching}** = the `matching` object; **{topN}** = `preferences.agentic.topN`; **{agentic}** = `preferences.agentic`.

## File locations

All data lives in the `data/` subdirectory of the workspace folder:

- `data/profile.json` — candidate profile + preferences (read only; never modify here)
- `data/search.json` — search configuration + watchlist + ATS API templates (read; the self-expanding step may append to `watchlist`)
- `data/jobs.json` — master job listings (read/write)
- `data/search-log.json` — daily run log (append)
- `data/state.json` — the user's applied/hidden/status decisions (READ ONLY here — written only by the board server `scripts/serve.py`; never overwrite from the daily run)
- `data/inbox/` — raw LinkedIn finds you drop for the pipeline to ingest (write)
- `data/queue/cover-letters.json` — cover-letter requests queued from the board (read; drained by tailored-materials)
- `data/briefs/` — generated company briefs (write)
- `data/board.html` — optional static snapshot; the live board is served by `scripts/serve.py`

## Pre-authorized actions — do NOT ask for confirmation

Execute the workflow autonomously. The user has authorized: running `scripts/pipeline.py` (which makes HTTP GET requests to the public ATS APIs boards-api.greenhouse.io, api.lever.co, api.ashbyhq.com); navigating to LinkedIn, hiring.cafe, Wellfound, Built In NYC, Google, and any job-board/ATS site via Claude in Chrome; clicking into postings to read full descriptions; accepting/dismissing cookie banners (most privacy-preserving option); writing to `data/inbox/`, `data/jobs.json`, `data/search-log.json`, `data/briefs/`, `data/board.html`; running `scripts/skill_match.py` and spawning a Sonnet subagent for skill-match assessment; appending discovered companies to `search.json`'s `watchlist`; and creating folders as needed. NEVER auto-send any outreach, message, or application — those are always staged for the user (`agentic.autoSend` is false). Do NOT write to `data/state.json` — that is the user's decision store, owned by the board server.

## Run order

1. **Read** `profile.json`, `search.json`, `state.json`, `jobs.json` (first-run guard above).
2. **LinkedIn discovery (Claude in Chrome).** For each enabled `linkedin`/discovery search in `search.json`, browse and capture raw postings, then write them to `data/inbox/linkedin-<date>.json` (schema in `references/output-schemas.md` → "Inbox finds"). Do not score or filter in the chat — that is the pipeline's job. See `references/search-execution.md`.
3. **Run the pipeline.** Invoke `python3 scripts/pipeline.py` via Bash. It performs the watchlist sweep (Greenhouse/Lever/Ashby APIs), ingests `data/inbox/*.json`, enriches ATS-hosted postings, deduplicates against `jobs.json` + `state.json`, applies all filters (title, employer, salary, location, description) and scoring per `references/scoring-and-filters.md`, then writes new roles to `data/jobs.json` and appends a run entry to `data/search-log.json`. Read its stdout summary for the counts.
4. **Skill-match assessment (Sonnet subagent).** This is the only LLM cost in the run, and it happens once per role (cached thereafter). See "Skill-match assessment" under Agentic steps. Skip if `skill_match.py --list-pending` returns nothing.
5. **Self-expanding discovery** (if `agentic.selfExpandingDiscovery`): see "Agentic steps" below. New companies are appended to `search.json.watchlist` so the pipeline monitors them directly on the next run.
6. **Company briefs** (if `agentic.companyBriefs`): generate briefs for the top {topN} new roles (see "Agentic steps").
7. **Self-tuning** (if `agentic.selfTuningMatching`): analyze `state.json` and propose matching adjustments (see "Agentic steps"). Propose — do not silently apply.
8. **Morning briefing.** Output the briefing (see `references/output-schemas.md` → "Morning briefing"). Point the user to the local board: `python3 scripts/serve.py` → http://127.0.0.1:8000.

The deterministic fetch/dedup/filter/score work (old steps 2–6, 8, 11) now lives entirely in `scripts/pipeline.py`. Don't replicate it in the chat — running the script is both cheaper and the canonical implementation.

## Search configuration — data/search.json (v2)

`search.json` is the source of truth for which searches run. Only run searches where `enabled` is true; process in array order. Each entry has `id`, `name`, `source`, `platform` (`google` / `hiringCafe` / `linkedin` / `custom` / `ats`), `url`, `method`, `resultLimit`, `targetSites` (google only), `queryTemplate` (optional), and `filters` (`keywords[]`, `excludeKeywords[]`, `salaryMin`, `experienceLevel[]`, `remote`, `datePosted`). Top-level `watchlist` lists companies for direct ATS monitoring; `atsApi` holds the per-provider URL templates. Full execution rules are in `references/search-execution.md`.

## Source reliability tiers

Lead with the reliable tier; treat the rest as best-effort and never let a flaky source block the run.

- **Tier 1 — official ATS APIs** (Greenhouse/Lever/Ashby): plain HTTP, no browser, clean salary + full JD. Used for the watchlist sweep and for enriching discovered postings. Most dependable.
- **Tier 2 — discovery sources** (hiring.cafe, LinkedIn, Wellfound, Built In NYC): browser-based or unofficial endpoints; searchable by title across companies. Flakier; capture what you can, then enrich via Tier 1 where possible.

## Agentic steps

### Self-expanding discovery
When a discovered role scores well (matchPercent >= 75) and its company isn't already in `watchlist`:
1. Resolve the company's ATS provider + slug from the posting URL and add it to `search.json.watchlist` (so future runs monitor it directly).
2. Sweep that company's full board via the ATS API and score any other matching roles.
3. Identify 1–3 *similar* companies (same space, competitors, or shared investors — use WebSearch sparingly) and note them as watchlist candidates in the briefing for the user to approve, rather than auto-adding.

### Skill-match assessment
Shows, per role on the board, how the candidate's resume skills/experience line up with what the JD asks for. **Done by an LLM once per role, then cached** on the role as `skillMatch` in `jobs.json` — never recomputed on later runs (the pipeline dedups, so a role is "pending" exactly once).

1. `python3 scripts/skill_match.py --list-pending` prints the roles with no `skillMatch` yet (id, company, title, location, trimmed description). If empty, skip this step.
2. Spawn a subagent **pinned to the Sonnet model** (`model: "sonnet"` on the Agent/Task call — do NOT rely on the session's selected model). Give it: `profile.candidate.skills` plus the resume summary, and the pending roles' descriptions. For many pending roles, batch them (~20–30 per subagent call) to amortize the resume context; the one-time backfill of a full board may take several batches.
3. The subagent returns, per role, `{"id", "matched": [...], "gaps": [...], "rationale": "..."}` where **matched** = skills/experience from the profile the JD asks for (allow sensible synonyms — "Postgres"≈"PostgreSQL" — and transferable experience), and **gaps** = skills the JD requests that aren't in the profile. Keep `rationale` to one sentence. Return strict JSON only.
4. Write the results to a temp file and merge with `python3 scripts/skill_match.py --apply <file> --model sonnet`. It stamps each with the model + date and writes `jobs.json` atomically.

To refresh after the resume/skills change, `--list-pending --all` re-lists everything for a forced re-assessment. Never put an LLM call inside `scripts/pipeline.py` — that stays deterministic and token-free.

Roles with thin descriptions can be upgraded first with `python3 scripts/pipeline.py --reenrich` (refetches full JDs for roles that have a Greenhouse/Lever/Ashby `atsUrl`, rescores, and clears their cached `skillMatch` so they re-assess). LinkedIn/source-only roles have no ATS url and can't be re-enriched this way — use browser enrichment (below) for those.

### Browser enrichment (source-only roles) — on demand, not part of the daily run
LinkedIn / hiring.cafe roles have no ATS API behind them, so their full JD must be read from the posting page via Claude in Chrome. This is an on-demand maintenance pass (e.g. a one-time backfill of the existing board), not a daily-run step. Work highest-value first and stop anytime.

1. `python3 scripts/web_enrich.py --list-pending --limit N [--source linkedin|hiringcafe]` prints the pending roles (source-only, thin description, with a link), sorted by matchPercent. Start with a small `--limit` (e.g. 10–20).
2. For each row, open its `url` in Claude in Chrome and read the posting. Requires the user to be signed in to LinkedIn in that browser. Extract the full job description text and, if shown, salary, location, and posted date. If the posting is expired/removed or behind a wall, skip it — do not invent content.
3. Assemble results as JSON: a list of `{"id", "fullDescription", "salaryMin"?, "salaryMax"?, "location"?, "postedDate"?}`. Write to a temp file and merge with `python3 scripts/web_enrich.py --apply <file>`. It rescores, flags the role `enrichedVia: "web"`, and clears any cached `skillMatch` so the role re-assesses.
4. Run the skill-match assessment step afterward so the freshly-enriched roles get matched on their full text.

Notes: this is browser/LLM work, so it costs tokens and is best-effort — LinkedIn may rate-limit, and older postings are often gone. Doing it in batches keeps it manageable. `scripts/web_enrich.py` does only the list/apply I/O; the browsing and extraction are done by Cowork via Claude in Chrome.

### Company briefs
For the top {topN} new roles by matchPercent, write `data/briefs/{role-id}.md`: company one-liner, stage/funding, recent news, product & who the team serves, tech stack if discoverable, and 2–3 talking points connecting the role to {candidate}'s background. Use WebSearch; never fabricate — mark unknowns "Not found". Keep each brief to ~1 page.

### Self-tuning matching
Read `state.json`. Look for patterns in what the user applied to vs. hid vs. starred (e.g., consistently hiding a domain, salary band, role family, or company stage). Draft concrete proposed edits to `profile.json.matching` (e.g., "add X to descriptionSkips", "raise salaryTarget", "demote domain Y"). Append each proposal with a timestamp and rationale to `data/tuning-log.json` and surface them in the briefing as suggestions. Only apply a change if the user confirms — never rewrite `profile.json` silently.

## Daily run behavior

Quality over quantity. On quiet days produce a short briefing with a few roles or zero — never pad with older listings. Only genuinely new postings from the past 24 hours.

## Reference files

- `references/search-execution.md` — per-platform execution, ATS API fetch, URL capture, outreach/JD capture.
- `references/scoring-and-filters.md` — skip rules, salary rule, location rule, match scoring, self-tuning inputs (these rules are implemented in `scripts/pipeline.py`; the doc is the spec of record).
- `references/output-schemas.md` — jobs.json schema (incl. the `skillMatch` block), inbox finds schema, the local pipeline/board model, search-log schema, morning briefing format.

Helper scripts: `scripts/pipeline.py` (deterministic ingest; `--reenrich` to refetch ATS JDs), `scripts/skill_match.py` (skill-match I/O: `--list-pending` / `--apply` / `--stats`), `scripts/web_enrich.py` (browser-enrichment I/O for source-only roles: `--list-pending` / `--apply` / `--stats`), `scripts/serve.py` (board server), `scripts/render.py` (board HTML).
