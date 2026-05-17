"""
week3_pipeline.py  —  Orquestrador Semana 3
Roda: avaliação → cover letters → CV adaptados
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def run_step(script: str, description: str) -> bool:
    """Roda um script e retorna True se sucesso."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"{'='*60}\n")

    try:
        result = subprocess.run(
            [sys.executable, script],
            cwd=ROOT,
            capture_output=False,
            text=True,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"❌ Erro ao rodar {script}: {e}")
        return False


def run_week3_pipeline():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'='*60}")
    print(f"  JOB HUNT — SEMANA 3  |  {timestamp}")
    print(f"  Avaliação & Materiais")
    print(f"{'='*60}")

    # Step 1: Evaluate all jobs
    print("\nSTEP 1 › Avaliando vagas de fit...")
    if not run_step("agents/job_evaluator.py", "Job Evaluator (Haiku)"):
        print("❌ Avaliação falhou.")
        return False

    # Step 2: Generate cover letters for APPLY jobs
    print("\nSTEP 2 › Gerando cover letters...")
    if not run_step("agents/cover_letter_writer.py", "Cover Letter Writer (Sonnet)"):
        print("⚠️  Cover letters falharam (nem todas as vagas qualificam)")

    # Step 3: Tailor CVs for APPLY jobs
    print("\nSTEP 3 › Adaptando CVs...")
    if not run_step("agents/cv_tailor.py", "CV Tailor (Sonnet)"):
        print("⚠️  Tailoring CV falhou (nem todas as vagas qualificam)")

    # Load results and summary
    print(f"\n{'='*60}")
    print(f"  RESULTADO FINAL")
    print(f"{'='*60}\n")

    if os.path.exists("digests/job_evaluations_latest.json"):
        with open("digests/job_evaluations_latest.json", "r") as f:
            evals = json.load(f)

        apply = [e for e in evals if e.get("score", 0) >= 65]
        review = [e for e in evals if 45 <= e.get("score", 0) < 75]
        uncertain = [e for e in evals if e.get("score", 0) < 45]

        print(f"Total vagas avaliadas: {len(evals)}\n")

        if apply:
            print(f"✅ APPLY ({len(apply)}) — gerar cover letter + CV:")
            for e in apply:
                score = e.get("score", 0)
                job = e.get("job", {})
                print(f"   • [{score}/100] {job.get('empresa')} — {job.get('titulo')[:40]}")

        if review:
            print(f"\n⚠️  REVIEW ({len(review)}) — Carlos decide:")
            for e in review:
                score = e.get("score", 0)
                job = e.get("job", {})
                print(f"   • [{score}/100] {job.get('empresa')} — {job.get('titulo')[:40]}")

        if uncertain:
            print(f"\n❌ UNCERTAIN ({len(uncertain)}) — não preenche critérios:")
            for e in uncertain:
                score = e.get("score", 0)
                job = e.get("job", {})
                flags = e.get("red_flags", [])
                print(f"   • [{score}/100] {job.get('empresa')} — {job.get('titulo')[:40]}")
                if flags:
                    print(f"      Problemas: {'; '.join(flags[:2])}")

        print(f"\n{'='*60}")
        print(f"  Materiais gerados:")
        print(f"  • Avaliações: digests/job_evaluations_latest.json")

        if os.path.exists("digests/cover_letters_latest.json"):
            with open("digests/cover_letters_latest.json", "r") as f:
                letters = json.load(f)
            print(f"  • Cover letters: digests/cover_letters_latest.json ({len(letters)} letras)")

        if os.path.exists("digests/tailored_cvs_latest.json"):
            with open("digests/tailored_cvs_latest.json", "r") as f:
                cvs = json.load(f)
            print(f"  • CVs tailored: digests/tailored_cvs_latest.json ({len(cvs)} CVs)")

        print(f"\n✅ Semana 3 concluída às {datetime.now().strftime('%H:%M')}")
        return True

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunt — Semana 3 Pipeline")
    args = parser.parse_args()

    success = run_week3_pipeline()
    sys.exit(0 if success else 1)
