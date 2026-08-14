#!/usr/bin/env python3
"""
hotfix-run1.py  —  Fixes 4 bugs found in the first real pipeline run

Run:  python hotfix-run1.py
from inside the C:\tmp\job-hunt-pipeline-FIXED folder
"""

import os
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  Written: {path}")

# Repo directory
REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERROR: Run this script from inside the repo folder (job-hunt-pipeline-FIXED)")
    exit(1)

print("=" * 60)
print("  HOTFIX — First Run Bugs")
print("=" * 60)
print()

# ======================================================================
# BUG 1: email_ingestor.py — SYNTACTICALLY BROKEN
# ======================================================================
print("[1/4] email_ingestor.py — rewriting in full...")
write_file(f"{REPO}/src/email_ingestor.py", '''"""
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

PROCESSED_EMAILS_FILE = "digests/processed_email_ids.json"

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


def load_processed_ids() -> set:
    if os.path.exists(PROCESSED_EMAILS_FILE):
        try:
            with open(PROCESSED_EMAILS_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_processed_ids(ids: set):
    os.makedirs("digests", exist_ok=True)
    with open(PROCESSED_EMAILS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(ids), f)


def fetch_job_alert_emails(hours_back: int = 24, max_results: int = 50) -> list[dict]:
    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD:
        print("GMAIL_SENDER or GMAIL_APP_PASSWORD not set.")
        return []

    print(f"Connecting to Gmail IMAP as {GMAIL_SENDER}...")

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
    except Exception as e:
        print(f"IMAP login failed: {e}")
        return []

    processed_ids = load_processed_ids()
    emails = []

    try:
        mail.select("inbox")

        since_date = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime("%d-%b-%Y")

        all_message_ids = set()
        for sender in JOB_ALERT_SENDERS:
            _, data = mail.search(None, f\'(FROM "{sender}" SINCE "{since_date}")\')
            ids = data[0].split()
            all_message_ids.update(ids)

        if not all_message_ids:
            print(f"No alert emails found in the last {hours_back}h.")
            return []

        new_message_ids = [mid for mid in all_message_ids if mid.decode() not in processed_ids]
        if not new_message_ids:
            print(f"No new emails (all {len(all_message_ids)} already processed).")
            return []

        message_ids = new_message_ids[:max_results]
        skipped = len(new_message_ids) - len(message_ids)
        print(f"Found {len(message_ids)} new emails" + (f" ({skipped} skipped)" if skipped else ""))

        for i, msg_id in enumerate(message_ids):
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = decode_header_value(msg.get("Subject", ""))
                from_addr = decode_header_value(msg.get("From", ""))
                date_str = msg.get("Date", "")

                html_body, text_body = extract_body(msg)
                snippet = (text_body or html_body)[:200].replace("\\n", " ").strip()

                emails.append({
                    "id": msg_id.decode(),
                    "subject": subject,
                    "from": from_addr,
                    "date": date_str,
                    "snippet": snippet,
                    "html_body": html_body,
                    "text_body": text_body,
                })

                processed_ids.add(msg_id.decode())

                if (i + 1) % 10 == 0:
                    print(f"  {i + 1}/{len(message_ids)} emails processed...")

            except Exception as e:
                print(f"  Error processing email {msg_id}: {e}")
                continue

    finally:
        try:
            mail.logout()
        except Exception:
            pass

    save_processed_ids(processed_ids)
    print(f"Total: {len(emails)} new emails extracted.")
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

    print(f"\\n{len(emails)} emails saved to digests/")
''')

# ======================================================================
# BUG 2: unified_ingestor.py — NoneType.lower()
# ======================================================================
print("[2/4] unified_ingestor.py — fix NoneType in dedup...")
content = open(f"{REPO}/src/unified_ingestor.py", "r", encoding="utf-8").read()

# Fix 1: location can be None
content = content.replace(
    '''            job.get("location", job.get("localizacao", "")).lower().strip(),''',
    '''            (job.get("location") or job.get("localizacao") or "").lower().strip(),'''
)

# Fix 2: timezone.utc in normalize_to_legacy
content = content.replace(
    '''        "data_post": job.get("posted_at") or job.get("data_post", datetime.now().isoformat()),''',
    '''        "data_post": job.get("posted_at") or job.get("data_post", datetime.now(timezone.utc).isoformat()),'''
)

# Fix 3: add try/except around JSON loads
for old, new in [
    ('''    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"  ✅ JSearch: {len(jobs)} vagas de {latest}")
    return jobs''',
     '''    latest = files[-1]
    try:
        with open(latest, "r", encoding="utf-8") as f:
            jobs = json.load(f)
        print(f"  ✅ JSearch: {len(jobs)} jobs from {latest}")
        return jobs
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠️  Error loading {latest}: {e}")
        return []'''),
    ('''    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"  ✅ LinkedIn: {len(jobs)} vagas de {latest}")
    return jobs''',
     '''    latest = files[-1]
    try:
        with open(latest, "r", encoding="utf-8") as f:
            jobs = json.load(f)
        print(f"  ✅ LinkedIn: {len(jobs)} jobs from {latest}")
        return jobs
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠️  Error loading {latest}: {e}")
        return []'''),
    ('''    latest = files[-1]
    with open(latest, "r", encoding="utf-8") as f:
        jobs = json.load(f)
    print(f"  ✅ Adzuna: {len(jobs)} vagas de {latest}")
    return jobs''',
     '''    latest = files[-1]
    try:
        with open(latest, "r", encoding="utf-8") as f:
            jobs = json.load(f)
        print(f"  ✅ Adzuna: {len(jobs)} jobs from {latest}")
        return jobs
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠️  Error loading {latest}: {e}")
        return []'''),
]:
    content = content.replace(old, new)

write_file(f"{REPO}/src/unified_ingestor.py", content)

# ======================================================================
# BUG 3: kimi_client.py — call_kimi_json without retry for empty responses
# ======================================================================
print("[3/4] kimi_client.py — retry in call_kimi_json for empty responses...")
content = open(f"{REPO}/src/kimi_client.py", "r", encoding="utf-8").read()

old_call_kimi_json = '''def call_kimi_json(prompt, system=None, model=KIMI_MODEL_DEFAULT, temperature=0.1, max_tokens=4096):
    return json.loads(call_kimi(prompt, system, model, temperature, max_tokens, {"type":"json_object"}))'''

new_call_kimi_json = '''def call_kimi_json(prompt, system=None, model=KIMI_MODEL_DEFAULT, temperature=0.1, max_tokens=4096):
    """Calls Kimi with JSON response format, with retry for empty responses."""
    for attempt in range(3):
        raw = call_kimi(prompt, system, model, temperature, max_tokens, {"type":"json_object"})
        if raw and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                if attempt < 2:
                    print(f"  [Kimi] Invalid JSON, retrying ({attempt + 1}/3)...")
                    time.sleep(2 ** attempt)
                    continue
                raise
        if attempt < 2:
            print(f"  [Kimi] Empty response, retrying ({attempt + 1}/3)...")
            time.sleep(2 ** attempt)
    raise RuntimeError("Kimi returned empty response after 3 attempts")'''

content = content.replace(old_call_kimi_json, new_call_kimi_json)
write_file(f"{REPO}/src/kimi_client.py", content)

# ======================================================================
# BUG 4: email_notifier.py — validate digest has jobs and is from today
# ======================================================================
print("[4/4] email_notifier.py — validate content before sending...")
content = open(f"{REPO}/agents/email_notifier.py", "r", encoding="utf-8").read()

# Ensure the job validation is correct
old_section = '''    digest = load_digest()
    if not digest:
        print("❌ No digest to send")
        return False

    # Validate digest has actual jobs before sending
    top_jobs = digest.get("top_jobs", [])
    total_evaluated = digest.get("total_evaluated", 0)
    if not top_jobs or total_evaluated == 0:
        print("📭 No jobs in digest — skipping email notification")
        return False'''

# If the new section does not exist, add it
if "📭 No jobs in digest" not in content:
    content = content.replace(
        '''    digest = load_digest()
    if not digest:
        print("❌ No digest to send")
        return False''',
        '''    digest = load_digest()
    if not digest:
        print("❌ No digest to send")
        return False

    # Validate digest has actual jobs before sending
    top_jobs = digest.get("top_jobs", [])
    total_evaluated = digest.get("total_evaluated", 0)
    if not top_jobs or total_evaluated == 0:
        print("📭 No jobs in digest — skipping email notification")
        return False'''
    )

write_file(f"{REPO}/agents/email_notifier.py", content)

# ======================================================================
# COMMIT AND PUSH
# ======================================================================
print()
print("Committing hotfix...")
ok, out, err = run(f"cd {REPO} && git add -A && git diff --cached --stat")
if ok:
    print(f"  Modified files:\n{out}")

ok, out, err = run(f'cd {REPO} && git commit -m "hotfix: fixes 4 bugs from the first real run" -m "- email_ingestor.py: rewritten - SyntaxError in the IMAP try/finally" -m "- unified_ingestor.py: fix NoneType in dedup (location=None)" -m "- kimi_client.py: retry in call_kimi_json for empty responses" -m "- email_notifier.py: validates jobs before sending email"')
if ok:
    print(f"  ✅ Commit created")
else:
    print(f"  Commit error: {err[:200]}")

print()
print("=" * 60)
print("  HOTFIX APPLIED!")
print("=" * 60)
print()
print("To push to GitHub:")
print("   git push origin main")
print()
print("Then, in GitHub Actions, run the workflow again.")
print()
print("⚠️  Do not forget to add the Secrets on GitHub:")
print("   - ADZUNA_APP_ID  and  ADZUNA_APP_KEY  (for Adzuna jobs to work)")
print("   - GMAIL_RECIPIENT  (to know who to send the email to)")
print()
