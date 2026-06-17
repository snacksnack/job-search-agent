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

Skip a role without clicking if its title matches any entry in `matching.skipTitleRules`. Each rule has a `category` (for logging under `titleMismatch`) and `titles` (the matching terms). If a title matches both a skip rule AND an entry in `matching.alwaysIncludeTitles`, ALWAYS include it — the always-include list wins. When a title is ambiguous, click in and review; only skip when it's obvious from the title.

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

## Seniority filtering

Include roles at the levels in `{seniorityLevels}` (Senior, Staff, Principal). Skip roles clearly below (intern / junior / associate / entry / new-grad / mid) and clearly above into people-leadership (Director / Head / VP / Chief) — these are also encoded in `matching.skipTitleRules` so the title-skip pass catches most of them. Note: many target titles contain the word "Manager" (e.g. "Technical Program Manager") — never skip those on the word "Manager"; the `alwaysIncludeTitles` list protects them. When seniority is unclear from the title, click in and judge from the JD's scope/requirements.

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

Skip a role if its description matches any dealbreaker in `matching.descriptionSkips`. Each entry describes a background/requirement the candidate wants to avoid. The configured dealbreaker is sales-quota tethering: skip roles where comp or the core day-to-day is tied to hitting individual sales quotas — BUT keep pre-sales Solutions/Forward Deployed Engineer roles where the quota is incidental, not central. Apply each dealbreaker as: skip unless every other aspect is a near-perfect fit. If `matching.descriptionSkips` is empty, apply no description-based skips.

## Self-tuning inputs (for the self-tuning step)

When `preferences.agentic.selfTuningMatching` is on, the daily run inspects `data/state.json` for revealed-preference signals and PROPOSES (never silently applies) edits to `profile.json.matching`:
- Consistently **hidden** roles sharing a domain, company stage, salary band, or sub-family → propose a new `descriptionSkips` entry, a `skipTitleRules` addition, or a `salaryTarget` bump.
- Consistently **applied/starred** roles sharing a domain → propose promoting that domain into `priorityDomains`.
- Record every proposal with timestamp + rationale in `data/tuning-log.json`, and present them in the morning briefing for the user to accept or decline. Apply only on explicit confirmation.
