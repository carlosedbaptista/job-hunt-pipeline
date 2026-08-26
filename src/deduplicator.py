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
from datetime import datetime, timedelta, timezone

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


_LOCATION_PAREN_RE = re.compile(r"\([^)]*\)")


def normalize_location(text: str) -> str:
    """Location normalisation: keeps only the first locality token so
    'Zurich', 'Zurich, Zurich' and 'Zurich, Switzerland' all match.
    LinkedIn alert cards hand over the 'Company · City, Country (Type)'
    blob instead ('Randstad Digital · Zurich, Switzerland (Hybrid)'): strip
    parentheticals and take the part after the middle dot, or the keyed
    locality becomes the COMPANY and the same posting dedups twice
    (measured 2026-08-26: one job, two cards, two agent evaluations)."""
    t = _LOCATION_PAREN_RE.sub(" ", str(text or ""))
    if "·" in t:
        t = t.split("·", 1)[1]
    normalized = normalize(t)
    return normalized.split()[0] if normalized else ""


# ─── Identity strengthening (2026-08-25) ─────────────────────────────────────
# The exact hash split ONE posting into two seen/evaluated jobs when a board
# padded the title ('AI Engineer (80%-100%) - Zurich') or the company arrived
# under an alias ('iudexnc' vs 'Iudex Non Calculat'). The dashboard got the
# same rule first, as a view-layer prototype; these are the same definitions,
# promoted to the shared kernel so ingestion, alerts, orchestrator, rescoring
# and the dashboard all mean the SAME thing by 'same job'.

_LOCATION_TAIL_RE = re.compile(
    r"\s*[-–]\s*(zurich|zürich|zug|switzerland|swiss|remote|geneva|genève|"
    r"bern|berne|basel|lausanne|winterthur|lucerne|lugano)\b.*$",
    re.IGNORECASE)
_PAREN_RE = re.compile(r"\([^)]*\)")
_WORKLOAD_RE = re.compile(r"\b\d{1,3}\s*%\s*(?:[-–]\s*\d{1,3}\s*%)?\b")


def normalize_title(title: str) -> str:
    """Title identity: boards pad titles with workload ('(80%-100%)') and the
    location (' - Zurich'); the same posting typed by hand carries neither.
    Strip both before the base normalisation."""
    t = _PAREN_RE.sub(" ", str(title or ""))
    t = _WORKLOAD_RE.sub(" ", t)
    t = _LOCATION_TAIL_RE.sub("", t)
    return normalize(t)


def company_abbreviation(company: str) -> str:
    """first-token-plus-initials form: 'Iudex Non Calculat' -> 'iudexnc'."""
    parts = normalize_company(company).split()
    if len(parts) < 2:
        return ""
    return parts[0] + "".join(p[0] for p in parts[1:] if p)


def companies_compatible(a: str, b: str) -> bool:
    """Same employer through formatting or an alias: equal after
    normalisation, or one side is exactly the first-token-plus-initials
    abbreviation of the other. Deliberately NOT a similarity threshold --
    'Swiss International Air Lines' and 'Swiss Re' must never merge, and
    'Unknown' companies merge nothing (different alert cards with a generic
    title would collapse distinct postings)."""
    ka, kb = normalize_company(a or ""), normalize_company(b or "")
    if not ka or not kb or ka == "unknown" or kb == "unknown":
        return False
    if ka == kb:
        return True
    return ((len(ka) >= 4 and ka == company_abbreviation(b)) or
            (len(kb) >= 4 and kb == company_abbreviation(a)))


def make_hash(company: str, title: str, location: str) -> str:
    """Generates a 16-char deduplication hash. NOTE: the title component was
    strengthened to normalize_title on 2026-08-25 -- rows stored before that
    need `rehash_seen_jobs` (a padded title hashes differently now)."""
    key = f"{normalize_company(company)}|{normalize_title(title)}|{normalize_location(location)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ─── Database ─────────────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    """Creates tables if they don't exist."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_jobs (
            hash        TEXT PRIMARY KEY,
            company     TEXT,
            title       TEXT,
            location    TEXT,
            url         TEXT,
            portal      TEXT,
            first_seen  TEXT,
            last_seen   TEXT,
            status      TEXT DEFAULT 'new'
        )
    """)

    # Migration: the data contract used to be PT-BR (empresa/titulo/
    # localizacao). Rename in place so existing rows survive.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(seen_jobs)")}
    if "empresa" in existing_cols and "company" not in existing_cols:
        conn.execute("ALTER TABLE seen_jobs RENAME COLUMN empresa TO company")
    if "titulo" in existing_cols and "title" not in existing_cols:
        conn.execute("ALTER TABLE seen_jobs RENAME COLUMN titulo TO title")
    if "localizacao" in existing_cols and "location" not in existing_cols:
        conn.execute("ALTER TABLE seen_jobs RENAME COLUMN localizacao TO location")

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
    # UTC-aware. Legacy rows stored naive local timestamps; comparing those
    # against an aware ISO cutoff is off by a couple of hours at most on the
    # boundary day -- harmless for a 21-day retention window.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn.execute(
        "DELETE FROM seen_jobs WHERE last_seen < ? AND status = 'new'",
        (cutoff,)
    )


# ─── Deduplication ────────────────────────────────────────────────────────────

def filter_new_jobs(
    jobs: list[dict],
    db_path: str = DB_PATH,
    retention_days: int = 21,
    mark_seen: bool = True,
) -> list[dict]:
    """
    Filters jobs already seen in the last N days.
    With mark_seen=True (default), inserts new jobs into the DB and updates
    last_seen for duplicates. With mark_seen=False it only filters -- used
    by unified_ingestor so jobs beyond the per-run evaluation cap stay
    unseen and resurface next run instead of being silently swallowed.
    Returns only new jobs.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    purge_old_records(conn, retention_days)

    new_jobs = []
    now = datetime.now(timezone.utc).isoformat()

    for job in jobs:
        h = make_hash(
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
        )

        row = conn.execute(
            "SELECT hash FROM seen_jobs WHERE hash = ?", (h,)
        ).fetchone()

        if row is None:
            # Second dedup layer: the exact hash misses postings that differ
            # only by title padding or a company alias, so the same job used
            # to enter (and cost an evaluation) twice. A cheap scan over the
            # retention window catches those -- seen_jobs holds hundreds of
            # rows at most, and compatibility is exact rules, not similarity.
            compat_hash = _find_compat_hash(conn, job, retention_days)
            if compat_hash is not None:
                if mark_seen:
                    conn.execute(
                        "UPDATE seen_jobs SET last_seen = ? WHERE hash = ?",
                        (now, compat_hash),
                    )
                continue
            if mark_seen:
                conn.execute(
                    """INSERT INTO seen_jobs
                       (hash, company, title, location, url, portal, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        h,
                        job.get("company", ""),
                        job.get("title", ""),
                        job.get("location", ""),
                        job.get("url", ""),
                        job.get("portal", ""),
                        now,
                        now,
                    ),
                )
            job["hash"] = h
            new_jobs.append(job)
        elif mark_seen:
            conn.execute(
                "UPDATE seen_jobs SET last_seen = ? WHERE hash = ?",
                (now, h),
            )

    conn.commit()
    conn.close()
    return new_jobs


# ─── Utilities ────────────────────────────────────────────────────────────────

def _find_compat_hash(conn: sqlite3.Connection, job: dict, retention_days: int = 21):
    """The hash of a seen_jobs row that is the same posting under an alias /
    padded title, or None. Requires ALL of: equal title identity, equal
    normalised location, compatible companies -- 'Swiss International Air
    Lines' vs 'Swiss Re' and 'Unknown' cards never merge."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    rows = conn.execute(
        "SELECT hash, company, title, location FROM seen_jobs WHERE last_seen >= ?",
        (cutoff,),
    ).fetchall()
    title_key = normalize_title(job.get("title", ""))
    loc_key = normalize_location(job.get("location", ""))
    if not title_key:
        return None
    for h, company, title, location in rows:
        if normalize_title(title or "") != title_key:
            continue
        if normalize_location(location or "") != loc_key:
            continue
        if companies_compatible(job.get("company", ""), company or ""):
            return h
    return None


def rehash_seen_jobs(db_path: str = DB_PATH) -> dict:
    """One-time migration after the 2026-08-25 hash strengthening: recomputes
    stored hashes from the raw fields. Collisions (two old rows now hashing
    equal) merge: earliest first_seen, latest last_seen, and a non-'new'
    status survives over 'new' (applications are never demoted)."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT hash, company, title, location, first_seen, last_seen, status "
        "FROM seen_jobs"
    ).fetchall()
    rehashed = merged = 0
    for old_h, company, title, location, first_seen, last_seen, status in rows:
        new_h = make_hash(company or "", title or "", location or "")
        if new_h == old_h:
            continue
        existing = conn.execute(
            "SELECT first_seen, last_seen, status FROM seen_jobs WHERE hash = ?",
            (new_h,),
        ).fetchone()
        if existing is None:
            conn.execute("UPDATE seen_jobs SET hash = ? WHERE hash = ?",
                         (new_h, old_h))
            rehashed += 1
        else:
            e_first, e_last, e_status = existing
            conn.execute(
                "UPDATE seen_jobs SET first_seen = ?, last_seen = ?, status = ? "
                "WHERE hash = ?",
                (min(first_seen, e_first), max(last_seen, e_last),
                 e_status if e_status != "new" else status, new_h),
            )
            conn.execute("DELETE FROM seen_jobs WHERE hash = ?", (old_h,))
            merged += 1
    conn.commit()
    conn.close()
    return {"rows": len(rows), "rehashed": rehashed, "merged": merged}

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

    if len(sys.argv) > 1 and sys.argv[1] == "rehash-seen":
        # One-time migration after the 2026-08-25 hash strengthening.
        result = rehash_seen_jobs()
        print(f"rehash-seen: {result['rehashed']} rows re-hashed, "
              f"{result['merged']} collisions merged "
              f"(of {result['rows']} rows)")
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
