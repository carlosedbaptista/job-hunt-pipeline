"""
tracker_updater.py  —  Records applications to the SQLite database
Called after user approves jobs to persist them.
"""

import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("JOBS_DB_PATH", "tracker/jobs.db")


def init_applications_table():
    """Creates the applications table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa         TEXT,
            titulo          TEXT,
            url             TEXT,
            date_applied    TEXT,
            status          TEXT DEFAULT 'sent',
            last_update     TEXT,
            response_date   TEXT,
            response_type   TEXT,
            notes           TEXT,
            recruiter_email TEXT
        )
    """)

    conn.commit()
    conn.close()


def record_application(empresa: str, titulo: str, url: str) -> bool:
    """
    Records a new application.
    Returns True on success, False if a record already exists.
    """
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)

    existing = conn.execute(
        "SELECT id FROM applications WHERE empresa = ? AND titulo = ?",
        (empresa, titulo),
    ).fetchone()

    if existing:
        print(f"⚠️  Already tracked: {empresa} — {titulo}")
        conn.close()
        return False

    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO applications
           (empresa, titulo, url, date_applied, status, last_update)
           VALUES (?, ?, ?, ?, 'sent', ?)""",
        (empresa, titulo, url, now, now),
    )

    conn.commit()
    conn.close()

    return True


def record_applications_batch(approvals_file: str) -> int:
    """
    Reads an approvals file and records all applications.
    Returns the number of applications successfully recorded.
    """
    if not os.path.exists(approvals_file):
        print(f"❌ File not found: {approvals_file}")
        return 0

    with open(approvals_file, "r", encoding="utf-8") as f:
        approval_record = json.load(f)

    approved_jobs = approval_record.get("approved_jobs", [])
    count = 0

    for job in approved_jobs:
        if record_application(
            empresa=job.get("empresa", ""),
            titulo=job.get("titulo", ""),
            url=job.get("url", ""),
        ):
            count += 1

    return count


def update_application_status(empresa: str, titulo: str, status: str, notes: str = ""):
    """Updates the status of an application."""
    init_applications_table()
    conn = sqlite3.connect(DB_PATH)

    conn.execute(
        """UPDATE applications
           SET status = ?, last_update = ?, notes = ?
           WHERE empresa = ? AND titulo = ?""",
        (status, datetime.now().isoformat(), notes, empresa, titulo),
    )

    conn.commit()
    conn.close()


def record_response(
    empresa: str, titulo: str, response_type: str, notes: str = ""
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

    conn.execute(
        """UPDATE applications
           SET status = ?, response_type = ?, response_date = ?, last_update = ?, notes = ?
           WHERE empresa = ? AND titulo = ?""",
        (
            status,
            response_type,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
            notes,
            empresa,
            titulo,
        ),
    )

    conn.commit()
    conn.close()


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
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = get_stats()
        print(json.dumps(stats, indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "list":
        apps = get_all_applications()
        print(json.dumps(apps, indent=2, ensure_ascii=False, default=str))
    elif len(sys.argv) > 2 and sys.argv[1] == "record":
        count = record_applications_batch(sys.argv[2])
        print(f"✅ {count} application(s) recorded")
    else:
        print("Usage:")
        print("  python agents/tracker_updater.py stats")
        print("  python agents/tracker_updater.py list")
        print("  python agents/tracker_updater.py record <approvals_file>")
