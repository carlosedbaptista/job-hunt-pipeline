"""
week3_pipeline.py  —  Evaluation and materials orchestrator
Runs: job evaluation → cover letters → tailored CVs
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def run_step(script: str, description: str) -> bool:
    """Runs a script and returns True on success."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(
            [sys.executable, script],
            cwd=ROOT,
            capture_output=False,
            text=True,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Error running {script}: {e}")
        return False


def run_evaluation_pipeline():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*60}")
    print(f"  JOB HUNT — EVALUATION PIPELINE  |  {timestamp}")
    print(f"  Evaluation & Materials")
    print(f"{'='*60}")

    print("\nSTEP 1 › Evaluating job fit...")
    if not run_step("agents/job_evaluator.py", "Job Evaluator (Haiku)"):
        print("❌ Evaluation failed.")
        return False

    print("\nSTEP 2 › Generating cover letters...")
    if not run_step("agents/cover_letter_writer.py", "Cover Letter Writer (Sonnet)"):
        print("⚠️  Cover letter generation failed (not all jobs qualify)")

    print("\nSTEP 3 › Tailoring CVs...")
    if not run_step("agents/cv_tailor.py", "CV Tailor (Sonnet)"):
        print("⚠️  CV tailoring failed (not all jobs qualify)")

    print(f"\n{'='*60}")
    print(f"  FINAL RESULTS")
    print(f"{'='*60}\n")

    if os.path.exists("digests/job_evaluations_latest.json"):
        with open("digests/job_evaluations_latest.json", "r") as f:
            evals = json.load(f)

        apply = [e for e in evals if e.get("score", 0) >= 65]
        review = [e for e in evals if 45 <= e.get("score", 0) < 75]
        uncertain = [e for e in evals if e.get("score", 0) < 45]

        print(f"Total jobs evaluated: {len(evals)}\n")

        if apply:
            print(f"✅ APPLY ({len(apply)}) — generating cover letter + CV:")
            for e in apply:
                score = e.get("score", 0)
                job = e.get("job", {})
                print(f"   • [{score}/100] {job.get('empresa')} — {job.get('titulo')[:40]}")

        if review:
            print(f"\n⚠️  REVIEW ({len(review)}) — needs your decision:")
            for e in review:
                score = e.get("score", 0)
                job = e.get("job", {})
                print(f"   • [{score}/100] {job.get('empresa')} — {job.get('titulo')[:40]}")

        if uncertain:
            print(f"\n❌ UNCERTAIN ({len(uncertain)}) — does not meet criteria:")
            for e in uncertain:
                score = e.get("score", 0)
                job = e.get("job", {})
                flags = e.get("red_flags", [])
                print(f"   • [{score}/100] {job.get('empresa')} — {job.get('titulo')[:40]}")
                if flags:
                    print(f"      Issues: {'; '.join(flags[:2])}")

        print(f"\n{'='*60}")
        print(f"  Generated files:")
        print(f"  • Evaluations: digests/job_evaluations_latest.json")

        if os.path.exists("digests/cover_letters_latest.json"):
            with open("digests/cover_letters_latest.json", "r") as f:
                letters = json.load(f)
            print(f"  • Cover letters: digests/cover_letters_latest.json ({len(letters)} letters)")

        if os.path.exists("digests/tailored_cvs_latest.json"):
            with open("digests/tailored_cvs_latest.json", "r") as f:
                cvs = json.load(f)
            print(f"  • Tailored CVs: digests/tailored_cvs_latest.json ({len(cvs)} CVs)")

        print(f"\n✅ Pipeline completed at {datetime.now().strftime('%H:%M')}")
        return True

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt — Evaluation Pipeline")
    args = parser.parse_args()

    success = run_evaluation_pipeline()
    sys.exit(0 if success else 1)
