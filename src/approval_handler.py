"""
approval_handler.py  —  Processes job approvals
Usage: python src/approval_handler.py --approve "1,3,5"
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def load_digest():
    """Loads the latest digest file."""
    digest_file = "digests/digest_latest.json"
    if not os.path.exists(digest_file):
        print("❌ Digest not found. Run first: python agents/digest_generator.py")
        return None

    with open(digest_file, "r", encoding="utf-8") as f:
        return json.load(f)


def process_approvals(approval_string: str):
    """
    Processes user approvals.
    Example input: "1,3,5" or "1, 3, 5"
    """
    digest = load_digest()
    if not digest:
        return False

    top_jobs = digest.get("top_jobs", [])

    if not top_jobs:
        print("❌ No jobs in digest.")
        return False

    try:
        approved_ids = [int(x.strip()) for x in approval_string.split(",")]
    except ValueError:
        print(f"❌ Invalid format: '{approval_string}'")
        print("Use: --approve '1,3,5'")
        return False

    invalid_ids = [id for id in approved_ids if id < 1 or id > len(top_jobs)]
    if invalid_ids:
        print(f"❌ Invalid IDs: {invalid_ids} (must be between 1 and {len(top_jobs)})")
        return False

    approved_jobs = []
    for i, job_eval in enumerate(top_jobs, 1):
        if i in approved_ids:
            job = job_eval.get("job", {})
            approved_jobs.append({
                "position": i,
                "empresa": job.get("empresa", ""),
                "titulo": job.get("titulo", ""),
                "url": job.get("url", ""),
                "score": job_eval.get("score", 0),
                "approved_at": datetime.now().isoformat(),
            })

    print("\n" + "=" * 70)
    print("JOB APPROVAL")
    print("=" * 70)
    print(f"\nYou approved {len(approved_jobs)} job(s):")
    print()

    for job in approved_jobs:
        print(f"  ✅ #{job['position']} [{job['score']}/100] {job['empresa']}")
        print(f"     {job['titulo']}")
        print(f"     Link: {job['url'][:60]}...")
        print()

    os.makedirs("digests", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    approval_record = {
        "approved_at": datetime.now().isoformat(),
        "approved_jobs": approved_jobs,
        "next_step": "Copy the link above and submit the application manually on the company's website.",
    }

    approval_file = f"digests/approvals_{timestamp}.json"
    with open(approval_file, "w", encoding="utf-8") as f:
        json.dump(approval_record, f, ensure_ascii=False, indent=2)

    with open("digests/approvals_latest.json", "w", encoding="utf-8") as f:
        json.dump(approval_record, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("NEXT STEP:")
    print("1. Open each link above in your browser")
    print("2. Submit the application manually on the company's website")
    print("3. Response tracking will update automatically when the monitor runs")
    print("=" * 70)
    print(f"\n✅ Approval record saved: {approval_file}")

    return True


def list_digest():
    """Lists the jobs in the digest for reference."""
    digest = load_digest()
    if not digest:
        return

    print("\n" + "=" * 70)
    print("AVAILABLE JOBS (for approval)")
    print("=" * 70 + "\n")

    for i, job_eval in enumerate(digest.get("top_jobs", []), 1):
        score = job_eval.get("score", 0)
        job = job_eval.get("job", {})
        empresa = job.get("empresa", "")
        titulo = job.get("titulo", "")

        print(f"{i}. [{score}/100] {empresa} — {titulo}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Processes job approvals from the digest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/approval_handler.py --list
  python src/approval_handler.py --approve "1,3,5"
  python src/approval_handler.py --approve "1, 2"
        """,
    )

    parser.add_argument(
        "--approve",
        type=str,
        help='Comma-separated IDs of approved jobs (e.g., "1,3,5")',
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Lists available jobs for approval",
    )

    args = parser.parse_args()

    if args.list:
        list_digest()
    elif args.approve:
        success = process_approvals(args.approve)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
