"""
email_ingestor.py  —  Fetches job alert emails from Gmail via IMAP (App Password)
"""

import email
import imaplib
import json
import os
from datetime import datetime, timedelta, timezone
from email.header import decode_header

from dotenv import load_dotenv

load_dotenv()

GMAIL_SENDER = os.environ.get("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

JOB_ALERT_SENDERS = [
    "jobs.ch",
    "jobup.ch",
    "linkedin.com",
    "indeed.com",
    "job-room.ch",
    "glassdoor.com",
    "xing.com",
    "swissdevjobs.ch",
]


def decode_header_value(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="ignore"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def extract_body(msg) -> tuple[str, str]:
    html_body = ""
    text_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html" and not html_body:
                payload = part.get_payload(decode=True)
                if payload:
                    html_body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
            elif content_type == "text/plain" and not text_body:
                payload = part.get_payload(decode=True)
                if payload:
                    text_body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            content_type = msg.get_content_type()
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="ignore")
            if content_type == "text/html":
                html_body = decoded
            else:
                text_body = decoded

    return html_body, text_body


def fetch_job_alert_emails(hours_back: int = 24, max_results: int = 50) -> list[dict]:
    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD:
        print("❌ GMAIL_SENDER or GMAIL_APP_PASSWORD not set in environment.")
        return []

    print(f"Connecting to Gmail IMAP as {GMAIL_SENDER}...")

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
    except Exception as e:
        print(f"❌ IMAP login failed: {e}")
        return []

    mail.select("inbox")

    since_date = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%d-%b-%Y")

    # Search for emails from any known job portal
    all_message_ids = set()
    for sender in JOB_ALERT_SENDERS:
        _, data = mail.search(None, f'(FROM "{sender}" SINCE "{since_date}")')
        ids = data[0].split()
        all_message_ids.update(ids)

    if not all_message_ids:
        print(f"No alert emails found in the last {hours_back}h.")
        mail.logout()
        return []

    # Limit results
    message_ids = list(all_message_ids)[:max_results]
    print(f"Found {len(message_ids)} emails. Extracting content...")

    emails = []
    for i, msg_id in enumerate(message_ids):
        try:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject = decode_header_value(msg.get("Subject", ""))
            from_addr = decode_header_value(msg.get("From", ""))
            date_str = msg.get("Date", "")
            snippet = ""

            html_body, text_body = extract_body(msg)
            snippet = (text_body or html_body)[:200].replace("\n", " ").strip()

            emails.append({
                "id": msg_id.decode(),
                "subject": subject,
                "from": from_addr,
                "date": date_str,
                "snippet": snippet,
                "html_body": html_body,
                "text_body": text_body,
            })

            if (i + 1) % 10 == 0:
                print(f"  {i + 1}/{len(message_ids)} emails processed...")

        except Exception as e:
            print(f"  ⚠️  Error processing email {msg_id}: {e}")
            continue

    mail.logout()
    print(f"Total: {len(emails)} emails extracted.")
    return emails


if __name__ == "__main__":
    os.makedirs("digests", exist_ok=True)

    emails = fetch_job_alert_emails(hours_back=24)

    preview = [
        {k: v for k, v in e.items() if k not in ("html_body", "text_body")}
        for e in emails
    ]
    with open("digests/raw_emails_latest.json", "w", encoding="utf-8") as f:
        json.dump(preview, f, ensure_ascii=False, indent=2)

    with open("digests/raw_emails_full.json", "w", encoding="utf-8") as f:
        json.dump(emails, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(emails)} emails saved to digests/")
