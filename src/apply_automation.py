"""
apply_automation.py  —  Orchestrates the application workflow with Claude in Chrome
Flow: approval → guide → Claude in Chrome → tracker
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.form_fill_guide import (
    generate_form_fill_guide,
    generate_claude_in_chrome_prompt,
)
from agents.tracker_updater import record_application, update_application_status


def load_latest_approvals():
    """Loads the most recent approvals file."""
    approval_file = "digests/approvals_latest.json"
    if not os.path.exists(approval_file):
        print("❌ No approvals found.")
        print("Run first: python src/approval_handler.py --approve '...'")
        return None

    with open(approval_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_evaluations():
    """Loads job evaluations, indexed by company name."""
    eval_file = "digests/job_evaluations_latest.json"
    if not os.path.exists(eval_file):
        return {}

    with open(eval_file, "r", encoding="utf-8") as f:
        evals = json.load(f)
        return {e.get("job", {}).get("empresa", ""): e for e in evals}


def generate_apply_guides(approvals_data: dict) -> list:
    """Generates form-filling guides for all approved jobs."""
    approved_jobs = approvals_data.get("approved_jobs", [])
    evals = load_evaluations()

    guides = []
    os.makedirs("digests", exist_ok=True)

    print(f"\nGenerating guides for {len(approved_jobs)} job(s)...\n")

    for i, job in enumerate(approved_jobs, 1):
        empresa = job.get("empresa", "")
        titulo = job.get("titulo", "")
        url = job.get("url", "")

        print(f"[{i}] {empresa} — {titulo}")

        eval_data = evals.get(empresa, {})
        guide = generate_form_fill_guide(eval_data, job)
        guides.append(guide)

        safe_name = empresa.replace(" ", "_").replace("/", "-")
        guide_file = f"digests/form_guide_{safe_name}_{i}.json"
        with open(guide_file, "w", encoding="utf-8") as f:
            json.dump(guide, f, ensure_ascii=False, indent=2)

        print(f"   ✅ Guide saved: {guide_file}")

    return guides


def display_apply_instructions(guides: list):
    """Displays instructions for using Claude in Chrome to fill each form."""
    print("\n" + "=" * 70)
    print("HOW TO USE CLAUDE IN CHROME TO FILL APPLICATION FORMS")
    print("=" * 70)

    for i, guide in enumerate(guides, 1):
        print(f"\nJOB {i}: {guide['empresa']} — {guide['titulo']}")
        print("-" * 70)

        prompt = generate_claude_in_chrome_prompt(guide)

        print("\n📋 COPY THIS PROMPT AND PASTE INTO CLAUDE IN CHROME:")
        print("-" * 70)
        print(prompt)
        print("-" * 70)
        print(f"\n🔗 Job link: {guide['url']}")

        print("""
STEPS:
1. Open Claude in Chrome (shortcut: Alt+C in browser)
2. COPY the prompt above (all of it)
3. PASTE it into the Claude in Chrome chat
4. Claude will fill the form automatically
5. REVIEW all information
6. CLICK "Submit" when confirmed
7. Return to this terminal and press ENTER
        """)

        input("Press ENTER once you have completed the application: ")

        record_application(
            empresa=guide["empresa"],
            titulo=guide["titulo"],
            url=guide["url"],
        )

        update_application_status(
            empresa=guide["empresa"],
            titulo=guide["titulo"],
            status="submitted_via_chrome",
            notes=f"Filled with Claude in Chrome at {datetime.now().isoformat()}",
        )

        print(f"✅ Application recorded in tracker")

    print("\n" + "=" * 70)
    print("🎉 ALL APPLICATIONS COMPLETED!")
    print("=" * 70)
    print("Run 'python src/dashboard.py' to view the updated status")


def run_apply_workflow():
    """Runs the full application workflow."""
    print("\n" + "=" * 70)
    print("JOB HUNT — APPLY AUTOMATION")
    print("Claude in Chrome + Form Filling")
    print("=" * 70)

    approvals = load_latest_approvals()
    if not approvals:
        return False

    approved_count = len(approvals.get("approved_jobs", []))
    print(f"\n✅ Loaded {approved_count} approved job(s)")

    guides = generate_apply_guides(approvals)

    if not guides:
        print("❌ No guides were generated")
        return False

    display_apply_instructions(guides)

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Job Hunt — Apply Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/apply_automation.py        # Interactive workflow
  python src/apply_automation.py --list # List saved guides
        """,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="Lists the generated guides",
    )

    args = parser.parse_args()

    if args.list:
        guides_file = "digests/form_guides_latest.json"
        if os.path.exists(guides_file):
            with open(guides_file, "r") as f:
                guides = json.load(f)
            print(json.dumps(guides, indent=2, ensure_ascii=False))
        else:
            print("No guides found. Run: python src/apply_automation.py")
    else:
        success = run_apply_workflow()
        sys.exit(0 if success else 1)
