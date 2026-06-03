#!/usr/bin/env python3
"""
=== PHASE 7: OPERATIONAL FEATURES ===
1. Local email parser (no API cost, faster)
2. High-score alert (>85) -- immediate email
3. Remove broken LinkedIn from workflow
"""
import os
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

def wf(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERROR: Run this script from the repo root directory"); exit(1)

print("=== PHASE 7: OPERATIONAL FEATURES ===\n")

# 1. Local email parser (regex + BeautifulSoup, no API)
wf(f"{REPO}/agents/email_parser_local.py", r'''#!/usr/bin/env python3
"""
email_parser_local.py -- Parse job alert emails using regex + BeautifulSoup.
No API calls. Faster and free.
"""
import json
import os
import re
from typing import List, Dict, Any

from bs4 import BeautifulSoup


def parse_html_emails(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract job listings from HTML email bodies using regex + BeautifulSoup."""
    jobs = []
    job_keywords = [
        "analyst", "analysten", "intern", "praktikum", "werkstudent",
        "engineer", "manager", "consultant", "specialist", "coordinator",
        "data", "business", "ai", "machine learning", "stagiaire",
    ]
    location_keywords = [
        "zurich", "zuerich", "zug", "basel", "bern", "geneva",
        "winterthur", "wallisellen", "schweiz", "switzerland",
    ]
    
    for email in emails:
        html = email.get("html_body", "")
        text = email.get("text_body", "")
        body = html or text
        if not body:
            continue
        
        soup = BeautifulSoup(body, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        
        job_blocks = []
        portal = email.get("from", "").split("@")[-1].split(">")[0].strip()
        
        # Pattern 1: Job title links
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            link_text = link.get_text(strip=True)
            
            if not link_text or len(link_text) < 5:
                continue
            
            title_lower = link_text.lower()
            if not any(kw in title_lower for kw in job_keywords):
                continue
            
            # Find nearby company and location
            parent = link.find_parent(["td", "div", "p", "li"])
            company = "Unknown"
            location = "Unknown"
            
            if parent:
                parent_text = parent.get_text(separator="\n", strip=True)
                lines = [l.strip() for l in parent_text.split("\n") if l.strip()]
                
                for line in lines:
                    if line != link_text and len(line) > 2 and len(line) < 100:
                        if company == "Unknown":
                            company = line
                        elif location == "Unknown":
                            if any(loc in line.lower() for loc in location_keywords):
                                location = line
            
            job_blocks.append({
                "title": link_text,
                "company": company if company != link_text else "Unknown",
                "location": location,
                "url": href,
                "portal": portal,
                "source_email": email.get("subject", ""),
            })
        
        # Pattern 2: Plain text fallback
        if not job_blocks and text:
            patterns = [
                r'([A-Za-z\s/\-]+(?:Analyst|Engineer|Intern|Manager|Consultant)[A-Za-z\s/\-]*)\s+(?:at|@|bei)\s+([A-Za-z0-9\s\-&.]+)',
            ]
            for pattern in patterns:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    title = match.group(1).strip()
                    company = match.group(2).strip()
                    if len(title) > 5:
                        job_blocks.append({
                            "title": title,
                            "company": company,
                            "location": "Unknown",
                            "url": "",
                            "portal": portal,
                            "source_email": email.get("subject", ""),
                        })
        
        jobs.extend(job_blocks)
    
    # Deduplicate
    seen = set()
    unique = []
    for job in jobs:
        key = (job["title"].lower().strip(), job["company"].lower().strip())
        if key not in seen:
            seen.add(key)
            unique.append(job)
    
    print(f"  Extracted {len(unique)} jobs from {len(emails)} emails (local parser)")
    return unique


def main():
    os.makedirs("digests", exist_ok=True)
    
    emails_path = "digests/raw_emails_full.json"
    if not os.path.exists(emails_path):
        print(f"  No emails to parse: {emails_path} not found")
        with open("digests/parsed_jobs_latest.json", "w") as f:
            json.dump([], f)
        return
    
    with open(emails_path, "r", encoding="utf-8") as f:
        emails = json.load(f)
    
    if not emails:
        print("  No emails to parse")
        with open("digests/parsed_jobs_latest.json", "w") as f:
            json.dump([], f)
        return
    
    jobs = parse_html_emails(emails)
    
    with open("digests/parsed_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    
    print(f"  Saved {len(jobs)} parsed jobs to digests/parsed_jobs_latest.json")


if __name__ == "__main__":
    main()
''')
print("[OK] agents/email_parser_local.py created (regex + BeautifulSoup, no API)")

# 2. High-score alert module
wf(f"{REPO}/agents/high_score_alert.py", r'''#!/usr/bin/env python3
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
''')
print("[OK] agents/high_score_alert.py created (triggers at score >= 85)")

# 3. Update workflow
WORKFLOW_PATH = f"{REPO}/.github/workflows/job-hunt-scheduler.yml"
if os.path.exists(WORKFLOW_PATH):
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    
    # Comment out LinkedIn
    content = content.replace(
        """      - name: Fetch LinkedIn jobs
        run: python agents/linkedin_ingestor.py
        continue-on-error: true

      - name: Fetch Gmail alerts""",
        """      # LinkedIn ingestion disabled -- consistently returns 0 jobs
      # - name: Fetch LinkedIn jobs
      #   run: python agents/linkedin_ingestor.py
      #   continue-on-error: true

      - name: Fetch Gmail alerts"""
    )
    
    # Replace Kimi email parser with local parser
    content = content.replace(
        """      - name: Parse job emails
        env:
          KIMI_API_KEY: ${{ secrets.KIMI_API_KEY }}
        run: python agents/email_parser.py
        continue-on-error: true""",
        """      - name: Parse job emails (local, no API)
        run: python agents/email_parser_local.py"""
    )
    
    # Add high-score alert step
    content = content.replace(
        """      - name: Send email notification
        if: always()""",
        """      - name: Send high-score alerts (>=85)
        if: always()
        env:
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          GMAIL_SENDER: ${{ secrets.GMAIL_SENDER }}
          GMAIL_RECIPIENT: ${{ secrets.GMAIL_RECIPIENT }}
          HIGH_SCORE_THRESHOLD: "85"
        run: python agents/high_score_alert.py
        continue-on-error: true

      - name: Send email notification
        if: always()"""
    )
    
    with open(WORKFLOW_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print("[OK] .github/workflows/job-hunt-scheduler.yml -> local parser + high-score alert + LinkedIn removed")

# 4. Commit
run("git add -A")
ok, _, err = run('git commit -m "feat: local email parser, high-score alert (>=85), remove broken LinkedIn"')
if ok:
    print("\n[OK] Commit successful! Next: git push origin main")
else:
    print(f"\n[!] Commit issue: {err[:200]}")

print("\n=== PHASE 7 COMPLETE ===")
print("New features:")
print("  - agents/email_parser_local.py -- regex + BeautifulSoup, zero API cost")
print("  - agents/high_score_alert.py -- immediate email for jobs scoring >= 85")
print("  - Workflow: local parser, high-score alert step, LinkedIn removed")
print("Benefits:")
print("  - Faster: no API call for email parsing")
print("  - Cheaper: zero Kimi API credits for email parsing")
print("  - Better: instant alert for top-scoring jobs")
