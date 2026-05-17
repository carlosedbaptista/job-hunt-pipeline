"""
deduplicator.py  —  Filters already-seen jobs using SQLite
Hash = sha256(company | title | location), retained for 7 days.
"""

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.environ.get("JOBS_DB_PATH", "tracker/jobs.db")


# ─── Normalisation ────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Removes accents, punctuation and extra spaces for consistent comparison."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_hash(empresa: str, titulo: str, localizacao: str) -> str:
    """Generates a 16-char deduplication hash."""
    key = f"{normalize(empresa)}|{normalize(titulo)}|{normalize(localizacao)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ─── Database ─────────────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    """Creates tables if they don't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            hash        TEXT PRIMARY KEY,
            empresa     TEXT,
            titulo      TEXT,
            localizacao TEXT,
            url         TEXT,
            portal      TEXT,
            first_seen  TEXT,
            last_seen   TEXT,
            status      TEXT DEFAULT 'new'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_hash     TEXT,
            empresa      TEXT,
            titulo       TEXT,
            url          TEXT,
            date_applied TEXT,
            status       TEXT DEFAULT 'sent',
            notes        TEXT,
            FOREIGN KEY (job_hash) REFERENCES seen_jobs(hash)
        )
    """)

    conn.commit()
    conn.close()


def purge_old_records(conn: sqlite3.Connection, days: int = 7):
    """Removes records older than N days (applications are preserved)."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn.execute(
        "DELETE FROM seen_jobs WHERE last_seen < ? AND status = 'new'",
        (cutoff,)
    )


# ─── Deduplication ────────────────────────────────────────────────────────────

def filter_new_jobs(
    jobs: list[dict],
    db_path: str = DB_PATH,
    retention_days: int = 7,
) -> list[dict]:
    """
    Filters jobs already seen in the last N days.
    Inserts new jobs into the DB; updates last_seen for duplicates.
    Returns only new jobs.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    purge_old_records(conn, retention_days)

    new_jobs = []
    now = datetime.now().isoformat()

    for job in jobs:
        h = make_hash(
            job.get("empresa", ""),
            job.get("titulo", ""),
            job.get("localizacao", ""),
        )

        row = conn.execute(
            "SELECT hash FROM seen_jobs WHERE hash = ?", (h,)
        ).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO seen_jobs
                   (hash, empresa, titulo, localizacao, url, portal, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    h,
                    job.get("empresa", ""),
                    job.get("titulo", ""),
                    job.get("localizacao", ""),
                    job.get("url", ""),
                    job.get("portal", ""),
                    now,
                    now,
                ),
            )
            job["hash"] = h
            new_jobs.append(job)
        else:
            conn.execute(
                "UPDATE seen_jobs SET last_seen = ? WHERE hash = ?",
                (now, h),
            )

    conn.commit()
    conn.close()
    return new_jobs


# ─── Utilities ────────────────────────────────────────────────────────────────

def get_stats(db_path: str = DB_PATH) -> dict:
    """Returns database statistics."""
    if not os.path.exists(db_path):
        return {"error": "Database not found"}

    conn = sqlite3.connect(db_path)

    total_seen = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
    total_applied = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status = 'sent'"
    ).fetchone()[0]

    conn.close()
    return {
        "total_jobs_seen": total_seen,
        "total_applications": total_applied,
        "pending_applications": pending,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = get_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        sys.exit(0)

    input_file = "digests/parsed_jobs_latest.json"
    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        print("Run first: python agents/email_parser.py")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"Jobs parsed: {len(jobs)}")
    new_jobs = filter_new_jobs(jobs)

    duplicates = len(jobs) - len(new_jobs)
    print(f"New: {len(new_jobs)}  |  Duplicates filtered: {duplicates}")

    output = "digests/new_jobs_latest.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(new_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(new_jobs)} new jobs → {output}")
