"""
tracker_updater.py  —  Records applications to the SQLite database
Called after user approves jobs to persist them.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from utils import THRESHOLD_APPLY, THRESHOLD_REVIEW

DB_PATH = os.environ.get("JOBS_DB_PATH", "tracker/jobs.db")


def init_applications_table():
    """Creates the applications table if it doesn't exist, and migrates
    older databases (created before follow-up tracking existed) forward."""
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company             TEXT,
            title              TEXT,
            url                 TEXT,
            date_applied        TEXT,
            status              TEXT DEFAULT 'sent',
            last_update         TEXT,
            response_date       TEXT,
            response_type       TEXT,
            notes               TEXT,
            recruiter_email     TEXT,
            last_followup_date  TEXT,
            followup_count      INTEGER DEFAULT 0
        )
    """)

    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(applications)")}
    if "last_followup_date" not in existing_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN last_followup_date TEXT")
    if "followup_count" not in existing_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN followup_count INTEGER DEFAULT 0")
    # Feedback loop (2026-08-24): the system records APPLY-tier jobs as
    # 'recommended' (score kept), and only a manual action promotes them to
    # 'sent'. Outcomes are measured ONLY over actually-sent applications --
    # mixing recommendations in would teach the scorer from jobs never applied to.
    if "score" not in existing_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN score INTEGER")
    if "date_recommended" not in existing_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN date_recommended TEXT")

    # Migration: the data contract used to be PT-BR (empresa/titulo).
    # Rename in place so existing rows survive.
    if "empresa" in existing_cols and "company" not in existing_cols:
        conn.execute("ALTER TABLE applications RENAME COLUMN empresa TO company")
    if "titulo" in existing_cols and "title" not in existing_cols:
        conn.execute("ALTER TABLE applications RENAME COLUMN titulo TO title")

    conn.commit()
    conn.close()


def record_recommendation(company: str, title: str, url: str, score: int) -> bool:
    """Records an APPLY-tier evaluation as 'recommended' (the system picked
    it; the user has NOT applied). date_applied stays NULL on purpose: the
    follow-up query keys on date_applied, and a follow-up for a job never
    applied to would be a lie. Returns False when the job is already tracked
    in a further state (sent/responded/etc.) -- a re-evaluation must never
    demote a real application back to 'recommended'."""
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()

    existing = conn.execute(
        "SELECT id, status FROM applications WHERE company = ? AND title = ?",
        (company, title),
    ).fetchone()

    if existing:
        if existing[1] == "recommended":
            conn.execute(
                "UPDATE applications SET score = ?, date_recommended = ?, last_update = ?, url = ? WHERE id = ?",
                (score, now, now, url, existing[0]),
            )
            conn.commit()
            conn.close()
            return True
        conn.close()
        return False

    conn.execute(
        """INSERT INTO applications
           (company, title, url, date_applied, status, last_update, date_recommended, score)
           VALUES (?, ?, ?, NULL, 'recommended', ?, ?, ?)""",
        (company, title, url, now, now, score),
    )
    conn.commit()
    conn.close()
    return True


def record_application(company: str, title: str, url: str) -> bool:
    """
    Records a new application.
    If the job was previously 'recommended', the same row is promoted to
    'sent' (keeping the score that drove the recommendation) -- that is what
    closes the score -> outcome loop. Returns False if already 'sent' or later.
    """
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)

    existing = conn.execute(
        "SELECT id, status FROM applications WHERE company = ? AND title = ?",
        (company, title),
    ).fetchone()

    now = datetime.now(timezone.utc).isoformat()

    if existing:
        if existing[1] == "recommended":
            conn.execute(
                """UPDATE applications
                   SET status = 'sent', date_applied = ?, last_update = ?, url = ?
                   WHERE id = ?""",
                (now, now, url, existing[0]),
            )
            conn.commit()
            conn.close()
            print(f"OK: promoted recommended -> sent: {company} — {title}")
            return True
        print(f"WARNING: Already tracked: {company} — {title}")
        conn.close()
        return False

    conn.execute(
        """INSERT INTO applications
           (company, title, url, date_applied, status, last_update)
           VALUES (?, ?, ?, ?, 'sent', ?)""",
        (company, title, url, now, now),
    )

    conn.commit()
    conn.close()

    return True


def get_outcome_summary() -> dict:
    """Aggregate score -> outcome evidence for scorer calibration.
    Counts only applications actually SENT (status != 'recommended')."""
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        """SELECT company, title, score, status, response_type, date_applied
           FROM applications WHERE status != 'recommended'
           ORDER BY date_applied DESC"""
    ).fetchall()]
    conn.close()

    def _tier(rows, lo, hi):
        sel = [r for r in rows if r.get("score") is not None and lo <= r["score"] < hi]
        return {
            "applied": len(sel),
            "responded": sum(1 for r in sel if r.get("response_type")),
            "interviews": sum(1 for r in sel if r.get("status") == "interview_scheduled"),
        }

    return {
        "total_applied": len(rows),
        "responded": sum(1 for r in rows if r.get("response_type")),
        "apply_tier": _tier(rows, THRESHOLD_APPLY, 10_000),
        "review_tier": _tier(rows, THRESHOLD_REVIEW, THRESHOLD_APPLY),
        "recent": rows[:12],
    }


def record_applications_batch(approvals_file: str) -> int:
    """
    Reads an approvals file and records all applications.
    Returns the number of applications successfully recorded.
    """
    if not os.path.exists(approvals_file):
        print(f"ERROR: File not found: {approvals_file}")
        return 0

    with open(approvals_file, "r", encoding="utf-8") as f:
        approval_record = json.load(f)

    approved_jobs = approval_record.get("approved_jobs", [])
    count = 0

    for job in approved_jobs:
        if record_application(
            company=job.get("company", ""),
            title=job.get("title", ""),
            url=job.get("url", ""),
        ):
            count += 1

    return count


def _warn_no_match(company: str, title: str) -> None:
    """These UPDATEs match on the exact company+title strings, unlike the
    rest of the pipeline, which normalizes. Recording a response against
    "BLP Digital" when the application was filed as "BLP Digital AG" used to
    update zero rows and still print "OK" -- the row kept response_type NULL,
    kept generating follow-up drafts forever, and the dashboard kept showing
    it as merely Applied. Say so instead."""
    print(f"WARNING: no application row matched company={company!r} title={title!r} "
          f"-- nothing was updated. Run `python agents/tracker_updater.py list` "
          f"and re-run with the exact strings recorded there.")


def update_application_status(company: str, title: str, status: str, notes: str = ""):
    """Updates the status of an application."""
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)

    cur = conn.execute(
        """UPDATE applications
           SET status = ?, last_update = ?, notes = ?
           WHERE company = ? AND title = ?""",
        (status, datetime.now(timezone.utc).isoformat(), notes, company, title),
    )
    updated = cur.rowcount
    conn.commit()
    conn.close()
    if not updated:
        _warn_no_match(company, title)
    return updated


def record_response(
    company: str, title: str, response_type: str, notes: str = ""
):
    """
    Records a recruiter response.
    response_type: 'positive' | 'rejection' | 'interview_invite' | 'info_request'
    """
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)

    status_map = {
        "positive": "positive_response",
        "rejection": "rejected",
        "interview_invite": "interview_scheduled",
        "info_request": "awaiting_info",
    }

    status = status_map.get(response_type, "responded")

    cur = conn.execute(
        """UPDATE applications
           SET status = ?, response_type = ?, response_date = ?, last_update = ?, notes = ?
           WHERE company = ? AND title = ?""",
        (
            status,
            response_type,
            datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
            notes,
            company,
            title,
        ),
    )
    updated = cur.rowcount
    conn.commit()
    conn.close()
    if not updated:
        _warn_no_match(company, title)
    return updated


def get_all_applications() -> list:
    """Returns all applications from the database."""
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT * FROM applications ORDER BY date_applied DESC"""
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_stats() -> dict:
    """Returns application statistics."""
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)

    total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    sent = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status = 'sent'"
    ).fetchone()[0]
    responded = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE response_type IS NOT NULL"
    ).fetchone()[0]
    rejected = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status = 'rejected'"
    ).fetchone()[0]
    interviews = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status = 'interview_scheduled'"
    ).fetchone()[0]

    conn.close()

    response_rate = (responded / total * 100) if total > 0 else 0

    return {
        "total_applications": total,
        "pending": sent,
        "responded": responded,
        "response_rate_percent": round(response_rate, 1),
        "rejections": rejected,
        "interviews": interviews,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage the applications tracker.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("stats", help="Print application statistics.")
    sub.add_parser("list", help="List all tracked applications.")

    p_record = sub.add_parser("record", help="Batch-record applications from an approvals JSON file.")
    p_record.add_argument("approvals_file")

    p_apply = sub.add_parser("apply", help="Record that you applied to a job.")
    p_apply.add_argument("--company", required=True)
    p_apply.add_argument("--title", required=True)
    p_apply.add_argument("--url", default="")

    p_response = sub.add_parser("response", help="Record a recruiter response for a tracked application.")
    p_response.add_argument("--company", required=True)
    p_response.add_argument("--title", required=True)
    p_response.add_argument("--type", required=True, choices=["positive", "rejection", "interview_invite", "info_request"])
    p_response.add_argument("--notes", default="")

    args = parser.parse_args()

    if args.command == "stats":
        print(json.dumps(get_stats(), indent=2))
    elif args.command == "list":
        print(json.dumps(get_all_applications(), indent=2, ensure_ascii=False, default=str))
    elif args.command == "record":
        count = record_applications_batch(args.approvals_file)
        print(f"OK: {count} application(s) recorded")
    elif args.command == "apply":
        if record_application(company=args.company, title=args.title, url=args.url):
            print(f"OK: Recorded: {args.company} — {args.title}")
        else:
            print(f"WARNING: Already tracked: {args.company} — {args.title}")
    elif args.command == "response":
        updated = record_response(company=args.company, title=args.title,
                                  response_type=args.type, notes=args.notes)
        if not updated:
            # Exit non-zero so the manual workflow goes red instead of
            # reporting a response that was never recorded.
            print(f"ERROR: no application matched: {args.company} — {args.title}")
            sys.exit(1)
        print(f"OK: Response recorded ({args.type}): {args.company} — {args.title}")
