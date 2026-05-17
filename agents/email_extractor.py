"""
email_extractor.py  —  Extracts recruiter contact email from job descriptions
Uses regex heuristics first, falls back to Claude if needed.
"""

import re
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

EMAIL_REGEX = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

CONTACT_KEYWORDS = [
    'contact', 'contato', 'reach', 'email', 'apply', 'candidat', 'recruiter',
    'hiring', 'hr', 'human resources', 'interview', 'application', 'submit',
    'send your', 'send us', 'apply to', 'apply via', 'apply by', 'send your application'
]


def extract_emails_from_text(text: str) -> list[str]:
    """Extracts all email addresses from text using regex."""
    if not text:
        return []
    return list(set(re.findall(EMAIL_REGEX, text)))


def is_contact_email(email: str, context: str) -> bool:
    """Returns True if the email looks like a recruiter contact rather than a generic address."""
    generic_prefixes = ['info@', 'support@', 'hello@', 'no-reply@', 'noreply@', 'no_reply@']

    email_lower = email.lower()

    for prefix in generic_prefixes:
        if email_lower.startswith(prefix):
            return False

    context_lower = context.lower()
    for keyword in CONTACT_KEYWORDS:
        if keyword in context_lower:
            return True

    return False


def extract_recruiter_email(job_description: str, empresa: str, titulo: str) -> str | None:
    """
    Extracts the recruiter contact email.
    Step 1: regex + heuristics.
    Step 2: Claude as fallback if emails found but none looks like a contact.
    """
    if not job_description:
        return None

    emails = extract_emails_from_text(job_description)

    for email in emails:
        if is_contact_email(email, job_description):
            return email

    if not emails:
        return None

    try:
        prompt = f"""Extract the recruiter/hiring contact email from this job description.
Return ONLY the email address, or "NONE" if not found.

COMPANY: {empresa}
JOB TITLE: {titulo}

JOB DESCRIPTION:
{job_description[:2000]}

Return format: email@example.com or NONE
"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )

        result = response.content[0].text.strip()

        if result.lower() != "none" and "@" in result:
            return result

    except Exception as e:
        print(f"  Warning: error extracting email with Claude: {e}")

    return None


if __name__ == "__main__":
    test_description = """
    Position: Data Analyst

    We're hiring! Please send your CV to: john.smith@company.com or apply via our portal.

    For questions, contact: hr@company.com

    Apply by sending your application to hiring@company.com
    """

    email = extract_recruiter_email(test_description, "Company XYZ", "Data Analyst")
    print(f"Found recruiter email: {email}")
