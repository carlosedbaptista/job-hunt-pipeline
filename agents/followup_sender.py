"""
followup_sender.py  —  Sends follow-up emails for stale applications
Targets applications > 7 days old with no response and a known recruiter email.
"""

import sqlite3
import os
import sys
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.followup_writer import generate_followup_email_package

DB_PATH = "tracker/jobs.db"


def get_old_applications(days_threshold: int = 7) -> list[dict]:
    """
    Returns applications that:
    1. Have received no response yet
    2. Were submitted more than days_threshold days ago
    3. Have a known recruiter email
    4. Have never had a follow-up, or the last attempt was > 3 days ago
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).isoformat()
    cutoff_3_days = (datetime.now() - timedelta(days=3)).isoformat()

    query = """
    SELECT
        id,
        empresa,
        titulo,
        date_applied,
        recruiter_email,
        last_followup_date,
        followup_count
    FROM applications
    WHERE
        response_type IS NULL          -- no response yet
        AND date_applied < ?           -- older than threshold
        AND recruiter_email IS NOT NULL
        AND recruiter_email != ''
        AND (
            last_followup_date IS NULL  -- never followed up
            OR last_followup_date < ?   -- last attempt > 3 days ago
        )
    ORDER BY date_applied ASC
    """

    try:
        apps = conn.execute(query, (cutoff_date, cutoff_3_days)).fetchall()
        conn.close()
        return [dict(app) for app in apps]
    except Exception as e:
        print(f"❌ Error fetching applications: {e}")
        conn.close()
        return []


def update_followup_status(app_id: int, success: bool = True):
    """Updates the tracker with follow-up information."""
    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute("""
            UPDATE applications
            SET
                last_followup_date = ?,
                followup_count = COALESCE(followup_count, 0) + 1
            WHERE id = ?
        """, (datetime.now().isoformat(), app_id))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error updating follow-up: {e}")
        conn.close()
        return False


def send_followup_email(
    to_email: str,
    subject: str,
    body: str,
    sender_email: str,
    app_password: str,
) -> bool:
    """Sends a follow-up email via Gmail SMTP."""
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)

        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = to_email

        full_body = f"""{body}

---
Best regards,
Carlos Eduardo Duarte Baptista
+41 78 261 34 74
carlosedbaptista@gmail.com
linkedin.com/in/carlosedbaptista

Swiss Work Permit B | Wallisellen, Zurich
"""

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="white-space: pre-wrap;">{full_body}</div>
        </body>
        </html>
        """

        message.attach(MIMEText(full_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        server.sendmail(sender_email, to_email, message.as_string())
        server.quit()

        return True

    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


def send_followups():
    """Sends follow-up emails for all eligible applications."""
    print("\n" + "=" * 70)
    print("FOLLOW-UP SENDER")
    print("=" * 70 + "\n")

    sender_email = os.environ.get("GMAIL_SENDER", "carlosedbaptista@gmail.com")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not app_password:
        print("⚠️  GMAIL_APP_PASSWORD not set")
        return False

    old_apps = get_old_applications(days_threshold=7)

    if not old_apps:
        print("✅ No eligible applications for follow-up")
        return True

    print(f"📧 Found {len(old_apps)} eligible application(s):\n")

    sent_count = 0

    for app in old_apps:
        app_id = app["id"]
        empresa = app["empresa"]
        titulo = app["titulo"]
        recruiter_email = app["recruiter_email"]
        date_applied = app["date_applied"]

        app_date = datetime.fromisoformat(date_applied)
        days_elapsed = (datetime.now() - app_date).days

        print(f"{sent_count + 1}. {empresa} — {titulo}")
        print(f"   Email: {recruiter_email}")
        print(f"   Days without response: {days_elapsed}")

        followup_package = generate_followup_email_package({
            "empresa": empresa,
            "titulo": titulo,
            "days_without_response": days_elapsed,
            "date_applied": date_applied,
        })

        if not followup_package:
            print(f"   ❌ Error generating follow-up\n")
            continue

        success = send_followup_email(
            to_email=recruiter_email,
            subject=followup_package["subject"],
            body=followup_package["body"],
            sender_email=sender_email,
            app_password=app_password,
        )

        if success:
            update_followup_status(app_id)
            print(f"   ✅ Follow-up sent\n")
            sent_count += 1
        else:
            print(f"   ❌ Failed to send email\n")

    print("=" * 70)
    print(f"✅ {sent_count} follow-up(s) sent")
    print("=" * 70 + "\n")

    return True


if __name__ == "__main__":
    success = send_followups()
    sys.exit(0 if success else 1)
