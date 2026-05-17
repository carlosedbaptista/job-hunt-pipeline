"""
pipeline.py  —  Orquestrador principal da Semana 2
Roda o pipeline completo: ingest → parse → dedup → output

Uso:
  python src/pipeline.py           # últimas 24h
  python src/pipeline.py --hours 48  # últimas 48h
  python src/pipeline.py --dry-run   # sem salvar no DB (teste)
"""

import argparse
import json
import os
import sys
from datetime import datetime

# Adiciona o root do projeto ao path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.email_ingestor import fetch_job_alert_emails
from agents.email_parser import parse_all_emails
from src.deduplicator import filter_new_jobs, get_stats


def run_pipeline(hours_back: int = 24, dry_run: bool = False) -> list[dict]:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    divider = "=" * 55

    print(f"\n{divider}")
    print(f"  JOB HUNT PIPELINE  —  {timestamp}")
    if dry_run:
        print("  ⚠️  DRY RUN — nada será salvo no banco")
    print(f"{divider}\n")

    os.makedirs("digests", exist_ok=True)
    os.makedirs("tracker", exist_ok=True)

    # ── STEP 1: Buscar emails ────────────────────────────────────────────────
    print("STEP 1 › Buscando emails de alerta...")
    emails = fetch_job_alert_emails(hours_back=hours_back)

    if not emails:
        print("Nenhum email encontrado. Pipeline encerrado.\n")
        return []

    # Salva raw para debug
    with open("digests/raw_emails_full.json", "w", encoding="utf-8") as f:
        json.dump(emails, f, ensure_ascii=False, indent=2)

    # ── STEP 2: Parsear vagas ────────────────────────────────────────────────
    print(f"\nSTEP 2 › Extraindo vagas com Claude Haiku ({len(emails)} emails)...")
    all_jobs = parse_all_emails(emails)

    with open("digests/parsed_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)

    print(f"\n  → {len(all_jobs)} vagas extraídas no total")

    if not all_jobs:
        print("Nenhuma vaga extraída. Pipeline encerrado.\n")
        return []

    # ── STEP 3: Deduplicação ─────────────────────────────────────────────────
    print("\nSTEP 3 › Filtrando duplicatas...")

    if dry_run:
        # Em dry-run, não salva no DB — usa dedup apenas em memória
        seen_keys = set()
        new_jobs = []
        for job in all_jobs:
            key = f"{job.get('empresa','').lower()}|{job.get('titulo','').lower()}"
            if key not in seen_keys:
                seen_keys.add(key)
                new_jobs.append(job)
    else:
        new_jobs = filter_new_jobs(all_jobs)

    duplicates = len(all_jobs) - len(new_jobs)
    print(f"  → {len(new_jobs)} novas  |  {duplicates} duplicatas filtradas")

    # ── OUTPUT ───────────────────────────────────────────────────────────────
    run_ts = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = f"digests/new_jobs_{run_ts}.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(new_jobs, f, ensure_ascii=False, indent=2)

    # Também sobrescreve o "latest" para uso do próximo step
    with open("digests/new_jobs_latest.json", "w", encoding="utf-8") as f:
        json.dump(new_jobs, f, ensure_ascii=False, indent=2)

    # ── RESUMO ───────────────────────────────────────────────────────────────
    print(f"\n{divider}")
    print(f"  RESULTADO")
    print(f"{divider}")
    print(f"  Emails processados : {len(emails)}")
    print(f"  Vagas extraídas    : {len(all_jobs)}")
    print(f"  Vagas novas        : {len(new_jobs)}")
    print(f"  Salvo em           : {output_path}")

    if new_jobs:
        print(f"\n  Top vagas novas:")
        for i, job in enumerate(new_jobs[:5], 1):
            empresa = job.get("empresa", "N/A")
            titulo = job.get("titulo", "N/A")
            local = job.get("localizacao", "?")
            portal = job.get("portal", "")
            print(f"  {i}. [{portal}] {empresa} — {titulo} ({local})")

    if not dry_run:
        stats = get_stats()
        print(f"\n  DB stats: {stats}")

    print(f"\n✅ Pipeline concluído às {datetime.now().strftime('%H:%M')}\n")
    return new_jobs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt Pipeline — Semana 2")
    parser.add_argument(
        "--hours", type=int, default=24, help="Janela de busca em horas (default: 24)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Roda sem salvar no banco (útil para testes)",
    )
    args = parser.parse_args()

    jobs = run_pipeline(hours_back=args.hours, dry_run=args.dry_run)
    sys.exit(0 if jobs is not None else 1)
