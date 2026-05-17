"""
email_notifier.py  —  Sends the daily digest by email via Gmail SMTP
"""

import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def load_digest():
    """Loads the latest digest file."""
    digest_file = "digests/digest_latest.json"
    if not os.path.exists(digest_file):
        print("❌ Digest not found.")
        return None

    with open(digest_file, "r", encoding="utf-8") as f:
        return json.load(f)


def format_digest_as_html(digest: dict) -> str:
    """Formats the digest as HTML for email delivery."""
    top_jobs = digest.get("top_jobs", [])
    total = digest.get("total_evaluated", 0)

    html = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background-color: #f5f5f5;
                margin: 0;
                padding: 20px;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: white;
                border-radius: 10px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            .header {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                text-align: center;
            }}
            .header h1 {{ margin: 0; font-size: 28px; }}
            .header p {{ margin: 10px 0 0 0; opacity: 0.9; font-size: 14px; }}
            .content {{ padding: 30px; }}
            .stats {{
                background-color: #f9f9f9;
                padding: 15px;
                border-radius: 8px;
                margin-bottom: 20px;
                text-align: center;
            }}
            .stats-number {{ font-size: 24px; font-weight: bold; color: #667eea; }}
            .job {{
                border-left: 4px solid #667eea;
                padding: 15px;
                margin-bottom: 15px;
                background-color: #fafafa;
                border-radius: 4px;
            }}
            .job-number {{ font-weight: bold; color: #667eea; margin-bottom: 8px; }}
            .job-company {{ font-weight: 600; font-size: 16px; color: #333; margin-bottom: 5px; }}
            .job-title {{ color: #666; margin-bottom: 5px; font-size: 14px; }}
            .job-location {{ color: #999; font-size: 13px; margin-bottom: 10px; }}
            .job-score {{
                display: inline-block;
                background-color: #667eea;
                color: white;
                padding: 4px 10px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }}
            .job-link {{
                display: inline-block;
                margin-top: 10px;
                color: #667eea;
                text-decoration: none;
                font-size: 13px;
            }}
            .footer {{
                background-color: #f9f9f9;
                padding: 20px;
                text-align: center;
                border-top: 1px solid #eee;
                font-size: 12px;
                color: #999;
            }}
            .cta-button {{
                display: inline-block;
                background-color: #667eea;
                color: white;
                padding: 12px 24px;
                border-radius: 6px;
                text-decoration: none;
                margin-top: 20px;
                font-weight: 600;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📊 Job Hunt Daily Digest</h1>
                <p>Your personalised job opportunities • {datetime.now().strftime('%B %d, %Y')}</p>
            </div>

            <div class="content">
                <div class="stats">
                    <div style="font-size: 14px; color: #666; margin-bottom: 5px;">Jobs evaluated today</div>
                    <div class="stats-number">{total}</div>
                </div>

                <h2 style="color: #333; margin-top: 0;">🎯 Top Jobs (Sorted by Fit Score)</h2>
    """

    for i, job_eval in enumerate(top_jobs, 1):
        score = job_eval.get("score", 0)
        job = job_eval.get("job", {})
        empresa = job.get("empresa", "N/A")
        titulo = job.get("titulo", "N/A")
        localizacao = job.get("localizacao", "N/A")
        url = job.get("url", "")
        portal = job.get("portal", "")

        color = "#32CD32" if score >= 65 else "#FFA500" if score >= 45 else "#999"

        html += f"""
                <div class="job">
                    <div class="job-number">#{i}</div>
                    <div class="job-company">{empresa}</div>
                    <div class="job-title">{titulo}</div>
                    <div class="job-location">📍 {localizacao} • 🏢 {portal}</div>
                    <div>
                        <span class="job-score" style="background-color: {color};">
                            {score}/100 Fit Score
                        </span>
                    </div>
        """

        if url:
            html += f'<a href="{url}" class="job-link">View job →</a>'

        html += """
                </div>
        """

    html += f"""
                <div style="margin-top: 30px; padding: 20px; background-color: #f0f4ff; border-radius: 8px; border-left: 4px solid #667eea;">
                    <h3 style="margin-top: 0; color: #667eea;">Next step?</h3>
                    <p style="margin: 10px 0; color: #555;">
                        Review the full digest and approve the jobs you want to apply to:
                    </p>
                    <a href="https://github.com/carlosedbaptista/job-hunt-pipeline" class="cta-button">
                        Open Dashboard →
                    </a>
                </div>
            </div>

            <div class="footer">
                <p style="margin: 0;">
                    Job Hunt Pipeline • Automated Notifications<br>
                    Generated at {datetime.now().strftime('%H:%M UTC')}
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    return html


def send_email(
    recipient_email: str,
    subject: str,
    html_content: str,
    sender_email: str,
    app_password: str,
) -> bool:
    """Sends an email via Gmail SMTP using an App Password."""
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = recipient_email

        # Plain text fallback
        text = f"Subject: {subject}\n\nView the HTML digest in your email client."

        html_part = MIMEText(html_content, "html")
        message.attach(html_part)

        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()

        return True

    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


def notify_digest():
    """Loads the latest digest and sends it by email."""
    print("\n" + "=" * 70)
    print("EMAIL NOTIFIER")
    print("=" * 70 + "\n")

    digest = load_digest()
    if not digest:
        print("❌ No digest to send")
        return False

    sender_email = os.environ.get("GMAIL_SENDER", "carlosedbaptista@gmail.com")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient_email = os.environ.get("GMAIL_RECIPIENT", "carlosedbaptista@gmail.com")

    if not app_password:
        print("⚠️  GMAIL_APP_PASSWORD not set")
        print("   Configure it in GitHub Secrets or your environment variables.")
        print("   Guide: https://support.google.com/accounts/answer/185833")
        return False

    print("Formatting digest as HTML...")
    html_content = format_digest_as_html(digest)

    subject = f"📊 Job Hunt Digest — {datetime.now().strftime('%B %d')}"

    print(f"Sending email to {recipient_email}...")

    success = send_email(
        recipient_email=recipient_email,
        subject=subject,
        html_content=html_content,
        sender_email=sender_email,
        app_password=app_password,
    )

    if success:
        print(f"✅ Email sent successfully!")
        print(f"   To: {recipient_email}")
        print(f"   Subject: {subject}")
        return True
    else:
        print("❌ Failed to send email")
        return False


if __name__ == "__main__":
    import sys

    success = notify_digest()
    sys.exit(0 if success else 1)
