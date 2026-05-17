"""
approval_handler.py  —  Processa aprovações de vagas
Você escolhe quais vagas aplicar: python src/approval_handler.py --approve "1,3,5"
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def load_digest():
    """Carrega o digest mais recente."""
    digest_file = "digests/digest_latest.json"
    if not os.path.exists(digest_file):
        print("❌ Digest não encontrado. Rode primeiro: python agents/digest_generator.py")
        return None

    with open(digest_file, "r", encoding="utf-8") as f:
        return json.load(f)


def process_approvals(approval_string: str):
    """
    Processa aprovações do usuário.
    Exemplo: "1,3,5" ou "1, 3, 5"
    """
    digest = load_digest()
    if not digest:
        return False

    top_jobs = digest.get("top_jobs", [])

    if not top_jobs:
        print("❌ Nenhuma vaga no digest.")
        return False

    # Parse approval string
    try:
        approved_ids = [int(x.strip()) for x in approval_string.split(",")]
    except ValueError:
        print(f"❌ Formato inválido: '{approval_string}'")
        print("Use: --approve '1,3,5'")
        return False

    # Validar IDs
    invalid_ids = [id for id in approved_ids if id < 1 or id > len(top_jobs)]
    if invalid_ids:
        print(f"❌ IDs inválidas: {invalid_ids} (deve estar entre 1 e {len(top_jobs)})")
        return False

    # Criar registro de aprovação
    approved_jobs = []
    for i, job_eval in enumerate(top_jobs, 1):
        if i in approved_ids:
            job = job_eval.get("job", {})
            approved_jobs.append({
                "position": i,
                "empresa": job.get("empresa", ""),
                "titulo": job.get("titulo", ""),
                "url": job.get("url", ""),
                "score": job_eval.get("score", 0),
                "approved_at": datetime.now().isoformat(),
            })

    print("\n" + "=" * 70)
    print("APROVAÇÃO DE VAGAS")
    print("=" * 70)
    print(f"\nVocê aprovou {len(approved_jobs)} vaga(s):")
    print()

    for job in approved_jobs:
        print(f"  ✅ #{job['position']} [{job['score']}/100] {job['empresa']}")
        print(f"     {job['titulo']}")
        print(f"     Link: {job['url'][:60]}...")
        print()

    # Salva approval record
    os.makedirs("digests", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    approval_record = {
        "approved_at": datetime.now().isoformat(),
        "approved_jobs": approved_jobs,
        "next_step": "Copie o link acima e submeta a aplicação manualmente no site da empresa.",
    }

    approval_file = f"digests/approvals_{timestamp}.json"
    with open(approval_file, "w", encoding="utf-8") as f:
        json.dump(approval_record, f, ensure_ascii=False, indent=2)

    # Sobrescreve latest
    with open("digests/approvals_latest.json", "w", encoding="utf-8") as f:
        json.dump(approval_record, f, ensure_ascii=False, indent=2)

    print("=" * 70)
    print("PRÓXIMO PASSO:")
    print("1. Abra cada link acima no navegador")
    print("2. Submeta a aplicação manualmente no site da empresa")
    print("3. Na Semana 5, vamos automatizar o tracking de respostas")
    print("=" * 70)
    print(f"\n✅ Registro de aprovação salvo: {approval_file}")

    return True


def list_digest():
    """Lista as vagas do digest para referência."""
    digest = load_digest()
    if not digest:
        return

    print("\n" + "=" * 70)
    print("VAGAS DISPONÍVEIS (para aprovação)")
    print("=" * 70 + "\n")

    for i, job_eval in enumerate(digest.get("top_jobs", []), 1):
        score = job_eval.get("score", 0)
        job = job_eval.get("job", {})
        empresa = job.get("empresa", "")
        titulo = job.get("titulo", "")

        print(f"{i}. [{score}/100] {empresa} — {titulo}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Processa aprovações de vagas do digest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  python src/approval_handler.py --list
  python src/approval_handler.py --approve "1,3,5"
  python src/approval_handler.py --approve "1, 2"
        """,
    )

    parser.add_argument(
        "--approve",
        type=str,
        help='IDs das vagas aprovadas, separadas por vírgula (ex: "1,3,5")',
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Lista as vagas disponíveis para aprovação",
    )

    args = parser.parse_args()

    if args.list:
        list_digest()
    elif args.approve:
        success = process_approvals(args.approve)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
