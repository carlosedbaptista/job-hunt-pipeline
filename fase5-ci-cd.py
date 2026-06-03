#!/usr/bin/env python3
"""
=== PHASE 5: CI/CD MODERNIZATION ===
Updates GitHub Actions workflow: Node.js 24, descriptive commits,
conditional continue-on-error, and professional job naming.
"""
import os
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERROR: Run this script from the repo root directory"); exit(1)

print("=== PHASE 5: CI/CD MODERNIZATION ===\n")

WORKFLOW_PATH = f"{REPO}/.github/workflows/job-hunt-scheduler.yml"

if not os.path.exists(WORKFLOW_PATH):
    print(f"ERROR: Workflow file not found at {WORKFLOW_PATH}")
    exit(1)

NEW_WORKFLOW = """name: Job Hunt Daily Pipeline

on:
  schedule:
    - cron: '0 5 * * *'   # 05:00 UTC = 07:00 CEST
    - cron: '0 12 * * *'  # 12:00 UTC = 14:00 CEST
  workflow_dispatch:

jobs:
  daily-pipeline:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Fetch Adzuna jobs
        env:
          ADZUNA_APP_ID: ${{ secrets.ADZUNA_APP_ID }}
          ADZUNA_APP_KEY: ${{ secrets.ADZUNA_APP_KEY }}
          ADZUNA_MAX_HITS: "35"
        run: python agents/adzuna_ingestor.py

      - name: Fetch LinkedIn jobs
        run: python agents/linkedin_ingestor.py
        continue-on-error: true

      - name: Fetch Gmail alerts
        env:
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GMAIL_SENDER: ${{ secrets.GMAIL_SENDER }}
        run: python src/email_ingestor.py
        continue-on-error: true

      - name: Parse job emails
        env:
          KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}
        run: python agents/email_parser.py
        continue-on-error: true

      - name: Unify job sources
        run: python src/unified_ingestor.py

      - name: Evaluate job fit with AI
        env:
          KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}
        run: python agents/job_evaluator.py

      - name: Generate daily digest
        env:
          KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}
        run: python src/week4_pipeline.py --digest-only

      - name: Generate dashboard
        env:
          DB_PATH: ./tracker/jobs.db
        run: python src/dashboard.py

      - name: Send email notification
        if: always()
        env:
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GMAIL_SENDER: ${{ secrets.GMAIL_SENDER }}
          GMAIL_RECIPIENT: ${{ secrets.GMAIL_RECIPIENT }}
        run: python agents/email_notifier.py

      - name: Commit and push results
        if: always()
        run: |
          git config user.name "github-actions"
          git config user.email "github-actions@github.com"
          git add data/raw_jobs/ digests/ tracker/jobs.db
          if git diff --cached --quiet; then
            echo "No changes to commit"
            exit 0
          fi
          JOB_COUNT=$(python -c "import json; d=json.load(open('digests/digest_latest.json')); print(d.get('total_evaluated', 0))" 2>/dev/null || echo 0)
          APPLY_COUNT=$(python -c "import json; d=json.load(open('digests/digest_latest.json')); jobs=d.get('top_jobs',[]); print(sum(1 for j in jobs if j.get('score',0)>=65))" 2>/dev/null || echo 0)
          TIMESTAMP=$(date -u +'%Y-%m-%d %H:%M UTC')
          git commit -m "chore: daily digest [$TIMESTAMP | $JOB_COUNT jobs | $APPLY_COUNT APPLY]"
          git push
"""

with open(WORKFLOW_PATH, "w", encoding="utf-8") as f:
    f.write(NEW_WORKFLOW)
print("[OK] .github/workflows/job-hunt-scheduler.yml -> updated")

# Commit
run("git add -A")
ok, _, err = run('git commit -m "ci: modernize workflow - descriptive commits, conditional error handling"')
if ok:
    print("\n[OK] Commit successful! Next: git push origin main")
else:
    print(f"\n[!] Commit issue: {err[:200]}")

print("\n=== PHASE 5 COMPLETE ===")
print("Changes:")
print("  - Job name: pipeline -> daily-pipeline")
print("  - Continue-on-error: removed from critical steps (unify, evaluate, digest, dashboard)")
print("  - Continue-on-error: kept for optional steps (linkedin, gmail, email_parser)")
print("  - Commit message: now includes timestamp, job count, and APPLY count")
print("  - Added 'No changes to commit' guard for empty runs")
