#!/usr/bin/env python3
"""
high_score_alert.py -- Send immediate email alert for jobs scoring >= 85.
Runs after job evaluation to catch top opportunities instantly.
"""
import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def get_job_field(job_eval, field, default="N/A"):
    job = job_eval.get("job")
    if job and isinstance(job, dict):
        val = job.get(field)
        if val:
            return val
        en_map = {"empresa": "company", "titulo": "title", "localizacao": "location"}
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
    
    company = get_job_field(job_eval, "empresa")
    title = get_job_field(job_eval, "titulo")
    location = get_job_field(job_eval, "localizacao")
    url = get_job_field(job_eval, "url")
    score = job_eval.get("score", 0)
    
    subject = f"HIGH SCORE ALERT: {title} at {company} -- {score}/100"
    
    html = f"""<html><head><meta charset="UTF-8"><style>
        body {{ font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .alert {{ background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 30px; border-radius: 12px; text-align: center; }}
        .score {{ font-size: 48px; font-weight: 700; }}
        .details {{ background: #f9f9f9; padding: 20px; border-radius: 8px; margin-top: 20px; }}
        .btn {{ display: inline-block; background: #667eea; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; margin-top: 15px; }}
    </style></head><body>
        <div class="alert"><h1>HIGH SCORE JOB ALERT</h1><div class="score">{score}/100</div><p>Top match detected! Apply quickly.</p></div>
        <div class="details"><h2>{title}</h2><p><strong>Company:</strong> {company}</p><p><strong>Location:</strong> {location}</p><p><strong>Score:</strong> {score} (APPLY threshold: 65)</p>{f'<a href="{url}" class="btn">View Job Posting</a>' if url and url != "N/A" else ""}</div>
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
    high_scores = [e for e in evaluations if e.get("score", 0) >= threshold]
    
    if not high_scores:
        print(f"  [Alert] No jobs >= {threshold} today")
        return
    
    print(f"  [Alert] Found {len(high_scores)} job(s) with score >= {threshold}")
    for job in high_scores:
        send_alert(job)


if __name__ == "__main__":
    main()
