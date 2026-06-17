---
name: job-search-setup
description: One-time (or re-run) configuration for the job-search agent. Use when the user wants to set up, configure, onboard, or re-configure their daily job search — e.g. "set up my job search", "configure job scout", "update my job search profile", "change my salary target or location", or when the daily job search reports that no profile exists yet. Collects location, salary target, target titles, location/remote rule, seniority levels, dealbreakers, and search sources through questions, ingests one or more uploaded resumes, and writes profile.json and a seeded search.json into the workspace folder you choose during setup. Tuned by default for Technical Program Manager / Solutions Engineer / Forward Deployed Engineer searches, but fully editable.
---

# Job Search Setup

Configure the personalized job-search agent by collecting the user's profile and writing the config files the daily search reads on every run. Run once at onboarding; re-run any time to update salary, location, titles, seniority, dealbreakers, or resume.

## What this skill produces

Files in the `data/` subdirectory of the workspace folder you choose during setup:

- `data/profile.json` — the candidate profile and search preferences (every personal value the engine reads).
- `data/search.json` — a seeded v2 search configuration the daily search runs each day.
- `data/resumes/` — a copy of each ingested resume.

It does NOT touch `data/jobs.json`, `data/search-log.json`, or `data/state.json` (those are created/managed by the daily search). It also never modifies `state.json` — that file is the user's decisions and is read-only to the agent.

## Workflow

### Step 1 — Choose the workspace folder

Let the user choose where their job-search data lives. Do not assume a folder name or location.

1. If a folder is already connected from an earlier setup (it contains `data/profile.json`), use that one.
2. Otherwise, call the directory-request tool so the user can pick or create a folder. Whatever they choose becomes the workspace for this plugin.

Treat the chosen folder's `data/` subdirectory as the target for all files this plugin reads and writes. Create `data/` if it does not exist. The daily search uses this same folder every run.

If `data/profile.json` already exists, read it first and treat this run as an UPDATE: pre-fill answers with existing values and only change what the user wants.

### Step 2 — Ingest the resume(s)

Ask the user to upload one or more resumes (PDF, DOCX, TXT). Resumes uploaded in this conversation appear in the uploads folder.

For each resume:

1. Read the file. For PDF, extract text (use the pdf skill or `pdfplumber`/`pdftotext`). For DOCX, extract text (use the docx skill or `python-docx`). For TXT/MD, read directly.
2. Parse out: current title and employer, total years of relevant experience, management/leadership experience (who/what they have led, and whether they prefer IC vs. people-management), technical background, domain expertise, certifications, notable accomplishments and metrics, location, and contact details.
3. Copy the resume into `data/resumes/` so the daily search and tailored-materials steps can reference it. Record its path in `candidate.resumePath`.

Never invent experience, metrics, or titles. If a detail isn't in the resume, leave it blank and ask in Step 3.

### Step 3 — Collect preferences through questions

Use AskUserQuestion (focused questions, grouped sensibly) to collect anything not confidently parsed. Cover:

- **Location** — home city/state (drives the location rule and logging).
- **Location/remote rule** — for this agent the default is `remote-or-nyc-metro`: include any role that is fully remote and open to US candidates, OR any role in the NYC metro in any arrangement (remote/hybrid/onsite); exclude hybrid/onsite roles tied to a location outside the NYC metro. Adjust the metro and the remote scope to the user.
- **Target titles** — the role titles to search for. Default set: Technical Program Manager (Senior/Staff/Principal), Solutions Engineer (Senior), Forward Deployed Engineer (Senior).
- **Seniority levels** — which levels to include (default: Senior, Staff, Principal). Roles clearly below (intern/junior/associate/mid) and clearly above into people-leadership (Director/Head/VP/Chief) are skipped.
- **Salary target** — the single number used by the salary test (a role qualifies if this number falls WITHIN the posted range; only skip when the whole range tops out below it). Default $150,000 if unsure.
- **Years of relevant experience** — confirm the number parsed from the resume (drives the experience-penalty scoring rule).
- **Management/leadership style** — what they have led and whether they prefer IC / player-coach / program-lead vs. people-management (affects IC-vs-people-manager scoring).
- **Priority domains** — strongest domains; roles here get the top domain bonus. Default for this candidate: platform/infrastructure, data/ML platforms, developer tooling & CI/CD, cloud/AWS.
- **Adjacent domains** — related domains earning a partial bonus (e.g. martech, SaaS, observability, fintech/data).
- **Search sources** — which searches to enable: Google/WebSearch across ATS boards, hiring.cafe, LinkedIn keyword, Wellfound, Built In NYC, plus any specific ATS boards to watch.
- **Agentic options** — confirm which agentic steps to turn on (self-expanding discovery, tailored materials, company briefs, self-tuning matching, morning briefing, interview prep), the `topN` for heavy steps (default 10), and confirm `autoSend` stays false (the agent NEVER auto-sends outreach or applications).
- **Board** — the board is local: `data/jobs.json` + `data/state.json` are the source of truth, served by `scripts/serve.py` (`python3 scripts/serve.py` → http://127.0.0.1:8000). No external service required.
- **Schedule** — daily run time and timezone (default 07:00 America/New_York).

Then collect the **matching rules** — the judgment calls that decide what gets skipped and how roles score. Present the TPM/SE/FDE Default Preset below and ask the user to confirm or adjust, rather than typing from scratch:

- **Skip-title rules** — title categories to skip without clicking. Default preset below skips pure Product Management, marketing, non-technical sales, design, HR, finance, non-technical PM/coordination, too-senior (people-leadership), and too-junior. Let the user add/remove.
- **Always-include titles** — titles to review even if they resemble a skip category. CRITICAL for this agent: protect every TPM/SE/FDE alias (the word "Manager" in "Technical Program Manager" must never trigger a sales/PM skip; "Sales Engineer" is a pre-sales SE alias, not a sales rep). Let the user add their own.
- **Skip employers** — recruiter/aggregator firms that hide the real employer. Default: Ladders, Dice, Jobot, CyberCoders. Let the user add others.
- **Description dealbreakers** — background/requirement red flags that skip a role unless it's otherwise a near-perfect fit. Default for this candidate: quota-carrying/commission-driven sales roles where comp or the core day-to-day is tethered to individual sales quotas — BUT keep pre-sales Solutions/Forward Deployed Engineer roles where the quota is incidental. Keep this list tight and personal; never assume dealbreakers the user didn't state.

If the user says "use your judgment," propose sensible defaults derived from the resume and the preset, and confirm before writing.

### TPM/SE/FDE Default Preset (seed for matching rules)

Use this to pre-fill the matching questions. It is a starting point — let the user edit it.

```json
{
  "skipTitleRules": [
    { "category": "Product Management (pure)", "titles": ["Product Manager", "Senior Product Manager", "Group Product Manager", "Principal Product Manager", "Director of Product", "VP of Product", "Product Owner", "Chief Product Officer"] },
    { "category": "Marketing", "titles": ["Marketing Manager", "Brand Manager", "Content Marketing Manager", "Demand Gen Manager", "Growth Marketing Manager", "Product Marketing Manager", "Field Marketing"] },
    { "category": "Sales (non-technical)", "titles": ["Account Executive", "Sales Manager", "Business Development Representative", "Sales Development Representative", "Account Manager", "Sales Director", "Inside Sales"] },
    { "category": "Design", "titles": ["UX Designer", "Product Designer", "Design Manager", "Creative Director", "UI Designer"] },
    { "category": "HR/People", "titles": ["People Operations", "HR Manager", "Talent Acquisition", "Recruiter", "Sourcer"] },
    { "category": "Finance/Legal", "titles": ["Controller", "FP&A", "Legal Counsel", "Accountant", "Financial Analyst"] },
    { "category": "Non-technical PM/coordination", "titles": ["Project Coordinator", "Program Coordinator", "Project Manager (non-technical)", "Scrum Master (standalone)"] },
    { "category": "Seniority too high (people-leadership)", "titles": ["Director", "Head of", "VP", "Vice President", "SVP", "Chief", "Senior Director"] },
    { "category": "Seniority too junior", "titles": ["Intern", "Junior", "Associate", "Entry Level", "New Grad", "Apprentice"] }
  ],
  "alwaysIncludeTitles": [
    "Technical Program Manager", "Senior Technical Program Manager", "Staff Technical Program Manager", "Principal Technical Program Manager",
    "Solutions Engineer", "Senior Solutions Engineer", "Sales Engineer", "Pre-Sales Engineer", "Technical Solutions Engineer", "Solutions Consultant", "Solutions Architect",
    "Forward Deployed Engineer", "Forward Deployed Software Engineer", "Deployment Engineer", "Implementation Engineer", "Integration Engineer", "Customer Engineer", "Field Engineer", "Professional Services Engineer", "Delivery Engineer", "Onboarding Engineer"
  ],
  "skipEmployers": ["Ladders", "The Ladders", "Ladders.com", "Dice", "Jobot", "CyberCoders"],
  "descriptionSkips": [
    "Role is primarily a quota-carrying or commission-driven sales position — i.e. compensation or the core day-to-day responsibility is tethered to hitting individual sales quotas/targets. Skip unless the role is otherwise a near-perfect technical fit and the quota element is incidental (most pre-sales Solutions/Forward Deployed Engineer roles are fine)."
  ],
  "priorityDomains": ["platform / infrastructure", "data / ML platforms", "developer tooling & CI/CD", "cloud / AWS"],
  "adjacentDomains": ["martech / marketing technology", "SaaS", "observability / reliability", "fintech / data products"]
}
```

### Step 4 — Write `data/profile.json`

Write the profile using exactly this schema (omit nothing; use `null` or `""`/`[]` where unknown). This mirrors what the daily search reads:

```json
{
  "schemaVersion": 1,
  "candidate": {
    "name": "",
    "currentRole": "",
    "yearsExperience": 0,
    "managementExperience": "",
    "technicalBackground": "",
    "domainExpertise": [],
    "location": "",
    "contact": { "email": "", "linkedin": "", "website": "" },
    "resumePath": "data/resumes/<file>"
  },
  "preferences": {
    "salaryTarget": 150000,
    "remotePolicy": "remote-or-nyc-metro",
    "targetTitles": [],
    "seniorityLevels": ["Senior", "Staff", "Principal"],
    "locationRule": {
      "includeRemoteScope": "US",
      "metroIncludeAnyArrangement": ["New York City", "NYC", "New York, NY", "Brooklyn", "Manhattan", "NY metro", "Greater New York"],
      "excludeOnsiteOrHybridOutsideMetro": true,
      "notes": "Include fully-remote US roles OR any NYC-metro role in any arrangement; exclude hybrid/onsite tied outside the NYC metro."
    },
    "includePlatformInfraEngineering": "only-if-strong-match",
    "agentic": {
      "selfExpandingDiscovery": true,
      "tailoredMaterials": true,
      "companyBriefs": true,
      "selfTuningMatching": true,
      "morningBriefing": true,
      "interviewPrep": true,
      "topN": 10,
      "autoSend": false
    },
    "board": { "type": "local-server", "serverScript": "scripts/serve.py", "host": "127.0.0.1", "port": 8000, "htmlSnapshotPath": "data/board.html" },
    "schedule": { "dailyRunTime": "07:00", "timezone": "America/New_York" }
  },
  "matching": { "...": "the matching object confirmed in Step 3" }
}
```

### Step 5 — Write `data/search.json`

Write a v2 search config. Top-level keys: `schemaVersion` (2), `searches` (array), `watchlist` (array — seed empty; the daily search's self-expanding step appends `{ "company", "ats", "slug" }` entries), and `atsApi` (the per-provider URL templates).

Each search entry: `id`, `name`, `source`, `platform` (`google` | `hiringCafe` | `linkedin` | `custom` | `ats`), `url`, `method`, `enabled`, `resultLimit`, `targetSites` (google only), optional `queryTemplate`, and `filters` (`keywords[]`, `excludeKeywords[]`, `salaryMin`, `experienceLevel[]`, `remote`, `datePosted`). Seed the five default sources (Google/ATS, hiring.cafe, LinkedIn keyword, Wellfound, Built In NYC) with the user's keywords (the target titles), `salaryMin` = salary target, `experienceLevel` = seniority levels, and `datePosted` = past 24 hours.

`atsApi` templates:

```json
{
  "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
  "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
  "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
}
```

### Step 6 — Confirm and hand off

Summarize what was written (target titles, salary, location rule, seniority, sources, agentic options, schedule). Tell the user they can now run the daily search (invoke `daily-job-search`), and that re-running setup updates any value. Mention the local board: after a run, `python3 scripts/serve.py` serves it at http://127.0.0.1:8000. Offer to set up the scheduled daily run (via the schedule skill) at the configured time.

## Guardrails

- Never overwrite `state.json`, `jobs.json`, or `search-log.json` here.
- Never invent resume facts. Ask when unsure.
- Keep `descriptionSkips` minimal and strictly user-stated.
- The salary number is a single target used by a "within range" test — not a hard floor that excludes ranges spanning it.
