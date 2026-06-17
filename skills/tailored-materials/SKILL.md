---
name: tailored-materials
description: Generate tailored application materials for a specific job from the user's job board — a role-tuned resume variant, a cover letter, and short outreach drafts (recruiter / hiring manager / referral). Use when the user says "tailor my resume for this role", "write a cover letter for <company>", "draft outreach for the <role> job", "prep materials for that posting", or picks a role from the board to apply to. Reads the role from jobs.json, the candidate's base resume and profile from profile.json, and stages everything under data/applications/{role-id}/. NEVER auto-sends anything — all materials are drafts for the user to review and send themselves.
---

# Tailored Materials

Produce application materials tailored to one specific role: a resume variant, a cover letter, and outreach drafts. Everything is staged as files for the user to review — this skill NEVER sends email, messages, or applications (`preferences.agentic.autoSend` is always false).

## Inputs

Read from the workspace folder's `data/`:

- `data/profile.json` — `candidate` (name, currentRole, yearsExperience, background, domainExpertise, contact, `resumePath`) and `preferences`.
- `data/jobs.json` — find the target role by `id` (or by company+title if the user names it). Use its `title`, `company`, `fullDescription`, `outreachContext`, `tags`, `domain`, `url`, salary, and `matchPercent`.
- The base resume at `candidate.resumePath` (under `data/resumes/`). Read its full text (use the docx skill for .docx, the pdf skill for .pdf).

If the role isn't in `jobs.json`, ask the user to paste the JD or run the daily search first. If the profile or resume is missing, send the user to `job-search-setup`.

## Output location

Stage all files under `data/applications/{role-id}/`:

- `resume-{role-id}.docx` — the tailored resume variant.
- `cover-letter-{role-id}.docx` — the cover letter.
- `outreach-{role-id}.md` — the outreach drafts (recruiter, hiring manager, referral) in one file.
- `notes-{role-id}.md` — a short rationale: what was emphasized/reordered and why, plus any gaps to be aware of.

Create the folder if needed.

## Workflow

1. **Read the role + resume + profile.** Build a clear picture of what the JD asks for (required + nice-to-have) and which of the candidate's real experiences map to each requirement.

2. **Map, don't invent.** List the JD's top requirements and, for each, the strongest matching evidence from the resume (projects, metrics, technologies, scope). Never fabricate experience, titles, employers, dates, or metrics. If the JD wants something the candidate lacks, do not claim it — either omit or honestly frame adjacent experience.

3. **Tailor the resume (use the docx skill).** Read the docx SKILL.md first. Start from the base resume and produce a variant that:
   - Reorders/spotlights the experience and skills most relevant to THIS role (e.g. emphasize cross-team program delivery + platform migrations for a TPM role; emphasize client-facing technical delivery + integrations for an SE/FDE role).
   - Mirrors the JD's vocabulary where it's truthful (use the same terms for the same real things).
   - Keeps every factual claim identical to the base resume — only emphasis, ordering, and summary wording change. Preserve formatting quality.
   - Keeps a clean professional layout. Save as `resume-{role-id}.docx`.

4. **Write the cover letter (use the docx skill).** One page, three-to-four short paragraphs: a specific hook tied to the company/team (`outreachContext.teamMission` / `notableDetails`), two-to-three concrete proof points mapping the candidate's real work to the role's core needs, and a warm close. Specific over generic; no filler, no clichés, no invented enthusiasm-as-fact. Save as `cover-letter-{role-id}.docx`.

5. **Draft outreach (`outreach-{role-id}.md`).** Three short, send-ready drafts the user can copy:
   - **Recruiter / application note** — 3–5 sentences, why this role, top relevant proof point, link to nothing the user hasn't approved.
   - **Hiring manager (LinkedIn/email)** — 3–4 sentences, references the team's mission/`whyRoleExists`, one sharp credential, a low-friction ask.
   - **Referral / warm intro** — a brief note the user could send to a mutual connection asking for an intro.
   Each draft: personable, concise, specific, no hype. Leave clearly-marked placeholders like `[recruiter name]` where the user must fill in.

6. **Write `notes-{role-id}.md`.** Briefly explain what you emphasized and why, plus any honest gaps between the resume and JD the user should be ready to address.

7. **Present the files.** Share the generated files (resume, cover letter, outreach, notes) with the file-sharing tool and give a one- or two-sentence summary. Remind the user nothing was sent — these are drafts to review, edit, and send themselves.

## Guardrails

- NEVER send, submit, or schedule anything. Drafts only.
- NEVER fabricate experience, employers, dates, degrees, certifications, or metrics. Tailoring = emphasis and framing of true facts, never invention.
- Keep claims consistent with the base resume; if the user wants to add something not on it, ask them to confirm it's real first.
- Match the JD's tone but keep the candidate's authentic voice; avoid generic AI-cover-letter phrasing.
