"""
email_parser.py — Batch parsing: 5 emails por chamada Kimi
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json

SYSTEM_PROMPT = """You are a job extraction assistant. Extract job listings from job alert emails.
For each job: company, title, location, description (max 300 chars), url, source.
Respond ONLY with a valid JSON array of job objects.
If no jobs found, return []."""

def parse_batch(emails):
    if not emails:
        return []
    combined = ""
    for i, email in enumerate(emails[:5], 1):
        subject = email.get("subject", "No subject")
        from_addr = email.get("from", "Unknown")
        preview = email.get("snippet", "")
        body = (email.get("html_body", "") or email.get("text_body", ""))[:1500]
        combined += f"\n=== EMAIL {i} ===\nSubject: {subject}\nFrom: {from_addr}\nPreview: {preview}\nContent: {body}\n"

    prompt = f"Extract ALL job listings from these emails. For each: company, title, location, description, url, source.\n\n{combined}\n\nReturn JSON array of ALL jobs found."
    try:
        result = call_kimi_json(prompt, system=SYSTEM_PROMPT, max_tokens=4000)
        if isinstance(result, list):
            for job in result:
                job.setdefault("url", ""); job.setdefault("portal", job.get("source", "email"))
                job.setdefault("idioma", "en"); job.setdefault("data_post", datetime.now(timezone.utc).isoformat())
            return result
    except Exception as e:
        print(f"  Batch failed: {str(e)[:80]}")
    return []

def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/raw_emails_full.json", "r", encoding="utf-8") as f:
            emails = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No emails to parse."); return
    if not emails:
        print("No emails to parse."); return

    print(f"Parsing {len(emails)} emails in batch mode...\n")
    all_jobs = []
    chunk_size = 5
    for i in range(0, len(emails), chunk_size):
        chunk = emails[i:i + chunk_size]
        print(f"  Chunk {i//chunk_size + 1}/{(len(emails) + chunk_size - 1)//chunk_size}: {len(chunk)} emails...", end=" ", flush=True)
        jobs = parse_batch(chunk)
        all_jobs.extend(jobs); print(f"{len(jobs)} jobs")

    print(f"\nTotal: {len(all_jobs)} jobs from {len(emails)} emails")
    with open("digests/parsed_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
