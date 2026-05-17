"""
deduplicator.py  —  Filtra vagas já vistas usando SQLite
Hash = sha256(empresa_normalizada | titulo_normalizado | localizacao_normalizada)
Persiste vagas por 7 dias.
"""

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

DB_PATH = os.environ.get("JOBS_DB_PATH", "tracker/jobs.db")


# ─── Normalização ────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Remove acentos, pontuação e espaços extras para comparação."""
    if not text:
        return ""
    text = text.lower().strip()
    # Remove caracteres não-alfanuméricos (exceto espaços)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_hash(empresa: str, titulo: str, localizacao: str) -> str:
    """Gera hash de deduplicação de 16 chars."""
    key = f"{normalize(empresa)}|{normalize(titulo)}|{normalize(localizacao)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


# ─── Banco de dados ───────────────────────────────────────────────────────────

def init_db(db_path: str = DB_PATH):
    """Cria tabelas se não existirem."""
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
    """Remove registros mais antigos que N dias (exceto aplicações)."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn.execute(
        "DELETE FROM seen_jobs WHERE last_seen < ? AND status = 'new'",
        (cutoff,)
    )


# ─── Deduplicação ─────────────────────────────────────────────────────────────

def filter_new_jobs(
    jobs: list[dict],
    db_path: str = DB_PATH,
    retention_days: int = 7,
) -> list[dict]:
    """
    Filtra vagas já vistas nas últimas N dias.
    - Insere novas vagas no DB
    - Atualiza last_seen das duplicatas
    - Retorna apenas vagas novas
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
            # Nova vaga — insere no DB e adiciona ao resultado
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
            # Duplicata — só atualiza last_seen
            conn.execute(
                "UPDATE seen_jobs SET last_seen = ? WHERE hash = ?",
                (now, h),
            )

    conn.commit()
    conn.close()
    return new_jobs


# ─── Utilitários ──────────────────────────────────────────────────────────────

def get_stats(db_path: str = DB_PATH) -> dict:
    """Retorna estatísticas do banco."""
    if not os.path.exists(db_path):
        return {"error": "DB não encontrado"}

    conn = sqlite3.connect(db_path)

    total_seen = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
    total_applied = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    pending = conn.execute(
        "SELECT COUNT(*) FROM applications WHERE status = 'sent'"
    ).fetchone()[0]

    conn.close()
    return {
        "total_vagas_vistas": total_seen,
        "total_aplicacoes": total_applied,
        "aplicacoes_pendentes": pending,
    }


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Modo stats
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        stats = get_stats()
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        sys.exit(0)

    # Modo dedup normal
    input_file = "digests/parsed_jobs_latest.json"
    if not os.path.exists(input_file):
        print(f"Arquivo não encontrado: {input_file}")
        print("Rode primeiro: python agents/email_parser.py")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"Vagas parseadas: {len(jobs)}")
    new_jobs = filter_new_jobs(jobs)

    duplicates = len(jobs) - len(new_jobs)
    print(f"Novas: {len(new_jobs)}  |  Duplicatas filtradas: {duplicates}")

    output = "digests/new_jobs_latest.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(new_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(new_jobs)} vagas novas → {output}")
