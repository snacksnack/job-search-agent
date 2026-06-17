# Search Execution

How to run each search depends on its `platform` value in `data/search.json`. Lead with the reliable Tier 1 (official ATS APIs) for the watchlist sweep and for enriching every discovered posting; use the Tier 2 discovery sources to find roles by title across companies.

## ATS API fetch (Tier 1 — reliable, no browser)

The public job-board APIs for Greenhouse, Lever, and Ashby return clean JSON (title, location, full description, and — for Ashby/Lever — structured salary) with no authentication. Use plain HTTP GET via Bash/Python (`curl` or `requests`), NOT the browser. Templates live in `search.json.atsApi`:

- Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`
- Lever: `https://api.lever.co/v0/postings/{slug}?mode=json`
- Ashby: `https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true`

**Two uses:**

1. **Watchlist sweep** — for each company in `search.json.watchlist` (each entry: `{ "company", "ats", "slug" }`), fetch its board, then filter the returned roles by title against `{targetTitles}` + `{matching}`, by salary against the salary rule, and by the location rule. This is the dependable backbone — run it first, every run.

2. **Enrichment** — when a discovery source surfaces a posting whose URL is on `boards.greenhouse.io` / `job-boards.greenhouse.io` (slug after `/boards/` or in the subdomain path), `jobs.lever.co/{slug}/...`, or `jobs.ashbyhq.com/{slug}/...`, parse out the provider + slug, fetch the company board, find the matching role by its ID/title, and use that canonical record (full JD, salary, apply URL) instead of scraped text.

**Resolving slugs:** the slug is the company identifier in the job-board URL (e.g. `jobs.lever.co/figma` → slug `figma`; `jobs.ashbyhq.com/openai/...` → slug `openai`; `boards.greenhouse.io/stripe` → slug `stripe`). When the self-expanding step finds a strong role, add `{ "company", "ats", "slug" }` to `search.json.watchlist`.

Not every employer uses these three (Workday, iCIMS, and bespoke sites have no clean API) — for those, fall back to whatever the discovery source captured and note the limitation.

## Platform execution rules

**linkedin**: Navigate to `url`. For preference-based searches (no keywords), click "Show all" and set Date Posted. For keyword searches, apply all filters from the `filters` object to LinkedIn's UI (keywords, salary, experience level, remote, date). Use the broad-survey sidebar approach: scroll through results calling `get_page_text` at each position to inventory roles, then apply skip rules, then click into relevant roles up to `resultLimit`. Use `get_page_text` to read each JD. Extract `currentJobId` from the URL to build the permalink.

**google**: Use the WebSearch tool. If `queryTemplate` is set, use it directly. Otherwise auto-build the query:
1. Build site clause: `site:X OR site:Y` from `targetSites`.
2. Build keyword clause: `"keyword1" OR "keyword2"` from `filters.keywords`.
3. Build exclude clause: `-intitle:"term"` from `filters.excludeKeywords`.
4. Build experience clause: `intitle:"Director" OR intitle:"Head"` from `filters.experienceLevel` (if present).
5. Add `"remote"` if `filters.remote` is true.
6. Combine all clauses into the final query.

Then navigate directly to each result URL to read the full JD via `get_page_text`. Respect `resultLimit`. For Workday (myworkdayjobs.com) results: extract from search snippets only — never use browser navigation.

**hiringCafe** (`method: api-or-browser`): hiring.cafe is the best cross-company *discovery* source. Prefer its internal search endpoint when it works — `POST https://hiring.cafe/api/search-jobs` with a JSON body carrying the keyword/location/remote/salary/date filters — fetched via Bash/Python, no browser. It is unofficial and undocumented, so if it errors or changes shape, fall back to browser navigation of `url` and apply filters through the site UI. Either way, hiring.cafe links to the original ATS posting, so follow through to capture the canonical URL and enrich via the ATS API (see "ATS API fetch").

**ats**: Navigate directly to `url` (a specific ATS board), or better, hit that board's ATS API if it's Greenhouse/Lever/Ashby.

**custom — Wellfound**: Startup roles with salary + equity. Browser-based (no official API; anti-bot is aggressive). Navigate to `url`, apply keyword/remote/salary filters via the UI, browse up to `resultLimit`, click into roles for the JD, and follow through to the company's ATS posting where one exists to enrich + capture the canonical URL. Best-effort — if blocked, skip gracefully and note it in the log.

**custom — Built In NYC**: NYC-metro tech/startup roles (relevant because of the NYC-metro side of the location rule). Browser-based. Navigate to `url`, filter by keyword and the NYC location, browse up to `resultLimit`, click into roles, and follow through to the underlying ATS posting to enrich. Because this source is geographically scoped, treat its results as satisfying the NYC-metro branch of the location rule.

**indeed / custom (other)**: Navigate to `url`, apply filters as available through the site's UI, browse and click into results up to `resultLimit`.

## Process optimization — tool selection by source

These rules were derived from real friction points. Follow them to avoid wasting time on known-broken paths.

1. **Workday sites (myworkdayjobs.com)**: NEVER use browser navigation — the browser extension cannot access these domains. Use WebSearch to find Workday-hosted roles and extract what you can from search snippets. If a Workday role looks promising from the snippet, include it with whatever details are available and note "Workday — limited JD access" in the rationale.
2. **LinkedIn job description reading**: Use `get_page_text` to read job descriptions instead of screenshot+scroll loops. After clicking into a role, call `get_page_text` once to capture the full JD text.
3. **LinkedIn sidebar scanning (broad survey first, then filter)**: Survey a large number of roles before applying filters. At each scroll position, use `get_page_text` to capture all visible role titles and metadata in the sidebar. Continue scrolling and capturing until you've built a comprehensive inventory, THEN apply title/skip filters to decide which roles to click into. This avoids missing good roles further down the list.
4. **Google/WebSearch method**: Use the WebSearch tool as the primary discovery method instead of navigating Google in the browser. Build or use the query from `data/search.json`, then navigate directly to the resulting ATS URLs to read full JDs via the browser. This bypasses Google's anti-bot friction and is significantly faster.
5. **Aggregator sites (hiring.cafe, etc.)**: Use browser navigation. After finding a role, always follow through to the original ATS posting to capture the canonical URL — do not use the aggregator's URL as the job URL.

## CRITICAL — Capturing job URLs

Every role in the report MUST have a valid, clickable URL that links directly to the job posting. Never use placeholder, generic, or fabricated URLs.

- **LinkedIn roles**: When you click a job in the sidebar, the browser URL updates to include `currentJobId=NNNNNNNNN`. Extract that numeric ID and construct the permalink as `https://www.linkedin.com/jobs/view/NNNNNNNNN/`. You MUST click into every role you plan to include — do NOT capture roles only from sidebar text.
- **ATS board roles (Greenhouse, Lever, Ashby, Workable, etc.)**: Use the actual URL from the browser after navigating to the job posting page.
- **Aggregator roles (hiring.cafe, etc.)**: Follow through to the original ATS posting and use THAT URL, not the aggregator URL.

**Verification**: Before writing the final JSON, review every URL in your collected data. Each one must be a real URL you visited this session, contain a numeric job ID for LinkedIn roles, and NOT be a search-results URL or placeholder. If you cannot confirm a valid URL for a role, either click into it or exclude it entirely.

## Capturing outreach context

When reading each JD, extract details useful for personalized outreach. For every included role, populate `outreachContext`:
- `teamMission` — what the team owns or focuses on; its purpose within the company.
- `whyRoleExists` — why the role was created (clues: "newly created role," "growing the team," "backfill," etc.).
- `notableDetails` — 1–2 standout details worth referencing in outreach.

If a detail isn't available from the JD, use "Not specified". Do NOT fabricate.

## Capturing the full job description

For every included role, store the complete JD text in `fullDescription`. Strip application form fields, navigation chrome, and boilerplate legal/EEO text. Preserve the original wording and structure.
