#!/usr/bin/env python3
"""
high_score_alert.py -- Send immediate email alert for jobs scoring >= 85.
Runs after job evaluation to catch top opportunities instantly.
Alerted jobs are recorded in digests/alerted_jobs.json so the same job
never triggers a second alert on later runs.
"""
import html as html_mod
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from utils import THRESHOLD_APPLY, has_hard_blocker
from deduplicator import make_hash

ALERTED_FILE = "digests/alerted_jobs.json"


def esc(value) -> str:
    return html_mod.escape(str(value), quote=True)


def safe_url(url) -> str:
    u = str(url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else ""


def load_alerted() -> set:
    if os.path.exists(ALERTED_FILE):
        try:
            with open(ALERTED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_alerted(hashes: set):
    os.makedirs("digests", exist_ok=True)
    with open(ALERTED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(hashes), f)


def get_job_field(job_eval, field, default="N/A"):
    job = job_eval.get("job")
    if job and isinstance(job, dict):
        val = job.get(field)
        if val:
            return val
        en_map = {"company": "company", "title": "title", "location": "location"}
        if field in en_map:
            val = job.get(en_map[field])
            if val:
                return val
    val = job_eval.get(field)
    if val:
        return val
    return default


def send_alert(job_eval):
    sender = os.environ.get("GMAIL_SENDER", "")
    recipient = os.environ.get("GMAIL_RECIPIENT", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    
    if not all([sender, recipient, app_password]):
        print("  [Alert] Gmail credentials not configured")
        return False
    
    company = esc(get_job_field(job_eval, "company"))
    title = esc(get_job_field(job_eval, "title"))
    location = esc(get_job_field(job_eval, "location"))
    url = safe_url(get_job_field(job_eval, "url", default=""))
    score = job_eval.get("score") or 0

    subject = f"HIGH SCORE ALERT: {get_job_field(job_eval, 'title')} at {get_job_field(job_eval, 'company')} -- {score}/100"
    
    html = f"""<html><head><meta charset="UTF-8"><style>
        body {{ font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .alert {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 30px; border-radius: 12px; text-align: center; }}
        .score {{ font-size: 48px; font-weight: 700; }}
        .details {{ background: #f9f9f9; padding: 20px; border-radius: 8px; margin-top: 20px; }}
        .btn {{ display: inline-block; background: #667eea; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin-top: 15px; }}
    </style></head><body>
        <div class="alert"><h1>HIGH SCORE JOB ALERT</h1><div class="score">{score}/100</div><p>Top match detected! Apply quickly.</p></div>
        <div class="details"><h2>{title}</h2><p><strong>Company:</strong> {company}</p><p><strong>Location:</strong> {location}</p><p><strong>Score:</strong> {score} (APPLY threshold: {THRESHOLD_APPLY})</p>{f'<a href="{esc(url)}" class="btn">View Job Posting</a>' if url else ""}</div>
        <p style="color:#999;font-size:12px;margin-top:20px;text-align:center;">Job Hunt Pipeline Alert | {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}</p>
    </body></html>"""
    
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, app_password)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient
        msg.attach(MIMEText(html, "html"))
        server.sendmail(sender, recipient, msg.as_string())
        server.quit()
        print(f"  [Alert] Sent high-score alert: {title} at {company} ({score})")
        return True
    except Exception as e:
        print(f"  [Alert] Failed to send: {e}")
        return False


def main():
    path = "digests/job_evaluations_latest.json"
    if not os.path.exists(path):
        print("  [Alert] No evaluations found")
        return
    
    with open(path, "r", encoding="utf-8") as f:
        evaluations = json.load(f)
    
    threshold = int(os.environ.get("HIGH_SCORE_THRESHOLD", "85"))
    # Hard-blocked jobs keep their (high) score but are capped at SKIP --
    # alerting them would be noise about roles the candidate is barred from.
    high_scores = [e for e in evaluations
                   if (e.get("score") or 0) >= threshold and not has_hard_blocker(e)]

    if not high_scores:
        print(f"  [Alert] No jobs >= {threshold} today")
        return

    alerted = load_alerted()
    new_alerts = []
    for ev in high_scores:
        h = make_hash(
            get_job_field(ev, "company", ""),
            get_job_field(ev, "title", ""),
            get_job_field(ev, "location", ""),
        )
        if h in alerted:
            print(f"  [Alert] Already alerted, skipping: {get_job_field(ev, 'title')}")
            continue
        new_alerts.append((h, ev))

    if not new_alerts:
        print(f"  [Alert] All {len(high_scores)} high-score job(s) were already alerted")
        return

    print(f"  [Alert] Found {len(new_alerts)} new job(s) with score >= {threshold}")
    for h, job in new_alerts:
        if send_alert(job):
            alerted.add(h)
    save_alerted(alerted)


if __name__ == "__main__":
    main()
