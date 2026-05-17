"""
week4_pipeline.py  —  Orquestrador Semana 4
Pipeline completo: Semana 2 + 3 + 4 (ingest → parse → eval → digest)
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime


def run_step(script: str, description: str) -> bool:
    """Roda um script e retorna True se sucesso."""
    print(f"\n{'='*70}")
    print(f"  {description}")
    print(f"{'='*70}\n")

    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=False,
            text=True,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False


def run_full_pipeline():
    """Roda o pipeline completo da Semana 2 até 4."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*70}")
    print(f"  JOB HUNT — FULL PIPELINE")
    print(f"  Semana 2: Email → Parse → Dedup")
    print(f"  Semana 3: Evaluate → Cover Letters → CV Tailor")
    print(f"  Semana 4: Digest → Approval")
    print(f"  {timestamp}")
    print(f"{'='*70}")

    # ─── SEMANA 2 ────────────────────────────────────────────────────────────
    print("\n📧 SEMANA 2: Ingestão & Parsing\n")

    if not run_step("src/email_ingestor.py", "Email Ingestor"):
        print("❌ Email ingestor falhou")
        return False

    if not run_step("agents/email_parser.py", "Email Parser"):
        print("⚠️  Parsing falhou (pode não ter vagas no email)")

    if not run_step("src/deduplicator.py", "Deduplicator"):
        print("⚠️  Dedup falhou")

    # ─── SEMANA 3 ────────────────────────────────────────────────────────────
    print("\n📊 SEMANA 3: Avaliação & Materiais\n")

    if not run_step("agents/job_evaluator.py", "Job Evaluator"):
        print("❌ Evaluator falhou")
        return False

    # Cover letters e CV tailor são opcionais (rodam só se houver APPLY jobs)
    run_step("agents/cover_letter_writer.py", "Cover Letter Writer (opcional)")
    run_step("agents/cv_tailor.py", "CV Tailor (opcional)")

    # ─── SEMANA 4 ────────────────────────────────────────────────────────────
    print("\n📋 SEMANA 4: Digest & Aprovação\n")

    if not run_step("agents/digest_generator.py", "Digest Generator"):
        print("❌ Digest falhou")
        return False

    # ─── RESUMO FINAL ─────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  ✅ PIPELINE CONCLUÍDO")
    print(f"{'='*70}\n")

    print("PRÓXIMOS PASSOS:")
    print("  1. Leia o digest acima")
    print("  2. Escolha as vagas que quer aplicar")
    print("  3. Rode: python src/approval_handler.py --approve '1,3,5'")
    print("     (substitua 1,3,5 pelos números das vagas)")
    print("")
    print("ARQUIVOS GERADOS:")
    print("  • digests/digest_latest.json")
    print("  • digests/digest_latest.txt")
    print("  • digests/job_evaluations_latest.json")
    print("")

    return True


def run_digest_only():
    """Roda só a Semana 4 (útil se já tem avaliações da Semana 3)."""
    print(f"\n{'='*70}")
    print(f"  JOB HUNT — DIGEST ONLY (Semana 4)")
    print(f"{'='*70}")

    return run_step("agents/digest_generator.py", "Digest Generator")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt — Semana 4 Pipeline")
    parser.add_argument(
        "--digest-only",
        action="store_true",
        help="Roda só o digest (assume que Semana 2-3 já rodaram)",
    )
    args = parser.parse_args()

    if args.digest_only:
        success = run_digest_only()
    else:
        success = run_full_pipeline()

    sys.exit(0 if success else 1)
