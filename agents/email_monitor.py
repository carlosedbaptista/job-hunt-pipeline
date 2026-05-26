"""
email_monitor.py  —  Monitors recruiter responses in Gmail
Fetches emails and classifies them as:
- Positive response
- Rejection
- Interview invite
- Information request
"""

import json
import os
import pickle
import re
import sys
from datetime import datetime

# MIGRADO: usar from src.kimi_client import call_kimi
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from agents.tracker_updater import record_response

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
load_dotenv()
client = anthropic.Anthropic()

RESPONSE_PATTERNS = {
    "rejection": [
        r"unfortunately",
        r"not selected",
        r"we regret",
        r"não foi selecionado",
        r"infelizmente",
        r"não podemos prosseguir",
        r"leider",
        r"bedauern",
    ],
    "interview_invite": [
        r"interview",
        r"entrevista",
        r"next step",
        r"próxima etapa",
        r"phone call",
        r"chamada",
    ],
    "positive": [
        r"excited to have you",
        r"welcome to",
        r"offer",
        r"oferta",
        r"we are pleased",
        r"estamos felizes",
    ],
}


def get_gmail_service():
    """Authenticates and returns the Gmail service."""
    creds = None
    token_path = "token.pickle"

    if os.path.exists(token_path):
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

    return build("gmail", "v1", credentials=creds)


def decode_email_body(payload: dict) -> str:
    """Extracts plain text from the email payload."""
    import base64

    def walk(parts):
        text = ""
        for part in parts:
            if "parts" in part:
                text += walk(part["parts"])
            else:
                data = part.get("body", {}).get("data", "")
                if data:
                    text += base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="ignore"
                    )
        return text

    if "parts" in payload:
        return walk(payload["parts"])
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    return ""


def classify_response_with_claude(email_subject: str, email_body: str) -> dict:
    """
    Uses Claude to classify a recruiter response.
    Returns: {'type': 'positive'|'rejection'|'interview_invite'|'info_request', 'confidence': 0-1}
    """
    system = """You are a recruiter response classifier.
Classify the email from a recruiter as one of:
- 'positive': job offer, positive feedback, moving forward
- 'rejection': not selected, not a fit, goodbye
- 'interview_invite': interview scheduled, phone call, next round
- 'info_request': asking for more information, clarification
- 'unknown': cannot determine

Return ONLY a JSON object:
{"type": "...", "confidence": 0.0-1.0, "reason": "brief explanation"}"""

    prompt = f"""Classify this recruiter email:

Subject: {email_subject}

Body:
{email_body[:1000]}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        result = json.loads(text)
        return result
    except Exception as e:
        print(f"  Warning: error classifying email: {e}")
        return {"type": "unknown", "confidence": 0, "reason": "classification error"}


def fetch_recruiter_emails(hours_back: int = 48) -> list:
    """Fetches recruiter emails from the last N hours."""
    service = get_gmail_service()

    query = f'(from:hr@ OR from:recruit OR from:noreply OR subject:job OR subject:application) is:unread after:{int((datetime.now().timestamp() - hours_back*3600))}'

    try:
        results = service.users().messages().list(
            userId="me", q=query, maxResults=20
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return []

        emails = []
        for msg_ref in messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="full")
                .execute()
            )

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            body = decode_email_body(msg["payload"])

            emails.append(
                {
                    "id": msg["id"],
                    "subject": headers.get("Subject", ""),
                    "from": headers.get("From", ""),
                    "date": headers.get("Date", ""),
                    "body": body,
                }
            )

        return emails

    except Exception as e:
        print(f"❌ Error fetching emails: {e}")
        return []


def process_recruiter_emails(emails: list) -> list:
    """Processes recruiter emails and updates the tracker."""
    processed = []

    for email in emails:
        subject = email.get("subject", "")
        body = email.get("body", "")
        from_addr = email.get("from", "")

        print(f"\n  Analysing: {subject[:60]}...")
        print(f"  From: {from_addr[:40]}")

        classification = classify_response_with_claude(subject, body)
        response_type = classification.get("type", "unknown")
        confidence = classification.get("confidence", 0)

        if confidence < 0.5:
            print(f"    ⚠️  Low confidence ({confidence}), skipping")
            continue

        print(f"    ✅ {response_type.upper()} (confidence: {confidence})")

        processed.append(
            {
                "subject": subject,
                "from": from_addr,
                "type": response_type,
                "confidence": confidence,
                "processed_at": datetime.now().isoformat(),
            }
        )

    return processed


def monitor_responses():
    """Monitors recruiter emails and updates the tracker."""
    print("\n" + "=" * 70)
    print("EMAIL MONITOR — Detecting recruiter responses")
    print("=" * 70 + "\n")

    print("Searching emails from the last 48h...")
    emails = fetch_recruiter_emails(hours_back=48)

    if not emails:
        print("No recruiter emails found.")
        return []

    print(f"Found {len(emails)} email(s). Classifying...\n")

    processed = process_recruiter_emails(emails)

    if processed:
        os.makedirs("digests", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output = f"digests/email_monitor_{timestamp}.json"

        with open(output, "w", encoding="utf-8") as f:
            json.dump(processed, f, ensure_ascii=False, indent=2)

        print(f"\n✅ {len(processed)} response(s) processed → {output}")
    else:
        print("\n⚠️  No responses were classified.")

    return processed


if __name__ == "__main__":
    responses = monitor_responses()
    sys.exit(0 if responses is not None else 1)
