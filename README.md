# Job Hunt Pipeline

Automated job search and evaluation pipeline for AI / agentic systems / data platform engineering roles (internship and junior level) in Switzerland (Zurich/Zug). Runs twice daily via GitHub Actions, pulls from multiple job sources, evaluates fit with an LLM, and delivers a personalized digest to your email.

---

## Overview

This pipeline automates the tedious parts of job hunting:

1. **Ingest** -- Fetches jobs from Adzuna API + Gmail job alerts
2. **Deduplicate** -- In-batch and cross-run dedup via SQLite (21-day window), so each job is evaluated once
3. **Enrich** -- Email alert cards carry a title and nothing else; the missing description is looked up on Adzuna so the job is scored on real text
4. **Evaluate** -- Scores each job for fit using Kimi LLM (0-100 scale); API failures are marked ERROR, never scored
5. **Decide** -- Classifies as APPLY (>=80), REVIEW (70-79), or SKIP (<70)
6. **Digest** -- Generates a ranked daily digest with top 5 jobs
7. **Notify** -- Sends a formatted HTML email with results
8. **Track** -- Persists seen jobs in SQLite and full evaluation history in `data/history/`

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
|-- Description Enricher (Adzuna) --> digests/new_jobs_latest.json
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
| AI Evaluation | Kimi API (kimi-k2.6; fallback via `KIMI_MODEL_FALLBACK`) |
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

Copy `config/candidate_profile.example.json` to `config/candidate_profile.json` (gitignored) and fill it in. The example lists every key the pipeline actually reads and what each one feeds; a key left out silently weakens every score.

## Search Targeting

`agents/adzuna_ingestor.py` defines the queries. Set `ADZUNA_QUERIES` (semicolon-separated) to retarget without editing code. Adzuna's free tier allows 100 calls/day and the list is multiplied by 2 locations and 2 scheduled runs, so 12 queries costs 48/day and leaves room for the enricher's 24.

## Scoring Rubric

Thresholds live in one place: `src/utils.py` (`THRESHOLD_APPLY` / `THRESHOLD_REVIEW`, overridable via env). Evaluator, digest, dashboard, email and alerts all read from there.

| Score | Decision | Action |
|-------|----------|--------|
| 80-100 | APPLY | Strong fit |
| 70-79 | REVIEW | Moderate fit -- review manually |
| 0-69 | SKIP | Low fit |
| (no score) | ERROR | API failure -- job not evaluated, excluded from metrics |

Two low-confidence caps sit on top of the thresholds: a job with under `MIN_DESCRIPTION_CHARS` (200) of posting text, and a job whose posting asks for an intermediate level of a language beyond English, are capped at REVIEW rather than APPLY. A real hard eligibility blocker caps the decision at SKIP regardless of score.

"Intermediate" is relative to you, not fixed: `language_levels` in the profile (e.g. `{"german": "A2"}`) drives it, and the band is every CEFR level above yours and below C1. At A2 that is B1 and B2; once you reach B1 it narrows to B2 alone. Update the profile, not the code.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The suite mocks the LLM, so it costs nothing and needs no secrets. It covers the scoring rules (`tests/test_scoring_consistency.py`) and the ingestion quality rules (`tests/test_ingestion_quality.py`); it runs on every push and pull request via `.github/workflows/tests.yml`. Run it before touching scoring, dedup or parsing logic.

## Project Structure

```
job-hunt-pipeline/
├── .github/workflows/      # Daily pipeline, manual actions, tests
├── agents/                 # Ingestors, enricher, evaluator, notifier
├── src/                    # Core pipeline + utils
├── tests/                  # pytest suite (mocked LLM, no secrets)
├── config/                 # Candidate profile + settings
├── data/raw_jobs/          # Raw job listings
├── data/history/           # Evaluation history
├── digests/                # Daily digests + dashboard
├── tracker/                # SQLite database
├── scripts/                # Utility scripts
├── docs/legacy/            # Archived documentation
├── requirements.txt
├── requirements-dev.txt
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
