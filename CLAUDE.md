# Job Hunt Pipeline — CLAUDE.md

## Project Overview

**Goal**: Automate job application workflow for internships in Switzerland using Claude as intelligent screening, material generation, and tracking agent.

**Scope**: Monitor 8 Swiss job portals, screen for fit, generate customized CV/cover letters, organize files, track applications, monitor email responses, assist with form filling.

**Timeline**: Available on 2 weeks' notice. Start: immediate upon notification.

**Status**: Under active development. Phase 1 (Weeks 1-3): Core pipeline. Phase 2 (Weeks 4-6): Dashboard and email monitoring.

---

## Technical Stack

- **Language**: Python or Node.js (user preference: Node.js with JavaScript familiarity)
- **Claude API**: Haiku 4.5 (screening/cheap), Sonnet 4.6 (materials), Opus 4.6 (if needed)
- **Gmail API**: OAuth2 for email integration
- **Storage**: SQLite for application tracking (local), Google Sheets for dashboard (optional)
- **File Organization**: Local filesystem at `/aplicacoes/{empresa}/{vaga-data}/`
- **Scheduling**: Node.js cron or external scheduler for daily runs
- **Version Control**: Git, hosted at https://github.com/carlosedbaptista/job-hunt-pipeline

---

## Code Patterns & Standards

- **No em dashes**: Use commas, colons, or restructure sentences instead
- **Logging**: All errors go to console + file in `/digests/`
- **Error handling**: Try-catch on every API call; graceful degradation
- **Naming**: snake_case for files/folders, camelCase for code variables
- **Comments**: Document why, not what. Code should be self-explanatory
- **Commits**: Atomic, descriptive messages. Link to work item if applicable

---

## Business Rules (CRITICAL)

1. **NEVER submit an application without explicit user approval** — this is non-negotiable
2. **Always ask before deleting or overwriting files**
3. **Deduplication**: Same job on multiple portals = track only once (by company + title + city + 7-day window)
4. **Email handling**: Parse emails case-insensitively; erring on the side of caution for recruiter responses
5. **Scoring is input, not gospel**: Score < 75 can still be applied if user overrides
6. **Rate limiting**: Max 30 vagas processed per day to control costs
7. **Cost optimization**: Haiku >> Sonnet >> Opus (use cheapest model first)

---

## User Context — Cadu (Carlos Eduardo Duarte Baptista)

**Role**: Data and business analysis professional, positioning as Analyst/AI User (NOT developer)

**Background**: 
- QUOD (Brazil, Business Process Analyst): 40% manual work reduction
- netzdenker.com (Switzerland, Analytics Associate): Power BI, GA4, AI-assisted workflows
- Education: Postgraduate in Data Science (expected Oct 2026), Bachelor's in Systems Analysis
- Languages: Portuguese (native), English (C1), Spanish (B2), German (A2, ongoing)

**Contact**: carlosedbaptista@gmail.com | LinkedIn: linkedin.com/in/carlosedbaptista | Phone: +41 78 261 34 74

**Work Status**: Swiss Work Permit B (valid), based in Wallisellen, available on 2 weeks' notice

**Certifications**: Google AI Essentials (2025) | Anthropic Claude Courses (2026) | GA4 Certification (2026)

---

## Materials Base

All base materials are in `/mnt/user-data/outputs/` on Claude's system. When building agents, reference these:

- **CV Master**: `Carlos_Baptista_CV_Master_v3.docx` — 1 page, data analyst positioning, "available on 2 weeks' notice"
- **Cover Letter Template**: `Carlos_Baptista_CoverLetter_Template.docx` — Base template with placeholders for company-specific customization
- **Positioning**: `positioning.md` — Analyst/AI User profile, hard constraints (Zurich/Zug location, English required, no dev-only roles), target roles
- **Evaluation Rubric**: `evaluation_rubric.md` — Scoring 0-100 (technical 40pts, contextual 35pts, opportunity 25pts), thresholds (>=75 APPLY, 55-74 REVIEW, <55 UNCERTAIN ask user)

**Key positioning**: Data analyst, not software engineer. Uses Claude/ChatGPT/Gemini daily as professional tools. Cross-cultural profile (Brazilian, based in Zurich area, polyglot). Quantified results (40% reduction at QUOD).

---

## Project Structure
job-hunt-pipeline/
├── src/                      # Main pipeline code
│   ├── index.js             # Entry point (cron job or manual trigger)
│   ├── email-fetcher.js     # Fetch job alerts from Gmail
│   ├── job-evaluator.js     # Call Haiku to score jobs
│   ├── materials-generator.js # Call Sonnet to create CV/cover letters
│   └── tracker-updater.js   # Update SQLite with submissions/responses
├── skills/                   # Reusable knowledge files for Claude
│   ├── evaluate-job-fit.md  # Rubric and examples
│   ├── write-as-cadu.md     # Tone, style, positioning
│   └── tracker-schema.md    # Database structure
├── agents/                   # Subagent definitions
│   ├── email-parser.js      # Parse job alert emails (one per portal)
│   ├── job-evaluator.js     # Score jobs (Haiku)
│   ├── cover-letter-writer.js # Generate CLs (Sonnet)
│   ├── cv-tailor.js         # Adjust CV per role
│   ├── tracker-updater.js   # Database updates
│   └── email-monitor.js     # Detect recruiter responses
├── aplicacoes/              # User's applications (organized by company)
│   └── {empresa-slug}/
│       └── {vaga-slug-date}/
│           ├── cv.pdf
│           ├── cover.pdf
│           ├── job_description.md
│           └── evaluation.json
├── tracker/                 # Application tracking
│   └── applications.db      # SQLite with submissions, responses, follow-ups
├── digests/                 # Daily email summaries
│   └── {date}_digest.txt
├── .env                     # Credentials (Gmail, API keys) — NEVER commit
├── .gitignore              # Excludes .env, node_modules, logs
├── CLAUDE.md               # This file
├── README.md               # User-facing documentation
└── package.json            # Node dependencies (when we build it)

---

## Subagents Overview

Each subagent is a focused Claude instance with a specific role:

1. **email-parser**: Extracts structured data from job portal alert emails
2. **job-evaluator**: Scores fit 0-100 using Haiku (cheap, fast)
3. **cover-letter-writer**: Drafts tailored CLs using Sonnet (quality)
4. **cv-tailor**: Adjusts CV emphasis per role, maintains 1-page constraint
5. **tracker-updater**: Logs submissions, responses, follow-ups to SQLite
6. **email-monitor**: Detects recruiter responses in Gmail (runs 2x/day)
7. **followup-writer**: Generates follow-up messages for stale applications

Each subagent:
- Has clear input/output spec
- Uses a skill file for domain knowledge
- Logs all decisions
- Never makes permanent changes without confirmation

---

## Daily Workflow (Once Pipeline is Live)

1. **6:00 AM**: Cron triggers email fetcher → parses job alerts from 8 portals
2. **6:15 AM**: Evaluator screens all jobs → outputs shortlist (score >= 55)
3. **6:30 AM**: User receives email digest with top 5 jobs, scores, reasoning
4. **User action**: Replies "1, 3, 5 approved" (or manually reviews in dashboard)
5. **Materials generation**: Sonnet generates customized CV/cover letters for approved jobs
6. **Storage**: Files organized in /aplicacoes/{empresa}/{vaga}/ with standardized names
7. **2:00 PM & 6:00 PM**: Email monitor checks for recruiter responses
8. **Dashboard**: Real-time view of submission status, response rate, pending follow-ups

---

## Security & Credentials

**Never commit these files:**
- `.env` (contains Gmail OAuth token, API keys)
- `tracker/applications.db` (contains personal data)
- Any PDFs in `aplicacoes/`

**Setup .env template**:
GMAIL_CLIENT_ID=your_client_id_here
GMAIL_CLIENT_SECRET=your_client_secret_here
ANTHROPIC_API_KEY=your_api_key_here
DB_PATH=./tracker/applications.db

**Before first run**: 
1. Create `.env` file (use template above)
2. Run Gmail OAuth flow (one-time setup)
3. Test email fetcher with a dry run

---

## Common Tasks

**Adding a new job portal**:
- Create parser in `agents/email-parser-{portal}.js`
- Update email filter labels in Gmail
- Test extraction with sample email

**Customizing scoring rubric**:
- Edit `/mnt/user-data/outputs/evaluation_rubric.md`
- Update job-evaluator with new weights if needed

**Reviewing application tracker**:
- Query SQLite: `SELECT company, role, status, days_pending FROM applications WHERE status = 'pending' ORDER BY date_submitted DESC`

**Sending follow-up**:
- Email monitor flags applications > 14 days pending
- User approves in dashboard
- followup-writer generates message
- User manually sends (not automated)

---

## Known Constraints & Future Work

- **Phase 1**: Screening + manual submission (user fills forms with Claude in Chrome helper)
- **Phase 2**: Automated ATS form filling (requires Claude in Chrome for Workday, Greenhouse, Lever)
- **Phase 3**: Proactive outreach (LinkedIn cold messages — out of scope, LinkedIn ToS)
- **Cost**: Estimated ~0.50-2.00 CHF/day for screening + materials (depends on volume)

---

## References

- Gmail API Docs: https://developers.google.com/gmail/api/guides
- Claude API Docs: https://docs.anthropic.com
- Job portals setup: See `positioning.md` for list
- Evaluation criteria: See `evaluation_rubric.md`

---

**Last Updated**: June 2026  
**Next Review**: After Phase 1 complete (end of Week 6)