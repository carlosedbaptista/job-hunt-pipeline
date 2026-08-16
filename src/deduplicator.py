"""
deduplicator.py  —  Filters already-seen jobs using SQLite
Hash = sha256(company | title | location), retained for 21 days.
"""

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta

DB_PATH = os.environ.get("JOBS_DB_PATH", "tracker/jobs.db")


# ─── Normalisation ────────────────────────────────────────────────────────────

# Legal suffixes that vary between sources for the same company
# (e.g. "BLP Digital AG" on Adzuna vs "BLP Digital" in an email alert).
LEGAL_SUFFIXES = {"ag", "gmbh", "sa", "sarl", "sagl", "ltd", "llc", "inc", "plc", "co", "kg", "se", "holding"}


def normalize(text: str) -> str:
    """Transliterates accents, removes punctuation and extra spaces."""
    if not text:
        return ""
    # NFKD + strip combining marks: "Zürich" -> "zurich" (not "z rich")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_company(text: str) -> str:
    """Company normalisation: also drops trailing legal suffixes."""
    tokens = normalize(text).split()
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_location(text: str) -> str:
    """Location normalisation: keeps only the first locality token so
    'Zurich', 'Zurich, Zurich' and 'Zurich, Switzerland' all match."""
    normalized = normalize(text)
    return normalized.split()[0] if normalized else ""


def make_hash(empresa: str, titulo: str, localizacao: str) -> str:
    """Generates a 16-char deduplication hash."""
    key = f"{normalize_company(empresa)}|{normalize(titulo)}|{normalize_location(localizacao)}"
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

    # The `applications` table is owned by agents/tracker_updater.py (see
    # its init_applications_table()) -- it used to also be defined here
    # with an incompatible, never-populated job_hash-based schema. Since
    # this init_db() runs on every CI execution (via unified_ingestor)
    # and tracker_updater's init only on the manual track-application
    # workflow, on a fresh DB this file's CREATE TABLE would have won the
    # race and silently broken every applications-table read/write
    # downstream (followup_sender, tracker_updater). Do not redefine it
    # here; call agents.tracker_updater.init_applications_table() if a
    # caller in this module ever needs the table to exist.

    conn.commit()
    conn.close()


def purge_old_records(conn: sqlite3.Connection, days: int = 21):
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
    retention_days: int = 21,
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

    print(f"\n[OK] {len(new_jobs)} new jobs -> {output}")
