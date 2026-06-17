---
name: interview-prep
description: Generate an interview prep pack for a specific role the user is interviewing for — likely interview questions mapped to the JD, a STAR-format story bank drawn from the user's real resume experience, smart questions to ask the interviewer, and company/role talking points. Use when the user says "help me prep for my interview", "I have an interview with <company>", "prep me for the <role> interview", or "do my queued interview prep" (draining the board's Interview Prep queue at data/queue/interview-prep.json — the per-card "Interview Prep" button enqueues roles there). Reads the role from jobs.json, the candidate's resume and profile, and any company brief, then writes a prep pack under data/interview-prep/{role-id}/.
---

# Interview Prep

Build a focused interview prep pack for one role: likely questions, a STAR story bank from the candidate's real experience, questions to ask back, and talking points. Grounded entirely in the candidate's actual resume and the real JD — never invented experience.

## Working the queue

The board's per-card **Interview Prep** button enqueues roles into `data/queue/interview-prep.json` (`{schemaVersion, requests:[{id, company, title, url, requestedAt, status}]}`). When the user says "do my queued interview prep," process each request with `status == "pending"`: build the pack (below) for that role id, then mark the request `"done"`. For a single role asked about directly in chat, skip the queue and just build the pack. Dedup is handled at enqueue time, so each pending role appears once.

## Inputs

Read from the workspace folder's `data/`:

- `data/profile.json` — `candidate` (background, domainExpertise, yearsExperience, managementExperience) and `preferences`.
- `data/jobs.json` — the target role by `id` (or company+title). Use `title`, `company`, `fullDescription`, `outreachContext`, `domain`, `tags`, and `skillMatch` (the cached `{matched, gaps, rationale}` from the daily run, if present).
- The base resume at `candidate.resumePath` — read full text (docx skill / pdf skill).
- `data/briefs/{role-id}.md` if a company brief exists — reuse it for company context; do not duplicate research unnecessarily.

If the role isn't in `jobs.json`, ask the user to paste the JD. If profile/resume is missing, send the user to `job-search-setup`.

## Output location

Write the pack under `data/interview-prep/{role-id}/`:

- `prep-{role-id}.md` — the full prep pack (single readable document).

Create the folder if needed. A single well-structured markdown file is preferred; only split into multiple files if the user asks.

## Workflow

1. **Read the role + resume + profile (+ brief).** Identify the role family (TPM vs. Solutions Engineer vs. Forward Deployed Engineer) — the question mix differs:
   - **TPM** — cross-team delivery, dependency/risk management, stakeholder alignment, prioritization, handling slipping timelines, technical depth to earn engineers' trust, metrics/process.
   - **Solutions Engineer** — technical discovery, demos, mapping product to customer problems, objection handling, working with sales/product, balancing pre-sales without owning a quota.
   - **Forward Deployed Engineer** — embedding with customers, building/integrating against their stack, ambiguity, prioritizing customer-driven work vs. core product, hands-on coding + delivery.

2. **Likely questions, mapped to the JD.** Produce a set of probable questions grouped by type: behavioral, role-specific/technical, system/process or design (as appropriate to the family), and company/motivation. Tie each cluster to specific JD requirements so the user sees why it's likely.

3. **STAR story bank — from REAL experience only.** From the resume, build 5–8 STAR stories (Situation, Task, Action, Result) using the candidate's actual projects, scope, technologies, and metrics. Map each story to the question types it answers (e.g. a platform-migration story → "tell me about a complex cross-team project," "a time a timeline slipped," "driving alignment without authority"). Never invent a story, metric, or outcome. If a common question has no matching real story, say so and suggest how to honestly frame adjacent experience.

4. **Questions to ask the interviewer.** 6–10 sharp, specific questions drawn from `outreachContext` and the JD (team mission, why the role exists, success in 90 days, how delivery/decisions work, biggest current challenge), avoiding anything answered on the careers page.

5. **Talking points & positioning.** A short section: the candidate's 2–3 strongest selling points for THIS role, how to frame the IC/program-lead preference positively, how to address any obvious gap honestly, and a crisp "why this company / why this role" narrative grounded in the brief. If the role has a cached `skillMatch`, lead from it: use `matched` to anchor the strongest selling points, and turn each `gaps` entry into an honest plan (transferable experience, recent learning, or candid acknowledgement) rather than re-deriving gaps from scratch. Sanity-check the cached gaps against the JD and drop any that are stale or no longer apply.

6. **Logistics checklist (light).** A brief reminder list: research the interviewers, re-read the JD, prepare the STAR stories, have questions ready, test any demo/coding setup if relevant.

7. **Present the file.** Share `prep-{role-id}.md` with the file-sharing tool and give a one- to two-sentence summary. Offer to do a mock-interview Q&A in chat if the user wants live practice.

## Guardrails

- Every STAR story and metric must come from the candidate's real resume/experience. Never fabricate.
- Don't over-coach into a script — give frameworks and real material, keep the candidate's authentic voice.
- If a JD requirement is a genuine gap, flag it honestly and suggest an authentic way to address it rather than papering over it.
