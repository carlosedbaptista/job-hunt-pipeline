"""
followup_writer.py  —  Generates personalised follow-up emails with Claude Sonnet
Used for applications with no response after 7+ days.
"""

import json
import os
import sys
sys.path.insert(0, "../src")
sys.path.insert(0, "./src")
from kimi_client import call_kimi
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

FOLLOWUP_SYSTEM_PROMPT = """You are writing a professional follow-up email for a job application.

GUIDELINES:
- Respectful and professional tone
- Brief (150-200 words max)
- Reference the original application
- Express continued interest
- Suggest next steps
- Do NOT be pushy or demanding

Language: English (C1 level)

Return ONLY the email body (no subject line, no greeting, no signature yet)."""


def generate_followup(
    empresa: str,
    titulo: str,
    days_elapsed: int,
    original_application_date: str,
) -> str | None:
    """Generates a personalised follow-up email body."""
    prompt = f"""Generate a professional follow-up email for this job application:

COMPANY: {empresa}
JOB TITLE: {titulo}
DAYS SINCE APPLICATION: {days_elapsed}
ORIGINAL APPLICATION DATE: {original_application_date}

The follow-up should:
1. Reference the original application
2. Reiterate interest in the position
3. Politely ask about the status
4. Offer to provide additional information
5. Suggest next steps

Keep it concise and professional."""

    try:
        return call_kimi(prompt, system=FOLLOWUP_SYSTEM_PROMPT, temperature=0.4, max_tokens=800).strip()

    except Exception as e:
        print(f"❌ Error generating follow-up: {e}")
        return None


def generate_followup_email_package(application: dict) -> dict | None:
    """
    Generates a complete follow-up package (subject + body).
    Expects a dict with application data from the database.
    """
    empresa = application.get("empresa", "Unknown")
    titulo = application.get("titulo", "Unknown")
    days_elapsed = application.get("days_without_response", 0)
    date_applied = application.get("date_applied", "Unknown")

    body = generate_followup(empresa, titulo, days_elapsed, date_applied)

    if not body:
        return None

    subject = f"Following up: {titulo} at {empresa}"

    return {
        "subject": subject,
        "body": body,
        "days_elapsed": days_elapsed,
        "empresa": empresa,
        "titulo": titulo,
    }


if __name__ == "__main__":
    test_app = {
        "empresa": "Sika AG",
        "titulo": "Data Analyst",
        "days_without_response": 10,
        "date_applied": "2026-05-07"
    }

    result = generate_followup_email_package(test_app)

    if result:
        print(f"Subject: {result['subject']}\n")
        print(f"Body:\n{result['body']}")
    else:
        print("❌ Error generating follow-up")
