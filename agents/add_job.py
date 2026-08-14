#!/usr/bin/env python3
"""
add_job.py -- Manually adds a job posting and evaluates the match right away.

Usage:
  python agents/add_job.py --url "https://empresa.com/vaga"
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

OUTPUT = os.path.join("digests", "manual_evaluations.json")


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

    return {"titulo": title, "empresa": "Unknown", "localizacao": "Unknown",
            "descricao": desc, "url": url, "portal": "manual"}


def save_evaluation(ev: dict):
    os.makedirs("digests", exist_ok=True)
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = []
    ev["evaluated_at"] = datetime.now(timezone.utc).isoformat()
    ev["source"] = "manual"
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
            print("Paste the job description text below (Ctrl+Z+Enter on Windows to finish):")
            text = sys.stdin.read()
            if not text.strip():
                print("No text provided. Aborting.")
                sys.exit(1)
            job = {"titulo": args.title or "Unknown", "empresa": args.company or "Unknown",
                   "localizacao": args.location or "Unknown", "descricao": text,
                   "url": args.url, "portal": "manual"}
    elif args.text or args.file:
        text = args.text or open(args.file, encoding="utf-8").read()
        job = {"titulo": args.title or "Unknown", "empresa": args.company or "Unknown",
               "localizacao": args.location or "Unknown", "descricao": text,
               "url": args.url or "", "portal": "manual"}
    else:
        print("Paste the job text below (Ctrl+Z+Enter on Windows to finish):")
        text = sys.stdin.read()
        if not text.strip():
            print("No text provided. Aborting.")
            sys.exit(1)
        job = {"titulo": args.title or "Unknown", "empresa": args.company or "Unknown",
               "localizacao": args.location or "Unknown", "descricao": text,
               "url": "", "portal": "manual"}

    if args.title:
        job["titulo"] = args.title
    if args.company:
        job["empresa"] = args.company

    print(f"\nEvaluating: {job['titulo'][:60]} @ {job['empresa']} ...")
    ev = evaluate_job(job)

    score = ev.get("score", 0)
    decision = ev.get("decision", "?")
    print("\n" + "=" * 60)
    print(f"SCORE: {score}/100  ->  {decision}  (APPLY >= 75)")
    print("=" * 60)
    print(f"Technical fit : {ev.get('technical_fit', '')}")
    print(f"Contextual fit: {ev.get('contextual_fit', '')}")
    print(f"Salary        : {ev.get('salary_estimate', '')}")
    print(f"Culture fit   : {ev.get('culture_fit', '')}")
    concerns = ev.get("concerns") or []
    if concerns:
        print(f"Concerns      : {', '.join(map(str, concerns))}")
    print(f"Comment       : {ev.get('portuguese_comment', '')}")

    save_evaluation(ev)
    print(f"\nSaved to {OUTPUT}")

    if decision == "APPLY" or score >= 75:
        print("\nHigh match! To generate tailored CV/CL, include this job in")
        print("digests/new_jobs_latest.json or run the normal pipeline.")


if __name__ == "__main__":
    main()
