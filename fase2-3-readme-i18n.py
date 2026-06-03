#!/usr/bin/env python3
"""
=== FASE 2+3: README.md + Documentacao + Padronizacao EN ===
Cria README.md profissional, .env.example, candidate_profile.json,
e traduz prints principais para ingles.
"""
import os
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

def wf(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERRO: Rode dentro da pasta do repo"); exit(1)

print("=== FASE 2+3: README + Docs + EN Padronization ===\n")

# 1. README.md
wf(f"{REPO}/README.md", r"""# Job Hunt Pipeline

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
""")

# 2. .env.example
wf(f"{REPO}/.env.example", r"""# Kimi API (Moonshot AI)
KIMI_API_KEY=your_kimi_api_key_here

# Adzuna API
ADZUNA_APP_ID=your_adzuna_app_id
ADZUNA_APP_KEY=your_adzuna_app_key
ADZUNA_MAX_HITS=35

# Gmail (App Password - 16 characters)
GMAIL_SENDER=your_email@gmail.com
GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
GMAIL_RECIPIENT=your_email@gmail.com

# SQLite
DB_PATH=./tracker/jobs.db
""")

# 3. config/candidate_profile.json
wf(f"{REPO}/config/candidate_profile.json", r"""{
  "name": "Carlos Eduardo Duarte Baptista",
  "role": "Data/Business Analyst",
  "location": "Wallisellen, CH",
  "permit": "B",
  "notice_period": "2 weeks",
  "skills": ["SQL", "Python", "Power BI", "GA4", "Data Analysis"],
  "languages": {"pt": "Native", "en": "C1", "es": "B2", "de": "A2"},
  "email": "carlosedbaptista@gmail.com",
  "phone": "+41 78 261 34 74",
  "linkedin": "linkedin.com/in/carlosedbaptista",
  "github": "github.com/carlosedbaptista",
  "certifications": ["Google AI Essentials (2025)", "GA4 Certification (2026)"],
  "work_status": "Swiss Permit B, available on 2 weeks notice"
}
""")

# 4. Traduzir Adzuna ingestor prints
ADZUNA_PATH = f"{REPO}/agents/adzuna_ingestor.py"
if os.path.exists(ADZUNA_PATH):
    with open(ADZUNA_PATH, "r", encoding="utf-8") as f:
        c = f.read()
    c = c.replace("ADZUNA -- Busca ativa de vagas (Suica)", "ADZUNA -- Active job search (Switzerland)")
    c = c.replace("ADZUNA_APP_ID ou ADZUNA_APP_KEY nao configuradas. Pulando Adzuna.", "ADZUNA_APP_ID or ADZUNA_APP_KEY not set. Skipping Adzuna.")
    c = c.replace("App ID/Key invalidos.", "Invalid App ID/Key.")
    c = c.replace("Rate limit da Adzuna.", "Adzuna rate limit hit.")
    c = c.replace("Erro: {e}", "Error: {e}")
    c = c.replace("Nenhuma vaga. Verifique ADZUNA_APP_ID e ADZUNA_APP_KEY.", "No jobs found. Check ADZUNA_APP_ID and ADZUNA_APP_KEY.")
    c = c.replace("Total bruto: {len(all_raw)} | Unicas: {len(unique)}", "Raw: {len(all_raw)} | Unique: {len(unique)}")
    c = c.replace("Adzuna concluido", "Adzuna done")
    with open(ADZUNA_PATH, "w", encoding="utf-8") as f:
        f.write(c)
    print("[OK] agents/adzuna_ingestor.py translated")

# 5. Traduzir Unified ingestor prints
UNIFIED_PATH = f"{REPO}/src/unified_ingestor.py"
if os.path.exists(UNIFIED_PATH):
    with open(UNIFIED_PATH, "r", encoding="utf-8") as f:
        c = f.read()
    c = c.replace("Nenhum arquivo JSearch.", "No JSearch file.")
    c = c.replace("Nenhum arquivo de email parseado.", "No parsed email file.")
    c = c.replace("Nenhum arquivo LinkedIn.", "No LinkedIn file.")
    c = c.replace("Nenhum arquivo Adzuna.", "No Adzuna file.")
    c = c.replace("vagas unificadas", "unified jobs")
    c = c.replace("vagas (formato legado)", "jobs (legacy format)")
    c = c.replace("Apos dedup", "After dedup")
    c = c.replace("Nenhuma vaga de nenhuma fonte.", "No jobs from any source.")
    c = c.replace("UNIFIED INGESTOR -- JSearch + Email", "UNIFIED INGESTOR -- Multi-source aggregation")
    with open(UNIFIED_PATH, "w", encoding="utf-8") as f:
        f.write(c)
    print("[OK] src/unified_ingestor.py translated")

# 6. Traduzir Job Evaluator prints
EVAL_PATH = f"{REPO}/agents/job_evaluator.py"
if os.path.exists(EVAL_PATH):
    with open(EVAL_PATH, "r", encoding="utf-8") as f:
        c = f.read()
    c = c.replace("1 vaga por chamada, prompt pequeno, delay 2s", "1 job per API call, small prompt, 2s delay")
    c = c.replace("Estrutura de saida compativel com digest_generator e email_notifier.", "Output structure compatible with digest_generator and email_notifier.")
    c = c.replace("Nao avaliado (timeout)", "Not evaluated (timeout)")
    c = c.replace("Verificar manualmente no link", "Check manually via link")
    c = c.replace("API timeout -> REVIEW padrao", "API timeout -> default REVIEW")
    with open(EVAL_PATH, "w", encoding="utf-8") as f:
        f.write(c)
    print("[OK] agents/job_evaluator.py translated")

# 7. Commit
run("git add -A")
ok, _, err = run('git commit -m "docs: add README.md, .env.example, candidate profile; i18n: translate prints to English"')
if ok:
    print("\n[OK] Commit feito! Proximo: git push origin main")
else:
    print(f"\n[!] Commit: {err[:200]}")

print("\n=== FASE 2+3 CONCLUIDA ===")
print("Criado: README.md, .env.example, config/candidate_profile.json")
print("Traduzido: adzuna_ingestor.py, unified_ingestor.py, job_evaluator.py")
