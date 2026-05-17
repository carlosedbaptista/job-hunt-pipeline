"""
pipeline.py  —  Email ingestion orchestrator
Runs: fetch emails → parse jobs → deduplicate → output

Usage:
  python src/pipeline.py              # last 24h
  python src/pipeline.py --hours 48   # last 48h
  python src/pipeline.py --dry-run    # without saving to DB (test mode)
"""

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.email_ingestor import fetch_job_alert_emails
from agents.email_parser import parse_all_emails
from src.deduplicator import filter_new_jobs, get_stats


def run_pipeline(hours_back: int = 24, dry_run: bool = False) -> list[dict]:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    divider = "=" * 55

    print(f"\n{divider}")
    print(f"  JOB HUNT PIPELINE  —  {timestamp}")
    if dry_run:
        print("  ⚠️  DRY RUN — nothing will be saved to the database")
    print(f"{divider}\n")

    os.makedirs("digests", exist_ok=True)
    os.makedirs("tracker", exist_ok=True)

    # ── STEP 1: Fetch emails ─────────────────────────────────────────────────
    print("STEP 1 › Fetching job alert emails...")
    emails = fetch_job_alert_emails(hours_back=hours_back)

    if not emails:
        print("No emails found. Pipeline stopped.\n")
        return []

    with open("digests/raw_emails_full.json", "w", encoding="utf-8") as f:
        json.dump(emails, f, ensure_ascii=False, indent=2)

    # ── STEP 2: Parse jobs ───────────────────────────────────────────────────
    print(f"\nSTEP 2 › Extracting jobs with Claude Haiku ({len(emails)} emails)...")
    all_jobs = parse_all_emails(emails)

    with open("digests/parsed_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n  → {len(all_jobs)} jobs extracted in total")

    if not all_jobs:
        print("No jobs extracted. Pipeline stopped.\n")
        return []

    # ── STEP 3: Deduplicate ──────────────────────────────────────────────────
    print("\nSTEP 3 › Filtering duplicates...")

    if dry_run:
        seen_keys = set()
        new_jobs = []
        for job in all_jobs:
            key = f"{job.get('empresa','').lower()}|{job.get('titulo','').lower()}"
            if key not in seen_keys:
                seen_keys.add(key)
                new_jobs.append(job)
    else:
        new_jobs = filter_new_jobs(all_jobs)

    duplicates = len(all_jobs) - len(new_jobs)
    print(f"  → {len(new_jobs)} new  |  {duplicates} duplicates filtered")

    # ── OUTPUT ───────────────────────────────────────────────────────────────
    run_ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = f"digests/new_jobs_{run_ts}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(new_jobs, f, ensure_ascii=False, indent=2)

    with open("digests/new_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(new_jobs, f, ensure_ascii=False, indent=2)

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    print(f"\n{divider}")
    print(f"  RESULTS")
    print(f"{divider}")
    print(f"  Emails processed : {len(emails)}")
    print(f"  Jobs extracted   : {len(all_jobs)}")
    print(f"  New jobs         : {len(new_jobs)}")
    print(f"  Saved to         : {output_path}")

    if new_jobs:
        print(f"\n  Top new jobs:")
        for i, job in enumerate(new_jobs[:5], 1):
            empresa = job.get("empresa", "N/A")
            titulo = job.get("titulo", "N/A")
            local = job.get("localizacao", "?")
            portal = job.get("portal", "")
            print(f"  {i}. [{portal}] {empresa} — {titulo} ({local})")

    if not dry_run:
        stats = get_stats()
        print(f"\n  DB stats: {stats}")

    print(f"\n✅ Pipeline completed at {datetime.now().strftime('%H:%M')}\n")
    return new_jobs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt Pipeline")
    parser.add_argument(
        "--hours", type=int, default=24, help="Search window in hours (default: 24)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without saving to database (useful for testing)",
    )
    args = parser.parse_args()

    jobs = run_pipeline(hours_back=args.hours, dry_run=args.dry_run)
    sys.exit(0 if jobs is not None else 1)
