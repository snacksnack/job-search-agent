# Scoring & Filters

Every person-specific list, threshold, and rule comes from `data/profile.json`. Do NOT hardcode any candidate's preferences here — read them from the profile. If a needed field is missing or empty, skip that rule rather than inventing one (and suggest the user re-run `job-search-setup`).

Profile fields used here:

- `preferences.salaryTarget` → **{salaryTarget}**
- `preferences.remotePolicy` + `preferences.locationRule` → **{locationRule}**
- `preferences.targetTitles` → **{targetTitles}**
- `preferences.seniorityLevels` → **{seniorityLevels}** (the levels to include)
- `matching.skipTitleRules` → categories/titles to skip without clicking
- `matching.alwaysIncludeTitles` → titles to always review even if they resemble a skip category
- `matching.secondaryIncludeTitles.titles` → adjacent titles to include but rank BELOW the primary targets (e.g. Technical Project Manager)
- `matching.skipEmployers` → employers to skip (recruiter aggregators)
- `matching.descriptionSkips` → background/description dealbreakers
- `matching.priorityDomains` → `domain_bonus` = 100
- `matching.adjacentDomains` → `domain_bonus` = 70
- `candidate.yearsExperience`, `candidate.managementExperience` → scoring penalties

## Title skip rules

Skip a role without clicking if its title matches any entry in `matching.skipTitleRules`. Each rule has a `category` (for logging under `titleMismatch`) and `titles` (the matching terms). If a title matches both a skip rule AND an entry in `matching.alwaysIncludeTitles`, ALWAYS include it — the always-include list wins. One exception outranks even the always-include list: `matching.leadershipOverrideTitles`, checked first of all. These are Manager-of-a-team phrasings ("Manager, Sales Engineering", "Solutions Engineering Manager") — people-leadership roles whose titles happen to contain an always-include substring like "Sales Engineer"; they are rejected as `titleMismatch: Seniority too high (people-leadership)`. When a title is ambiguous, click in and review; only skip when it's obvious from the title.

## Recruiter / aggregator postings

Skip any listing whose employer matches an entry in `matching.skipEmployers` (e.g. recruiter aggregators that hide the real employer and provide limited useful information).

## Never skip based on domain alone

Do NOT skip a role just because the company's industry or domain is unfamiliar. Domain mismatch only affects `matchPercent` (via `domain_bonus`). The only exception is if the JD lists specific domain experience as a firm, required qualification.

## Salary evaluation rule

A role is only marked "salary too low" if `{salaryTarget}` falls BELOW the bottom of the posted range. The correct test: if `{salaryTarget}` falls WITHIN the posted range (i.e., `salaryMin <= {salaryTarget} <= salaryMax`), the role qualifies on salary. Only skip when the entire range tops out below `{salaryTarget}`. Example: with target 160000, a range of $115K–$175K should NOT be skipped because 160000 is achievable within it; a range of $100K–$143K should be skipped because the max is below target.

## Location rule

Interpret `{remotePolicy}` together with `{locationRule}`. For the configured `remote-or-nyc-metro` policy, a role qualifies on location if EITHER:
- it is **fully remote** and open to US-based candidates (`locationRule.includeRemoteScope` = "US"); OR
- it is in the **NYC metro** (`locationRule.metroIncludeAnyArrangement`) in ANY arrangement — remote, hybrid, or onsite.

Exclude a role only when it is **hybrid or onsite and tied to a location outside the NYC metro** (`locationRule.excludeOnsiteOrHybridOutsideMetro` = true). Examples: "Remote (US)" → include; "Hybrid, Brooklyn NY" → include; "Hybrid, 3 days/week in Austin" → exclude; "Onsite San Francisco" → exclude; "Remote, US or Canada" → include. Log location-excluded roles under `locationHybrid`.

A location that names **only a nationwide scope** — "United States", "US", "USA", "Nationwide" — is an eligibility statement, not a worksite, and is included (RC1-586). LinkedIn renders exactly that when its Remote filter already established remoteness and there is no city to show, and Greenhouse boards use it for nationwide reqs. It carries no arrangement to exclude on, so only an explicit arrangement in `remoteNotes` ("hybrid, 3 days in Austin") can still rule one out. A country-qualified *city* is still judged on the city: "Milpitas, California, United States" is an onsite posting and excluded.

**The metro can be named in the title** (RC1-588) — "Forward Deployment Engineer- Greater NYC" at location "United States". A metro in the title is where the seat is, and it qualifies in any arrangement, exactly as a metro in the location field does. This is the mirror of the territory rule below.

**`remoteStatus` never outranks an explicit remote location** (RC1-588). `remoteStatus` is normally *derived* from the location string by the pipeline, so a stale derivation must not override the text it came from: a role stored as "United States (Remote)" with `remoteStatus: onsite` is remote. Narrow on purpose — the derived "onsite" is the only onsite signal a plain city posting carries, so it still counts there. Arrangement language in `remoteNotes` ("Hybrid, 3 days a week in Austin") rules a role out either way.

**Territory vs worksite** (RC1-587). A non-US region named in the **title** counts as a location signal only when the location field names no place at all — "", "Remote", "Remote (Remote)". "Senior Sales Engineer - UK" posted at "Remote" is a UK seat and is excluded as `locationNonUS`. But the same token in a title whose location names a real place is the book of accounts the seat covers, not where it sits: "Senior Solutions Engineer, Enterprise - LATAM" at "New York, NY" and "Sales Engineer, LATAM" at "Remote - USA" both stay. Any location that names a city, state or country — including an explicit US one — outranks the title.

Two things the non-US word list deliberately does and doesn't do: "england" never matches inside "New England", and Canadian **provinces** are listed (a posting often names only "Ontario - Remote") but no further Canadian cities are. `US_RE` recognizes country and region words, not US cities, so a dual-site posting would trip the non-US rule on its foreign city while its US city went unseen — "Remote (San Francisco or Calgary)" is a US-eligible role. The asymmetry already exists for Toronto and Vancouver; widening it would need `US_RE` to learn US cities.

**Title matching ignores hyphens and extra whitespace** (RC1-588). Matching is substring-based, so "Forward-Deployed Engineer" used to miss the "Forward Deployed Engineer" always-include and be rejected as `titleMismatch` — a primary target title losing to a hyphen. Hyphens and slashes read as spaces on **both** sides, in the filter and in scoring, so a configured phrase may carry its own hyphen ("Manager - Sales Engineering") and a rescued title doesn't then score at the no-signal floor.

## Seniority filtering

Include roles at the levels in `{seniorityLevels}` — read the list from the profile rather than assuming it; an unleveled title (plain "Technical Program Manager") counts as Mid and is included when Mid is listed. Skip roles clearly below (intern / junior / associate / entry / new-grad) and clearly above into people-leadership — Director / Head / VP / Chief via `matching.skipTitleRules`, and Manager-of-a-team titles ("Senior Manager, Sales Engineering") via `matching.leadershipOverrideTitles`, which beats even the always-include list. Note: many target titles contain the word "Manager" (e.g. "Technical Program Manager") — never skip those on the word "Manager" alone; the `alwaysIncludeTitles` list protects them, and the leadership overrides only match Manager-of-a-team phrasings (team name after "Manager," / "Manager of", or before "... Manager"), never the IC "<function> Manager" shape — and a "Manager, <team>" match is ignored when "Manager" is directly preceded by Program/Project/Product, so IC titles like "Program Manager, Professional Services" survive. Deliberately greedy on the Program Management family: titles like "Senior Manager, Technical Program Management" are NOT in the override list — the user prefers seeing any kind of Program Manager role and hiding misses manually over risking a filtered-out match. When seniority is unclear from the title, click in and judge from the JD's scope/requirements.

## Deduplication

If a role appears in multiple searches, include it once. Place it under the first source where it was found and note other sources in `appearedInSources`. Before adding any role, check if a role with the same URL already exists in `data/jobs.json`. If so, skip it entirely, but update `appearedInSources` if found via a new search.

## Priority sorting

Within each source group, sort roles in `matching.priorityDomains` first, then remaining roles by `matchPercent` descending.

## Match-percent scoring (0–100)

Score each role against the `candidate` object.

Formula: `matchPercent = (0.55 × title) + (0.35 × fit) + (0.10 × domain_bonus)`

`title` base: a title matching `targetTitles`/`alwaysIncludeTitles` = 95; a title matching `matching.secondaryIncludeTitles.titles` (e.g. **Technical Project Manager**) = 60 so it ranks clearly below true **Technical Program Manager** roles while still appearing; a generic technical-IC/role-type keyword = 80; otherwise 55. Senior/Staff/Principal add a small nudge; people-management language and "more years than the candidate has" subtract. Note: secondary titles are *included* but down-ranked — plain non-technical "Project Manager" is not in the secondary list and stays excluded via the title-skip pass.

`fit` (0–100) comes from the role's cached `skillMatch`: `100 × matched / (matched + gaps)`. Until a role has been skill-matched — or when an assessment found no concrete signal (0 matched / 0 gaps) — `fit` falls back to a neutral baseline of 70 so unassessed roles are neither rewarded nor unfairly penalized. This is what makes a 0-matched/many-gap role rank below a clean fit with the same title (it's recomputed by `score()` whenever an assessment is applied). Weights are deliberately tilted toward `fit` so a strong title alone can't carry a poor-fit role.

`domain_bonus`: 100 = role is in `matching.priorityDomains`; 70 = role is in `matching.adjacentDomains`; 40 = neutral; 10 = distant/niche.

Ranges: 80–100 excellent fit; 60–79 strong; 40–59 moderate; 20–39 weak; 0–19 poor.

Key rules (all relative to the candidate's own profile):
- Penalize roles requiring more years of experience than `candidate.yearsExperience`.
- Penalize roles requiring management of a team type the candidate hasn't managed (compare against `candidate.managementExperience`).
- IC and player-coach roles score higher than people-management roles, unless the candidate's profile indicates a preference for people management.
- Do NOT penalize a title merely for being a step down from the candidate's current seniority.
- Roles in `matching.priorityDomains` get the domain bonus.
- Domain mismatch lowers `domain_bonus` only — it is never a skip reason.

## Description-based skips

Skip a role if its description matches any dealbreaker in `matching.descriptionSkips`. The check re-runs whenever a fuller JD arrives (`--reenrich`, `web_enrich --apply`): a LinkedIn find lands title-only, so the first pass had almost nothing to judge, and a role that trips a dealbreaker on its canonical text is archived then — otherwise a dealbreaker is really just a function of which source found the req first (RC1-586). A role the user has decided on or saved is never evicted. Each entry describes a background/requirement the candidate wants to avoid. The configured dealbreaker is sales-quota tethering: skip roles where comp or the core day-to-day is tied to hitting individual sales quotas — BUT keep pre-sales Solutions/Forward Deployed Engineer roles where the quota is incidental, not central. Apply each dealbreaker as: skip unless every other aspect is a near-perfect fit. If `matching.descriptionSkips` is empty, apply no description-based skips.

## Self-tuning inputs (for the self-tuning step)

When `preferences.agentic.selfTuningMatching` is on, the daily run inspects `data/state.json` for revealed-preference signals and PROPOSES (never silently applies) edits to `profile.json.matching`:
- Consistently **hidden** roles sharing a domain, company stage, salary band, or sub-family → propose a new `descriptionSkips` entry, a `skipTitleRules` addition, or a `salaryTarget` bump.
- Consistently **applied/starred** roles sharing a domain → propose promoting that domain into `priorityDomains`.
- Record every proposal with timestamp + rationale in `data/tuning-log.json`, and present them in the morning briefing for the user to accept or decline. Apply only on explicit confirmation.

The signals above are all revealed *after* a role reaches the board. For the other direction — a filter that is too tight, so a role the user would have wanted never arrived — read `data/logs/rejects-YYYY-MM-DD.jsonl`. It records one line per rejected posting with its identity, the `reason` bucket, and the `detail` naming the exact rule that fired (e.g. `titleMismatch` / `Sales (non-technical)`). Use it to answer "why didn't role X show up?" directly, and to spot a `detail` that is rejecting far more than it should before proposing a `skipTitleRules` change.
