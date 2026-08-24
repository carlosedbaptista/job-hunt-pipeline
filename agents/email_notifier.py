"""
email_notifier.py  --  Sends the daily digest by email via Gmail SMTP
"""
import html
import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from utils import THRESHOLD_APPLY, THRESHOLD_REVIEW, effective_decision


def esc(value) -> str:
    """HTML-escapes a field before interpolation. Job titles/companies come
    from third-party emails and APIs -- never trust them in HTML."""
    return html.escape(str(value), quote=True)


def safe_url(url) -> str:
    """Returns the URL only if it uses http(s); blocks javascript: and data:."""
    u = str(url or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else ""


MAX_DIGEST_AGE_HOURS = int(os.environ.get("MAX_DIGEST_AGE_HOURS", "18"))
# Gmail rejects messages over ~25 MB, and a wall of attachments is its own
# kind of noise. Two PDFs per job, so this is six jobs' worth.
MAX_ATTACHMENTS = int(os.environ.get("MAX_DIGEST_ATTACHMENTS", "12"))
# Mirrors doc_generator.DELIVER_FORMATS: what reaches the inbox, as opposed
# to what was generated. Default .docx -- the editable copy.
DELIVER_FORMATS = tuple(
    f.strip().lower() for f in os.environ.get("DELIVER_FORMATS", ".docx").split(",")
    if f.strip())


def load_digest():
    digest_file = "digests/digest_latest.json"
    if not os.path.exists(digest_file):
        print("X Digest not found.")
        return None
    try:
        with open(digest_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError) as e:
        print(f"X Digest unreadable ({type(e).__name__}: {e})")
        return None


def _age_hours(stamp):
    """Hours since an ISO timestamp, or None if it is missing or unparseable.
    Handles both naive and tz-aware stamps: subtracting one from the other
    raises TypeError, which is exactly how the follow-up sender used to break."""
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return (datetime.now() - parsed).total_seconds() / 3600
    return (datetime.now(parsed.tzinfo) - parsed).total_seconds() / 3600


def digest_age_hours(digest):
    """Hours since the digest was generated, or None if it does not say."""
    return _age_hours((digest or {}).get("generated_at"))


def _get_field(job_eval, field, default="N/A"):
    """Extracts a field from the evaluation -- supports nested OR direct."""
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
    en_map = {"company": "company", "title": "title", "location": "location"}
    if field in en_map:
        val = job_eval.get(en_map[field])
        if val:
            return val
    return default


DOCS_MANIFEST = os.path.join("digests", "generated_docs_latest.json")


def load_generated_docs():
    """Documents agents/doc_generator.py produced in THIS run.

    Returns [] rather than raising when there is nothing: no APPLY job is the
    normal case, and the digest must go out regardless.

    The freshness check is the same guard the digest itself gets. The manifest
    is a committed file, so a run where doc generation is skipped (it is
    continue-on-error) would otherwise re-announce yesterday's documents and
    attach files that no longer exist on this runner.
    """
    try:
        with open(DOCS_MANIFEST, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    age = _age_hours(data.get("generated_at"))
    if age is None or age > MAX_DIGEST_AGE_HOURS:
        return []
    fresh = []
    for doc in data.get("documents") or []:
        # Only announce files that are actually here. A missing PDF would
        # promise the candidate an attachment that never arrives.
        files = [f for f in (doc.get("files") or []) if os.path.isfile(f)]
        if files:
            fresh.append({**doc, "files": files})
    return fresh


DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://carlosedbaptista.github.io/job-hunt-pipeline/")


def load_ingestion_stats():
    """Where postings stopped on their way to the scorer (written by
    unified_ingestor). Missing on old runs -- the heartbeat degrades to
    question marks, which is fine."""
    try:
        with open("digests/ingestion_stats_latest.json", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def format_heartbeat_html(digest, stats):
    """Quiet-day heartbeat: proof-of-life with the day's funnel, so a
    MISSING email can only ever mean the pipeline is down."""
    def row(label, value):
        return (f'<tr><td style="padding:6px 14px 6px 0;color:#666">{esc(label)}</td>'
                f'<td style="padding:6px 0;font-weight:600">{esc(value)}</td></tr>')

    rows = "".join([
        row("Postings ingested", stats.get("total_ingested", "?")),
        row("Already seen (dedup)", stats.get("already_seen", "?")),
        row("Dropped off-target", stats.get("dropped_off_target", "?")),
        row("Deferred by cost cap (back next run)", stats.get("deferred_by_cap", "?")),
        row("Sent to the scorer", stats.get("sent_to_evaluator", "?")),
        row("Skipped -- no posting text", digest.get("not_evaluated_no_text", 0)),
        row("API errors", digest.get("evaluation_errors", 0)),
    ])

    return f"""<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;margin:0;padding:20px">
  <div style="max-width:560px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
    <div style="background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:24px 28px">
      <h1 style="margin:0;font-size:20px">Job Hunt -- quiet day</h1>
      <p style="margin:6px 0 0;opacity:.9;font-size:14px">No new jobs scored today. That's the market, not a failure.</p>
    </div>
    <div style="padding:20px 28px">
      <table style="border-collapse:collapse;font-size:14px">{rows}</table>
      <p style="font-size:13px;color:#666;margin:18px 0 0">
        Dashboard: <a href="{esc(DASHBOARD_URL)}">{esc(DASHBOARD_URL)}</a>
      </p>
      <p style="font-size:13px;color:#999;margin:14px 0 0;border-top:1px solid #eee;padding-top:14px">
        This heartbeat exists so that a MISSING email always means the pipeline
        is down. If you ever don't receive this, check the Actions tab.
      </p>
    </div>
  </div>
</body></html>"""


def send_quiet_day_heartbeat(digest):
    """Sends the quiet-day heartbeat. Returns True on success (a send failure
    here is a real failure and must mark the step red)."""
    sender_email = os.environ.get("GMAIL_SENDER", "")
    recipient_email = os.environ.get("GMAIL_RECIPIENT", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not all([sender_email, recipient_email, app_password]):
        print("Gmail credentials not configured -- heartbeat not sent")
        return False

    stats = load_ingestion_stats()
    subject = f"Job Hunt -- quiet day (system OK), {datetime.now().strftime('%B %d')}"
    print("Quiet day: sending heartbeat email...")
    success = send_email(recipient_email, subject, format_heartbeat_html(digest, stats),
                         sender_email, app_password)
    print("OK Heartbeat sent" if success else "X Heartbeat failed to send")
    return success


def format_digest_as_html(digest):
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
                <h1>Job Hunt Daily Digest</h1>
                <p>Your personalised job opportunities - {esc(str(digest.get('generated_at') or '')[:10] or datetime.now().strftime('%Y-%m-%d'))}</p>
            </div>

            <div class="content">
                <div class="stats">
                    <div style="font-size: 14px; color: #666; margin-bottom: 5px;">Jobs evaluated today</div>
                    <div class="stats-number">{total}</div>
                </div>

                <h2 style="color: #333; margin-top: 0;">Top Jobs (Sorted by Fit Score)</h2>
    """

    for i, job_eval in enumerate(top_jobs, 1):
        score = job_eval.get("score") or 0
        company = esc(_get_field(job_eval, "company"))
        title = esc(_get_field(job_eval, "title"))
        location = esc(_get_field(job_eval, "location"))
        url = safe_url(_get_field(job_eval, "url", default=""))
        portal = esc(_get_field(job_eval, "portal"))

        # Colour and label come from the DERIVED decision, never from the
        # raw score: digest_generator ranks every scored record, including
        # hard-blocked and REVIEW-capped ones. A blind 85 (insufficient_info,
        # capped at REVIEW) used to arrive as a green APPLY-coloured top
        # pick, while the .txt digest and the dashboard called the same job
        # REVIEW -- three views of one job, disagreeing.
        decision = effective_decision(job_eval)
        color = {"APPLY": "#32CD32", "REVIEW": "#FFA500"}.get(decision, "#999")

        html += f"""
                <div class="job">
                    <div class="job-number">#{i}</div>
                    <div class="job-company">{company}</div>
                    <div class="job-title">{title}</div>
                    <div class="job-location">{location} - {portal}</div>
                    <div>
                        <span class="job-score" style="background-color: {color};">
                            {score}/100 - {esc(decision)}
                        </span>
                    </div>
        """
        if url:
            html += f'<a href="{esc(url)}" class="job-link">View job -&gt;</a>'
        html += "</div>"

    blind = digest.get("scored_title_only", 0)
    if blind:
        html += f"""
                <div style="margin-top: 20px; padding: 12px; background-color: #f5f5f5; border-radius: 8px; border-left: 4px solid #999;">
                    <strong>{blind} job(s) had no posting text</strong> and were scored on the
                    title alone, so they are capped at REVIEW.
                </div>
        """

    errors = digest.get("evaluation_errors", 0)
    if errors:
        html += f"""
                <div style="margin-top: 20px; padding: 15px; background-color: #fff3e0; border-radius: 8px; border-left: 4px solid #FFA500;">
                    <strong>{errors} job(s) could not be evaluated</strong> due to API errors
                    (check Kimi credits and digests/evaluation_errors.txt).
                </div>
        """

    # Documents generated by this same run, announced where the candidate
    # already looks once a day. One e-mail beats a second thread per APPLY job.
    docs = load_generated_docs()
    if docs:
        rows = "".join(
            f'<li style="margin: 6px 0; color: #555;">'
            f'<b>{esc(d.get("title"))}</b> at {esc(d.get("company"))}'
            + (f' <span style="color:#888;">(match {esc(d.get("score"))})</span>'
               if d.get("score") is not None else "")
            + (f'<br><a href="{safe_url(d["link"])}">Download CV and cover letter</a>'
               if d.get("link") else
               f'<br><span style="color:#888;">CV and cover letter attached to this e-mail'
               f' ({len(d.get("files") or [])} files)</span>')
            + "</li>"
            for d in docs
        )
        html += f"""
                <div style="margin-top: 30px; padding: 20px; background-color: #fff8e6; border-radius: 8px; border-left: 4px solid #f0a020;">
                    <h3 style="margin-top: 0; color: #b3701a;">Application materials ready</h3>
                    <p style="margin: 10px 0; color: #555;">
                        Tailored documents were generated for the job{'s' if len(docs) > 1 else ''} below.
                        Nothing has been sent to any employer.
                    </p>
                    <ul style="margin: 10px 0 0 0; padding-left: 20px;">{rows}</ul>
                </div>
        """

    html += f"""
                <div style="margin-top: 30px; padding: 20px; background-color: #f0f4ff; border-radius: 8px; border-left: 4px solid #667eea;">
                    <h3 style="margin-top: 0; color: #667eea;">Next step?</h3>
                    <p style="margin: 10px 0; color: #555;">
                        Review the full digest and approve the jobs you want to apply to:
                    </p>
                    <a href="https://carlosedbaptista.github.io/job-hunt-pipeline/digests/dashboard.html" class="cta-button">
                        Open Dashboard -&gt;
                    </a>
                </div>
            </div>

            <div class="footer">
                <p style="margin: 0;">
                    Job Hunt Pipeline - Automated Notifications<br>
                    Generated at {datetime.now().strftime('%H:%M UTC')}
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_email(recipient_email, subject, html_content, sender_email, app_password,
               attachments=None):
    """Sends the message, optionally with files attached.

    `attachments` is a list of local paths. It exists so the generated CV/CL
    can reach the candidate: this repo is public, so the PDFs can never be
    committed or uploaded as an Actions artifact, and the Google Drive path
    fails until GDRIVE_REFRESH_TOKEN_B64 is set. Mail to GMAIL_RECIPIENT is
    the one durable copy that leaks nothing -- and it only ever goes to the
    candidate, never to a recruiter.
    """
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)
        # "alternative" means "the same content in different formats", which
        # is wrong once a PDF is attached: some clients would hide the body.
        if attachments:
            message = MIMEMultipart("mixed")
            body = MIMEMultipart("alternative")
            body.attach(MIMEText(html_content, "html"))
            message.attach(body)
        else:
            message = MIMEMultipart("alternative")
            message.attach(MIMEText(html_content, "html"))
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = recipient_email
        for path in attachments or []:
            if not os.path.isfile(path):
                print(f"  ! Attachment missing, skipped: {path}")
                continue
            with open(path, "rb") as fh:
                part = MIMEApplication(fh.read(), Name=os.path.basename(path))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
            message.attach(part)
        server.sendmail(sender_email, recipient_email, message.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"X Failed to send email: {e}")
        return False


def notify_digest():
    print("\n" + "=" * 70)
    print("EMAIL NOTIFIER")
    print("=" * 70 + "\n")

    digest = load_digest()
    if not digest:
        print("X No digest to send")
        return False

    age = digest_age_hours(digest)
    if age is not None and age > MAX_DIGEST_AGE_HOURS:
        # The workflow runs this step with `if: always()`, so when the
        # evaluator exits 1 (no Kimi credits) the digest step is skipped and
        # this would happily re-send the PREVIOUS run's top 5 stamped with
        # today's date. Refuse instead of lying.
        print(f"X Digest is {age:.1f}h old (limit {MAX_DIGEST_AGE_HOURS}h) -- "
              f"an earlier step must have failed. Refusing to re-send a stale digest.")
        return False

    top_jobs = digest.get("top_jobs", [])
    total_evaluated = digest.get("total_evaluated", 0)
    if not top_jobs or total_evaluated == 0:
        # A quiet day used to skip the send entirely -- but then a missing
        # email was indistinguishable from a dead pipeline (2026-08-24: the
        # owner asked "what broke?" on a perfectly healthy run). Send the
        # heartbeat instead; silence must only ever mean failure.
        return send_quiet_day_heartbeat(digest)

    sender_email = os.environ.get("GMAIL_SENDER", "")
    recipient_email = os.environ.get("GMAIL_RECIPIENT", "")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender_email or not recipient_email:
        print("GMAIL_SENDER and/or GMAIL_RECIPIENT not set")
        return False
    if not app_password:
        print("GMAIL_APP_PASSWORD not set")
        return False

    print("Formatting digest as HTML...")
    html_content = format_digest_as_html(digest)

    # Carry this run's CV/CL on the digest itself. The repo is public, so the
    # PDFs can go neither into git nor into an Actions artifact, and Drive is
    # unconfigured -- the attachment is the only private channel there is. A
    # `link` on the manifest entry (Drive, once OAuth2 is set up) takes over:
    # the HTML then shows a download link and nothing is attached.
    docs = load_generated_docs()
    # Only the formats the candidate asked to receive. The manifest lists
    # everything that was generated (PDF and .docx); the PDF is the copy an
    # employer gets and lives in Drive, while the one worth putting in his
    # inbox is the one he can correct.
    attachments = [f for d in docs if not d.get("link") for f in d["files"]
                   if f.lower().endswith(DELIVER_FORMATS)]
    if len(attachments) > MAX_ATTACHMENTS:
        print(f"  {len(attachments)} files generated, attaching the first "
              f"{MAX_ATTACHMENTS} (the rest stay in generated_docs/ on the runner)")
        attachments = attachments[:MAX_ATTACHMENTS]

    subject = f"Job Hunt Digest - {datetime.now().strftime('%B %d')}"
    print(f"Sending email to {recipient_email}...")
    if attachments:
        print(f"   with {len(attachments)} document(s) attached")
    success = send_email(recipient_email, subject, html_content, sender_email, app_password,
                         attachments=attachments)

    if success:
        print(f"OK Email sent successfully!")
        print(f"   To: {recipient_email}")
        print(f"   Subject: {subject}")
        return True
    else:
        print("X Failed to send email")
        return False


if __name__ == "__main__":
    import sys
    success = notify_digest()
    sys.exit(0 if success else 1)
