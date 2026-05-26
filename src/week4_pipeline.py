"""
week4_pipeline.py  —  Full pipeline orchestrator
Runs: jsearch → email → parse → unify → evaluate → digest → notify
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime


def run_step(script: str, description: str) -> bool:
    """Runs a script and returns True on success."""
    print(f"\n{'='*70}")
    print(f"  {description}")
    print(f"{'='*70}\n")

    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=False,
            text=True,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def load_unified_jobs() -> list[dict]:
    """Loads the latest unified job file (JSearch + Email)."""
    files = sorted(glob.glob("data/raw_jobs/all_jobs_*.json"))
    if not files:
        return []
    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"📥 {len(jobs)} vagas carregadas de {latest}")
    return jobs


def run_full_pipeline():
    """Runs the full pipeline end-to-end."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*70}")
    print(f"  JOB HUNT — FULL PIPELINE")
    print(f"  Stage 1: JSearch + Email → Parse → Unify")
    print(f"  Stage 2: Evaluate → Cover Letters → CV Tailor")
    print(f"  Stage 3: Digest → Approval")
    print(f"  {timestamp}")
    print(f"{'='*70}")

    # ── STAGE 1: Ingestion ───────────────────────────────────────────────────
    print("\n🔍 STAGE 1: Active Search & Email Ingestion\n")

    run_step("agents/jsearch_ingestor.py", "JSearch — Active Job Search")

    if not run_step("src/email_ingestor.py", "Email Ingestor"):
        print("⚠️  Email ingestor failed")

    if not run_step("agents/email_parser.py", "Email Parser"):
        print("⚠️  Parsing failed (no jobs in emails)")

    if not run_step("src/unified_ingestor.py", "Unified Ingestor (JSearch + Email)"):
        print("❌ Unified ingestor failed")
        return False

    # ── STAGE 2: Evaluation ──────────────────────────────────────────────────
    print("\n📊 STAGE 2: Evaluation & Materials\n")

    jobs = load_unified_jobs()
    if not jobs:
        print("⚠️  No jobs to evaluate.")
        # Still try digest in case old evaluations exist
    else:
        if not run_step("agents/job_evaluator.py", "Job Evaluator"):
            print("❌ Evaluator failed")
            return False

    run_step("agents/cover_letter_writer.py", "Cover Letter Writer (optional)")
    run_step("agents/cv_tailor.py", "CV Tailor (optional)")

    # ── STAGE 3: Digest ──────────────────────────────────────────────────────
    print("\n📋 STAGE 3: Digest & Approval\n")

    if not run_step("agents/digest_generator.py", "Digest Generator"):
        print("❌ Digest failed")
        return False

    if not run_step("agents/email_notifier.py", "Email Notifier"):
        print("⚠️  Email notification failed (digest still saved to file)")

    if not run_step("agents/page_generator.py", "Page Generator (GitHub Pages)"):
        print("⚠️  Dashboard page generation failed")

    # ── SUMMARY ──────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  ✅ PIPELINE COMPLETE")
    print(f"{'='*70}\n")

    print("NEXT STEPS:")
    print("  1. Review the digest above")
    print("  2. Choose the jobs you want to apply to")
    print("  3. Run: python src/approval_handler.py --approve '1,3,5'")
    print("     (replace 1,3,5 with the job numbers)")
    print("")
    print("GENERATED FILES:")
    print("  • data/raw_jobs/all_jobs_*.json")
    print("  • digests/new_jobs_latest.json")
    print("  • digests/job_evaluations_latest.json")
    print("  • digests/digest_latest.json")
    print("  • digests/digest_latest.txt")
    print("")

    return True


def run_digest_only():
    """Runs only the digest step (useful if evaluations already exist)."""
    print(f"\n{'='*70}")
    print(f"  JOB HUNT — DIGEST ONLY")
    print(f"{'='*70}")

    return run_step("agents/digest_generator.py", "Digest Generator")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt — Full Pipeline")
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="Runs only the digest step (assumes earlier steps have already run)",
    )
    args = parser.parse_args()

    if args.digest_only:
        success = run_digest_only()
    else:
        success = run_full_pipeline()

    sys.exit(0 if success else 1)
