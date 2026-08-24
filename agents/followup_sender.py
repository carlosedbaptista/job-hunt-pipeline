"""
followup_sender.py  —  Drafts follow-up emails for stale applications
Targets applications > 7 days old with no response.

Does NOT email the recruiter. The draft is emailed to the candidate
(GMAIL_RECIPIENT) for review; the candidate forwards it themselves.
This keeps the step safe to run unsupervised in the daily pipeline
without breaking the "never submit without approval" rule -- the
approval is the act of forwarding.
"""

import os
import sys
import html as html_mod
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.followup_writer import generate_followup_email_package
from agents.tracker_updater import DB_PATH, init_applications_table
import sqlite3


def get_stale_applications(days_threshold: int = 7) -> list[dict]:
    """
    Returns applications that:
    1. Have received no response yet
    2. Were submitted more than days_threshold days ago
    3. Have never had a follow-up drafted, or the last draft was > 3 days ago

    A known recruiter email is NOT required: the draft goes to the
    candidate, who decides where and whether to forward it.
    """
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    cutoff_date = (datetime.now() - timedelta(days=days_threshold)).isoformat()
    cutoff_3_days = (datetime.now() - timedelta(days=3)).isoformat()

    query = """
    SELECT
        id,
        company,
        title,
        date_applied,
        recruiter_email,
        last_followup_date,
        followup_count
    FROM applications
    WHERE
        response_type IS NULL          -- no response yet
        AND status = 'sent'            -- never follow up a job merely recommended
        AND date_applied < ?           -- older than threshold
        AND (
            last_followup_date IS NULL  -- never drafted
            OR last_followup_date < ?   -- last draft > 3 days ago
        )
    ORDER BY date_applied ASC
    """

    try:
        apps = conn.execute(query, (cutoff_date, cutoff_3_days)).fetchall()
        return [dict(app) for app in apps]
    except Exception as e:
        print(f"ERROR: could not fetch applications: {e}")
        return []
    finally:
        conn.close()


def update_followup_status(app_id: int):
    """Marks that a draft was surfaced for this application, so it doesn't
    get re-drafted every single day."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """UPDATE applications
               SET last_followup_date = ?, followup_count = COALESCE(followup_count, 0) + 1
               WHERE id = ?""",
            (datetime.now().isoformat(), app_id),
        )
        conn.commit()
    except Exception as e:
        print(f"ERROR: could not update follow-up status: {e}")
    finally:
        conn.close()


def send_draft_to_candidate(
    company: str,
    title: str,
    days_elapsed: int,
    recruiter_email: str,
    subject: str,
    body: str,
    recipient_email: str,
    sender_email: str,
    app_password: str,
) -> bool:
    """Emails a follow-up draft to the candidate for review (not to the recruiter)."""
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)

        message = MIMEMultipart("alternative")
        message["Subject"] = f"[Draft] Follow-up ready: {title} at {company}"
        message["From"] = sender_email
        message["To"] = recipient_email

        recruiter_line = recruiter_email or "not recorded -- check the original job posting"
        intro = (
            "DRAFT FOLLOW-UP -- REVIEW BEFORE SENDING\n\n"
            "This is an auto-generated draft. Read it, edit it if needed, "
            "and forward it yourself to the recruiter.\n\n"
            f"Company: {company}\n"
            f"Role: {title}\n"
            f"Days since application: {days_elapsed}\n"
            f"Recruiter email on file: {recruiter_line}\n\n"
            "---\n\n"
            f"Suggested subject line:\n{subject}\n\n"
            f"Suggested body:\n{body}\n\n"
            "---\n"
        )

        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="white-space: pre-wrap;">{html_mod.escape(intro)}</div>
        </body>
        </html>
        """

        message.attach(MIMEText(intro, "plain"))
        message.attach(MIMEText(html_body, "html"))

        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()

        return True

    except Exception as e:
        print(f"ERROR: failed to send draft: {e}")
        return False


def _days_since(iso_timestamp) -> int:
    """Days between an ISO timestamp and now, in UTC.

    tracker_updater.record_application stores an AWARE timestamp
    (datetime.now(timezone.utc).isoformat()), and this used to subtract it
    from a naive datetime.now() -- TypeError on every eligible application.
    The step is continue-on-error, so the run stayed green and the follow-up
    feature silently never produced a single draft. Legacy rows written
    before that (naive) are treated as UTC. Returns None when unparseable."""
    try:
        parsed = datetime.fromisoformat(str(iso_timestamp))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).days


def draft_followups():
    """Drafts and emails (to the candidate) follow-up suggestions for all
    eligible stale applications."""
    print("\n" + "=" * 70)
    print("FOLLOW-UP DRAFTER")
    print("=" * 70 + "\n")

    sender_email = os.environ.get("GMAIL_SENDER", "")
    recipient_email = os.environ.get("GMAIL_RECIPIENT", sender_email)
    app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not app_password or not sender_email:
        print("WARNING: GMAIL_SENDER/GMAIL_APP_PASSWORD not set -- skipping.")
        return True

    stale_apps = get_stale_applications(days_threshold=7)

    if not stale_apps:
        print("OK: no eligible applications for follow-up.")
        return True

    print(f"Found {len(stale_apps)} eligible application(s):\n")

    drafted_count = 0

    for app in stale_apps:
        app_id = app["id"]
        company = app["company"]
        title = app["title"]
        recruiter_email = app.get("recruiter_email") or ""
        date_applied = app["date_applied"]

        days_elapsed = _days_since(date_applied)
        if days_elapsed is None:
            print(f"   WARNING: unparseable date_applied {date_applied!r} -- skipping\n")
            continue

        print(f"{drafted_count + 1}. {company} - {title} ({days_elapsed} days)")

        followup_package = generate_followup_email_package({
            "company": company,
            "title": title,
            "days_without_response": days_elapsed,
            "date_applied": date_applied,
        })

        if not followup_package:
            print("   ERROR: could not generate draft\n")
            continue

        success = send_draft_to_candidate(
            company=company,
            title=title,
            days_elapsed=days_elapsed,
            recruiter_email=recruiter_email,
            subject=followup_package["subject"],
            body=followup_package["body"],
            recipient_email=recipient_email,
            sender_email=sender_email,
            app_password=app_password,
        )

        if success:
            update_followup_status(app_id)
            print("   OK: draft sent for review\n")
            drafted_count += 1
        else:
            print("   ERROR: failed to send draft\n")

    print("=" * 70)
    print(f"OK: {drafted_count} draft(s) sent for review")
    print("=" * 70 + "\n")

    return True


if __name__ == "__main__":
    success = draft_followups()
    sys.exit(0 if success else 1)
