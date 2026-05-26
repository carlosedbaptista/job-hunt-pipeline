"""
email_parser.py  —  Extracts job listings from job alert emails
Uses Claude Haiku to parse HTML from each portal.
"""

import json
import os
import re
# MIGRADO: usar from src.kimi_client import call_kimi
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

PORTAL_MAP = {
    "jobs.ch": "jobs.ch",
    "jobup.ch": "jobup.ch",
    "linkedin.com": "linkedin",
    "jobalert@linkedin": "linkedin",
    "indeed.com": "indeed",
    "job-room.ch": "job-room",
    "avam.admin.ch": "job-room",
    "glassdoor.com": "glassdoor",
    "xing.com": "xing",
    "swissdevjobs.ch": "swissdevjobs",
}

SYSTEM_PROMPT = """You are a precise job listing extractor. Your only job is to extract job listings from email alert content.

Return ONLY a valid JSON array. No preamble, no explanation, no markdown code fences.

Each job in the array must have exactly these fields:
{
  "empresa": "Company name as written",
  "titulo": "Job title exactly as listed",
  "url": "Direct URL to job posting, or null",
  "descricao": "1-2 sentence summary of the role, or null",
  "localizacao": "City or region, or null",
  "idioma": "Language of the posting: en, de, fr, or mixed",
  "data_post": "Date posted YYYY-MM-DD format, or null",
  "portal": "Source portal identifier"
}

If zero job listings are found, return: []
Never add fields beyond those listed above."""


def detect_portal(email_from: str) -> str:
    """Identifies the source portal from the email 'from' field."""
    from_lower = email_from.lower()
    for pattern, portal in PORTAL_MAP.items():
        if pattern in from_lower:
            return portal
    return "unknown"


def clean_json_response(raw: str) -> str:
    """Strips markdown fences if the model adds them."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def parse_email(email: dict) -> list[dict]:
    """
    Uses Claude Haiku to extract jobs from a single email.
    Returns a list of jobs in a standardised format.
    """
    portal = detect_portal(email["from"])

    # Prefer HTML (more structured), fall back to plain text
    body = email.get("html_body") or email.get("text_body") or ""

    # Truncate to fit context window
    MAX_BODY = 25_000
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n[content truncated]"

    if not body.strip():
        print(f"  Warning: email {email['id']} has no body, skipping.")
        return []

    user_prompt = f"""Portal: {portal}
Subject: {email.get('subject', '')}
From: {email.get('from', '')}
Date: {email.get('date', '')}

Email content:
{body}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text
        clean = clean_json_response(raw_text)
        jobs = json.loads(clean)

        for job in jobs:
            job["portal"] = portal
            job["source_email_id"] = email["id"]

        return jobs

    except json.JSONDecodeError as e:
        print(f"  ❌ Invalid JSON for email {email['id']}: {e}")
        print(f"     Raw response: {raw_text[:200]}")
        return []
    except Exception as e:
        print(f"  ❌ Error parsing email {email['id']}: {e}")
        return []


def parse_all_emails(emails: list[dict]) -> list[dict]:
    """Parses all emails and returns a consolidated list of jobs."""
    all_jobs = []
    total = len(emails)

    for i, email in enumerate(emails, 1):
        subject_preview = email.get("subject", "")[:55]
        print(f"[{i}/{total}] Parsing: {subject_preview}...")

        jobs = parse_email(email)
        print(f"        → {len(jobs)} job(s) extracted")
        all_jobs.extend(jobs)

    return all_jobs


if __name__ == "__main__":
    import sys

    input_file = "digests/raw_emails_full.json"

    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        print("Run first: python src/email_ingestor.py")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        emails = json.load(f)

    print(f"Parsing {len(emails)} emails...\n")
    jobs = parse_all_emails(emails)

    os.makedirs("digests", exist_ok=True)
    output = "digests/parsed_jobs_latest.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(jobs)} jobs extracted → {output}")

    if jobs:
        print("\nTop jobs:")
        for j in jobs[:5]:
            print(f"  • {j.get('empresa', 'N/A')} — {j.get('titulo', 'N/A')} ({j.get('localizacao', '?')})")
