# Output Schemas

## Output — direct write to data/jobs.json

Write new role entries directly into `data/jobs.json` in the workspace folder chosen during setup. Do NOT create separate daily files.

Schema version 2 structure:

```json
{
  "schemaVersion": 2,
  "roles": [ { ... }, { ... } ]
}
```

Role object schema:

```json
{
  "id": "temporal-sr-tpm-platform",
  "company": "Temporal Technologies",
  "title": "Senior Technical Program Manager, Platform",
  "source": "googleAtsBoards",
  "appearedInSources": ["googleAtsBoards", "hiringCafe"],
  "location": "Remote US",
  "remoteStatus": "remote",
  "remoteNotes": "Remote-first, US-based; occasional travel to SF for onsites",
  "matchPercent": 88,
  "salaryMin": 180000,
  "salaryMax": 230000,
  "salaryCurrency": "USD",
  "url": "https://jobs.ashbyhq.com/temporal/e20c78e7-...",
  "rationale": "Durable-execution platform; role drives cross-team delivery for the core platform org — strong fit for the candidate's TPM + backend/infra background and migration experience.",
  "tags": ["Platform", "Infrastructure", "Developer Tools", "Cross-team Delivery"],
  "isPriorityDomain": true,
  "postedDate": "2026-06-07",
  "foundDate": "2026-06-08",
  "experienceRequired": "8+ years",
  "roleType": "IC",
  "domain": "Developer Infrastructure / Platform",
  "outreachContext": {
    "teamMission": "Coordinates delivery across the platform org that owns Temporal's durable-execution engine and cloud offering.",
    "whyRoleExists": "Newly created role to scale program management as the platform team grows.",
    "notableDetails": "Heavy cross-functional coordination between SDK, cloud, and infra teams; remote-first culture."
  },
  "fullDescription": "The complete job description text as extracted from the posting page..."
}
```

Field definitions:
- `remoteStatus` options: `remote`, `remote-with-travel`, `hybrid-optional`.
- `roleType` options: `IC`, `player-coach`, `people-manager`.
- `isPriorityDomain`: true when the role falls in one of the profile's `priorityDomains`.
- `source`: the `source` value from the matching entry in `data/search.json`.

**Deduplication**: Before adding a role, check if a role with the same URL already exists. If so, skip it entirely (but update `appearedInSources` if found via a new search).

**Write process**: Use Python via Bash to safely read, merge, and write `data/jobs.json`. Include schema-migration logic from v1 to v2 if an older file is encountered.

## Search log — write to data/search-log.json

After writing to `data/jobs.json`, append a new run entry to `data/search-log.json`. Read the existing file first, then append to the `runs` array. If the file doesn't exist, create it with `schemaVersion` 1.

**CRITICAL — schema compliance**: Before writing a new entry, READ the last existing entry in `data/search-log.json` and match its field names exactly. Use EXACTLY the field names below. Do NOT use alternatives like "found" instead of "jobsFound", "id" instead of "searchId", "reviewed" instead of "jobsReviewed", "qualified" instead of "jobsQualified", "added" instead of "notes".

Each run entry MUST have ALL of these top-level keys:
- `date` (string) — "YYYY-MM-DD"
- `totalNewRolesAdded` (number) — new roles appended to jobs.json
- `totalDuplicatesMerged` (number) — existing roles whose `appearedInSources` was updated
- `totalExpiredListings` (number) — URLs that returned 404 or were confirmed closed
- `searches` (array) — one object per search executed
- `skipReasons` (object) — counts by category
- `topRoles` (array) — highest-scoring new roles added this run

`searches` array — one entry per search, using these exact fields:
- `searchId` (string) — the `source` value from the matching entry in `data/search.json` (NOT the `id` field)
- `name` (string) — human-readable label from `data/search.json`
- `jobsFound` (number) — total roles visible/surfaced (sidebar count, search-results count)
- `jobsReviewed` (number) — roles actually clicked into and JD read
- `jobsQualified` (number) — roles that passed all filters and were added (or duplicates that updated sources)
- `notes` (string) — optional notes about yield, issues, or skipped roles

`skipReasons` object — all keys required, use 0 if none:
- `expired` (number) — listings that returned 404 or were confirmed closed
- `duplicate` (number) — roles already in jobs.json (matched by URL)
- `salaryTooLow` (number) — below salary threshold
- `locationHybrid` (number) — hybrid/on-site only, not remote-eligible
- `titleMismatch` (number) — title doesn't match target roles (engineering, marketing, design, etc.)
- `domainMismatch` (number) — domain-specific requirements the candidate can't meet
- `overlapWithPriorSearch` (number) — roles already seen in an earlier search this run or already in state.json (applied/hidden)

`topRoles` array — each entry uses these exact fields:
- `company` (string)
- `title` (string)
- `matchPercent` (number)
- `salary` (string) — e.g. "$160K–$210K"

Complete example of a valid run entry:

```json
{
  "date": "2026-05-28",
  "totalNewRolesAdded": 6,
  "totalDuplicatesMerged": 2,
  "totalExpiredListings": 3,
  "searches": [
    {
      "searchId": "linkedinPreferences",
      "name": "LinkedIn Preference-Based Jobs",
      "jobsFound": 17,
      "jobsReviewed": 7,
      "jobsQualified": 6,
      "notes": "25 sidebar roles surveyed. 15+ skipped via state.json cross-ref."
    }
  ],
  "skipReasons": {
    "expired": 3,
    "duplicate": 2,
    "salaryTooLow": 0,
    "locationHybrid": 0,
    "titleMismatch": 5,
    "domainMismatch": 0,
    "overlapWithPriorSearch": 12
  },
  "topRoles": [
    { "company": "Company Name", "title": "Role Title", "matchPercent": 89, "salary": "$160K–$210K" }
  ]
}
```

Use Python via Bash to safely read, append, and write `data/search-log.json`.

## Final summary

After writing to both `data/jobs.json` and `data/search-log.json`, output a final summary that includes:
- Total number of new roles added today.
- Count of jobs found / reviewed / qualified for each search.
- Count of roles skipped (with reason breakdown).
- Top 5 highest-scoring new roles with company, title, matchPercent, and salary range.
- A "Skipped Jobs" detail section with bulleted lists for each skip category:
  - **Salary Too Low**: company, title, salary range.
  - **Title Mismatch**: company, title, reason (e.g. "people-manager Director role, not IC TPM" or "recruiter aggregator posting").
  - **Domain Mismatch**: company, title, domain requirement that disqualified it.
  - **Location**: company, title, the disqualifying arrangement (hybrid/onsite outside the NYC metro).

## Inbox finds — write to data/inbox/

The LinkedIn discovery step (Claude in Chrome) does not score or filter. It only captures raw postings and drops them into `data/inbox/linkedin-<date>.json` for `scripts/pipeline.py` to ingest. The file is a JSON array of raw postings; only `title` and `url` are required, the rest are best-effort:

```json
[
  {
    "title": "Senior Technical Program Manager",
    "company": "Acme",
    "url": "https://www.linkedin.com/jobs/view/4012345678",
    "location": "Remote, US",
    "source": "linkedinSaved",
    "description": "optional snippet or full JD text if captured",
    "postedDate": "2026-06-09"
  }
]
```

The pipeline classifies the `url` into `sourceUrl` vs `atsUrl` by domain, and when a posting's URL is on Greenhouse/Lever/Ashby it fetches the canonical record (full JD, salary, apply URL) from that board's API automatically. So if you only have a LinkedIn URL, just record it — enrichment happens downstream. Inbox files are transient and git-ignored; the pipeline reads every `*.json` in the folder.

## Roles written by the pipeline — data/jobs.json

`scripts/pipeline.py` is the single writer of new roles. It deduplicates against existing `jobs.json` (by `url` and `id`) and against `state.json` (never resurfaces an applied/hidden role), applies every filter and the scoring formula from `scoring-and-filters.md`, and appends new role objects to `jobs.json.roles`. Each role carries both link fields: `sourceUrl` (human-readable listing) and `atsUrl` (direct apply link); whichever isn't known yet is left empty and shows as "pending" on the board. Do not hand-write roles into `jobs.json` from the chat — run the pipeline so the dedup/filter/score logic stays consistent.

## The board — local server (no Notion)

Local JSON is the source of truth; there is no Notion. The board is served by `scripts/serve.py`:

- Run `python3 scripts/serve.py` and open http://127.0.0.1:8000.
- It renders live from `jobs.json` + `state.json` on every request (via `scripts/render.py`).
- The **Mark Applied / Hide / Restore** buttons POST to `/api/decision`, which writes the decision straight into `data/state.json` (atomic write). This is the ONLY writer of `state.json` — the daily run reads it but never writes it.
- **Draft Cover Letter** POSTs to `/api/queue-cover-letter`, appending the role to `data/queue/cover-letters.json` (deduped while pending). Drain that queue on demand with the tailored-materials skill.
- **Reset state** clears all decisions; **Show applied** / **Show hidden** and the search box filter client-side.

`scripts/render.py` can also be run directly to write a static `data/board.html` snapshot (e.g. for a quick look without the server), but the live, interactive board is the server. `board.html` is git-ignored (generated).

Requirements:
- Single file, no external runtime dependencies (inline CSS; a CDN script tag is fine but not required).
- A sortable/scannable card or table layout grouped or sorted by `matchPercent` descending, with priority-domain roles surfaced first.
- Each role shows: title, company, match %, salary, location, remote status, source, tags, posted date, and a working link to `url`.
- Reflect the user's decisions from `state.json`: visually de-emphasize or hide roles marked `hidden`; badge roles by `status` (new / applied / interviewing / etc.).
- Header shows the run date and counts (new today, total active, top match %).
- Never invent data — render only what's in `jobs.json`/`state.json`.

## Morning briefing

After all writes, output the morning briefing directly in the chat (this is the primary daily deliverable). Keep it tight and scannable — quality over volume. On a quiet day with few or zero new roles, say so plainly; never pad with stale listings.

Structure:

1. **Headline** — one line: date + how many new roles today + the single best match (company, title, match %).
2. **Top new roles** (up to {topN}, best first) — for each: company, title, match %, salary range, location/remote, and a one-line "why it fits." Link the `url`.
3. **Company briefs** — for roles that got a brief this run, a one-line pointer to `data/briefs/{id}.md`.
4. **Watchlist candidates** — any similar companies the self-expanding step surfaced for the user to approve adding (do not auto-add).
5. **Self-tuning proposals** — any matching adjustments proposed this run (with rationale), each requiring the user's explicit yes/no. Never applied silently.
6. **Run stats** — compact line: searches run, found/reviewed/qualified totals, skip breakdown, expired listings.
7. **Pointers** — tell the user to start the local board (`python3 scripts/serve.py` → http://127.0.0.1:8000) to review, mark applied, hide, or queue cover letters. Optionally also link a fresh `data/board.html` static snapshot via the file-sharing tool.

Tone: concise, friendly, decision-oriented. The user should be able to read it in under a minute and know exactly what's worth acting on today.