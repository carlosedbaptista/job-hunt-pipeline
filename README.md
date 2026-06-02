# Job Hunt Pipeline

Automated job search and evaluation pipeline for Data/Business Analyst positions in Switzerland (Zurich/Zug). Runs twice daily via GitHub Actions, scrapes multiple job sources, evaluates fit using AI scoring, and delivers a personalized digest to your email.

---

## Overview

This pipeline automates the tedious parts of job hunting:

1. **Ingest** -- Fetches jobs from Adzuna API + Gmail job alerts
2. **Evaluate** -- Scores each job for fit using Kimi LLM (0-100 scale)
3. **Decide** -- Classifies as APPLY (>=65), REVIEW (45-64), or SKIP (<45)
4. **Digest** -- Generates a ranked daily digest with top 5 jobs
5. **Notify** -- Sends a formatted HTML email with results
6. **Track** -- Stores application history in SQLite

---

## Architecture

```
GitHub Actions (2x/day: 05:00 & 12:00 UTC)
|
|-- Adzuna Ingestor --> data/raw_jobs/adzuna_YYYYMMDD.json
|-- Gmail IMAP --> digests/raw_emails_latest.json
|
|-- Email Parser --> digests/parsed_jobs_latest.json
|-- Unified Ingestor --> data/raw_jobs/all_jobs_*.json
|
|-- Job Evaluator (Kimi API) --> digests/job_evaluations_latest.json
|
|-- Digest Generator --> digests/digest_latest.json + .txt
|-- Dashboard Generator --> digests/dashboard.html
|-- Email Notifier (Gmail SMTP) --> Email sent to you
|
'-- Git commit & push --> Tracker persisted
```

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11 |
| Job Sources | Adzuna API, Gmail IMAP |
| AI Evaluation | Kimi API (moonshot-v1-8k) |
| Workflow | GitHub Actions |
| Email | Gmail SMTP (App Password) |
| Storage | SQLite + JSON files |
| Dashboard | GitHub Pages (static HTML) |

---

## Setup

### 1. Fork/Clone this repo

```bash
git clone https://github.com/carlosedbaptista/job-hunt-pipeline.git
cd job-hunt-pipeline
```

### 2. Create .env file

```bash
cp .env.example .env
# Edit .env with your keys
```

### 3. Add GitHub Secrets

Go to **Settings --> Secrets and variables --> Actions** and add:

| Secret | Description |
|--------|-------------|
| `KIMI_API_KEY` | Your Moonshot AI API key |
| `ADZUNA_APP_ID` | Adzuna API app ID |
| `ADZUNA_APP_KEY` | Adzuna API app key |
| `GMAIL_SENDER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Gmail App Password (16 chars) |
| `GMAIL_RECIPIENT` | Email address to receive digests |

### 4. Enable GitHub Pages

Go to **Settings --> Pages --> Source: main --> /(root)** --> Save

Dashboard: `https://carlosedbaptista.github.io/job-hunt-pipeline/digests/dashboard.html`

## Candidate Profile

Edit `config/candidate_profile.json` to customize your profile for job evaluation.

## Scoring Rubric

| Score | Decision | Action |
|-------|----------|--------|
| 65-100 | APPLY | Strong fit |
| 45-64 | REVIEW | Moderate fit -- review manually |
| 0-44 | SKIP | Low fit |

## Project Structure

```
job-hunt-pipeline/
├── .github/workflows/      # CI/CD workflow
├── agents/                 # Ingestors, evaluator, notifier
├── src/                    # Core pipeline + utils
├── config/                 # Candidate profile + settings
├── data/raw_jobs/          # Raw job listings
├── data/history/           # Evaluation history
├── digests/                # Daily digests + dashboard
├── tracker/                # SQLite database
├── scripts/                # Utility scripts
├── docs/legacy/            # Archived documentation
├── requirements.txt
├── .env.example
└── README.md
```

## Daily Workflow

| Time (UTC) | Time (CEST) | Action |
|------------|-------------|--------|
| 05:00 | 07:00 | Morning run |
| 12:00 | 14:00 | Afternoon run |

## License

MIT
