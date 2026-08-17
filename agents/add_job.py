#!/usr/bin/env python3
"""
add_job.py -- Manually adds a job posting and evaluates the match right away.

Usage:
  python agents/add_job.py --url "https://company.com/job"
  python agents/add_job.py --text "job description..." --title "Data Engineer" --company "ACME"
  python agents/add_job.py --file job.txt
  python agents/add_job.py            # interactive mode (paste text)

Requires KIMI_API_KEY in the environment or in a .env file at the repo root.
Result: score/decision in the terminal + record in digests/manual_evaluations.json
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from job_evaluator import evaluate_job  # noqa: E402
from deduplicator import normalize, normalize_company  # noqa: E402

OUTPUT = os.path.join("digests", "manual_evaluations.json")


def _same_job(a: dict, b: dict) -> bool:
    """Same normalized company+title -- the same matching used for the
    dedup hash, so re-running "Add Job" for a posting you already
    evaluated is recognised as the same job even if the URL changed
    (LinkedIn issues a new tracking URL per visit)."""
    ja, jb = a.get("job", {}), b.get("job", {})
    return (
        normalize_company(ja.get("company", "")) == normalize_company(jb.get("company", ""))
        and normalize(ja.get("title", "")) == normalize(jb.get("title", ""))
    )


def fetch_job_from_url(url: str) -> dict:
    """Best effort: downloads the job page and extracts title/description.
    Many portals (LinkedIn, Indeed) block scraping -- in that case the
    script warns and asks you to paste the job text."""
    import re
    import requests
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()

    title = (soup.title.get_text(strip=True) if soup.title else "")[:150]
    meta = soup.find("meta", attrs={"property": "og:description"}) or soup.find("meta", attrs={"name": "description"})
    meta_desc = meta.get("content", "") if meta else ""

    body_text = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n", strip=True))
    # Heuristic: og:description is usually the summary; the body has the full description
    desc = body_text[:4000] if len(body_text) > len(meta_desc) else meta_desc

    if len(desc) < 200:
        raise RuntimeError("Page has insufficient content (likely an anti-bot block).")

    return {"title": title, "company": "Unknown", "location": "Unknown",
            "description": desc, "url": url, "portal": "manual"}


def save_evaluation(ev: dict):
    os.makedirs("digests", exist_ok=True)
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
    ev["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    ev["source"] = "manual"

    # Re-evaluating a job you already added replaces the old record
    # instead of piling up duplicates with different scores (e.g. after a
    # scoring calibration change) -- the old score/reasoning is gone once
    # replaced; this is intentional, the newest evaluation is the one that
    # should drive the dashboard/digest and any CV/CL decision.
    existing_idx = next((i for i, prior in enumerate(data) if _same_job(prior, ev)), None)
    if existing_idx is not None:
        old_score = data[existing_idx].get("score")
        print(f"Replacing previous evaluation for this job (was score={old_score}, now score={ev.get('score')}).")
        data[existing_idx] = ev
    else:
        data.append(ev)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Evaluates the match for a job right away.")
    parser.add_argument("--url", help="Job posting link (best effort; if blocked, use --text)")
    parser.add_argument("--text", help="Job text/description")
    parser.add_argument("--file", help=".txt file with the job description")
    parser.add_argument("--title", default="", help="Job title (optional with --text/--file)")
    parser.add_argument("--company", default="", help="Company (optional)")
    parser.add_argument("--location", default="", help="Location (optional)")
    args = parser.parse_args()

    if args.url:
        print(f"Fetching job from {args.url} ...")
        try:
            job = fetch_job_from_url(args.url)
        except Exception as e:
            print(f"Could not extract the job from the link ({e}).")
            if not sys.stdin.isatty():
                print("Non-interactive mode: rerun pasting the description text "
                      "(locally: --text/--file; in GitHub Actions: fill the 'text' input).")
                sys.exit(1)
            print("Paste the job description text below (Ctrl+Z+Enter on Windows to finish):")
            text = sys.stdin.read()
            if not text.strip():
                print("No text provided. Aborting.")
                sys.exit(1)
            job = {"title": args.title or "Unknown", "company": args.company or "Unknown",
                   "location": args.location or "Unknown", "description": text,
                   "url": args.url, "portal": "manual"}
    elif args.text or args.file:
        text = args.text or open(args.file, encoding="utf-8").read()
        job = {"title": args.title or "Unknown", "company": args.company or "Unknown",
               "location": args.location or "Unknown", "description": text,
               "url": args.url or "", "portal": "manual"}
    else:
        print("Paste the job text below (Ctrl+Z+Enter on Windows to finish):")
        text = sys.stdin.read()
        if not text.strip():
            print("No text provided. Aborting.")
            sys.exit(1)
        job = {"title": args.title or "Unknown", "company": args.company or "Unknown",
               "location": args.location or "Unknown", "description": text,
               "url": "", "portal": "manual"}

    if args.title:
        job["title"] = args.title
    if args.company:
        job["company"] = args.company

    print(f"\nEvaluating: {job['title'][:60]} @ {job['company']} ...")
    ev = evaluate_job(job)

    score = ev.get("score", 0)
    decision = ev.get("decision", "?")
    print("\n" + "=" * 60)
    print(f"SCORE: {score}/100  ->  {decision}  (APPLY >= 80)")
    print("=" * 60)
    print(f"Technical fit : {ev.get('technical_fit', '')}")
    print(f"Contextual fit: {ev.get('contextual_fit', '')}")
    print(f"Salary        : {ev.get('salary_estimate', '')}")
    print(f"Culture fit   : {ev.get('culture_fit', '')}")
    concerns = ev.get("concerns") or []
    if concerns:
        print(f"Concerns      : {', '.join(map(str, concerns))}")

    save_evaluation(ev)
    print(f"\nSaved to {OUTPUT}")

    if decision == "APPLY" or score >= 80:
        from doc_generator import generate_docs_for_job  # noqa: E402 (deferred: only needed here)
        from utils import load_json  # noqa: E402
        from kimi_client import KimiClient  # noqa: E402

        profile = load_json("config/candidate_profile.json")
        if not profile:
            print("\nHigh match, but config/candidate_profile.json is missing/invalid -- "
                  "skipping CV/CL generation (check the CANDIDATE_PROFILE_B64 secret).")
        else:
            print("\nHigh match! Generating tailored CV/CL...")
            client = KimiClient()
            generate_docs_for_job(client, profile, ev)


if __name__ == "__main__":
    main()
