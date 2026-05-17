"""
apply_automation.py  —  Orquestra fluxo de aplicação com Claude in Chrome
Workflow: aprovação → guia → Claude in Chrome → tracker
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.form_fill_guide import (
    generate_form_fill_guide,
    generate_claude_in_chrome_prompt,
)
from agents.tracker_updater import record_application, update_application_status


def load_latest_approvals():
    """Carrega as aprovações mais recentes."""
    approval_file = "digests/approvals_latest.json"
    if not os.path.exists(approval_file):
        print("❌ Nenhuma aprovação encontrada.")
        print("Rode primeiro: python src/approval_handler.py --approve '...'")
        return None

    with open(approval_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_evaluations():
    """Carrega avaliações das vagas."""
    eval_file = "digests/job_evaluations_latest.json"
    if not os.path.exists(eval_file):
        return {}

    with open(eval_file, "r", encoding="utf-8") as f:
        evals = json.load(f)
        # Index by company name
        return {e.get("job", {}).get("empresa", ""): e for e in evals}


def generate_apply_guides(approvals_data: dict) -> list:
    """Gera guias pra todas as aplicações aprovadas."""
    approved_jobs = approvals_data.get("approved_jobs", [])
    evals = load_evaluations()

    guides = []
    os.makedirs("digests", exist_ok=True)

    print(f"\nGerando guias pra {len(approved_jobs)} vaga(s)...\n")

    for i, job in enumerate(approved_jobs, 1):
        empresa = job.get("empresa", "")
        titulo = job.get("titulo", "")
        url = job.get("url", "")
        score = job.get("score", 0)

        print(f"[{i}] {empresa} — {titulo}")

        eval_data = evals.get(empresa, {})
        guide = generate_form_fill_guide(eval_data, job)
        guides.append(guide)

        # Salva guia individual
        safe_name = empresa.replace(" ", "_").replace("/", "-")
        guide_file = f"digests/form_guide_{safe_name}_{i}.json"
        with open(guide_file, "w", encoding="utf-8") as f:
            json.dump(guide, f, ensure_ascii=False, indent=2)

        print(f"   ✅ Guia salvo: {guide_file}")

    return guides


def display_apply_instructions(guides: list):
    """Exibe instruções pra usar Claude in Chrome."""
    print("\n" + "=" * 70)
    print("COMO USAR CLAUDE IN CHROME PARA PREENCHER FORMULÁRIOS")
    print("=" * 70)

    for i, guide in enumerate(guides, 1):
        print(f"\nVAGA {i}: {guide['empresa']} — {guide['titulo']}")
        print("-" * 70)

        prompt = generate_claude_in_chrome_prompt(guide)

        print("\n📋 COPIE ESTE PROMPT E COLE NO CLAUDE IN CHROME:")
        print("-" * 70)
        print(prompt)
        print("-" * 70)
        print(f"\n🔗 Link da vaga: {guide['url']}")

        print("""
PASSOS:
1. Abra Claude in Chrome (atalho: Alt+C no navegador)
2. COPIE o prompt acima (todo ele)
3. COLE no chat do Claude in Chrome
4. Claude preencherá o formulário automaticamente
5. REVISE as informações
6. CLIQUE em "Submit" quando confirmado
7. Volte para este terminal e pressione ENTER
        """)

        input("Pressione ENTER quando tiver completado a aplicação: ")

        # Registra a aplicação
        record_application(
            empresa=guide["empresa"],
            titulo=guide["titulo"],
            url=guide["url"],
        )

        update_application_status(
            empresa=guide["empresa"],
            titulo=guide["titulo"],
            status="submitted_via_chrome",
            notes=f"Preenchido com Claude in Chrome em {datetime.now().isoformat()}",
        )

        print(f"✅ Aplicação registrada no tracker")

    print("\n" + "=" * 70)
    print("🎉 TODAS AS APLICAÇÕES COMPLETADAS!")
    print("=" * 70)
    print("Rode 'python src/dashboard.py' pra ver o status atualizado")


def run_apply_workflow():
    """Executa o fluxo completo de aplicação."""
    print("\n" + "=" * 70)
    print("JOB HUNT — APPLY AUTOMATION (Semana 6)")
    print("Claude in Chrome + Form Filling")
    print("=" * 70)

    # Carrega aprovações
    approvals = load_latest_approvals()
    if not approvals:
        return False

    approved_count = len(approvals.get("approved_jobs", []))
    print(f"\n✅ Carregadas {approved_count} vaga(s) aprovada(s)")

    # Gera guias
    guides = generate_apply_guides(approvals)

    if not guides:
        print("❌ Nenhum guia foi gerado")
        return False

    # Exibe instruções e fluxo interativo
    display_apply_instructions(guides)

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Job Hunt — Semana 6: Apply Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python src/apply_automation.py              # Fluxo interativo
  python src/apply_automation.py --list       # Lista guias salvos
        """,
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="Lista os guias gerados",
    )

    args = parser.parse_args()

    if args.list:
        guides_file = "digests/form_guides_latest.json"
        if os.path.exists(guides_file):
            with open(guides_file, "r") as f:
                guides = json.load(f)
            print(json.dumps(guides, indent=2, ensure_ascii=False))
        else:
            print("Nenhum guia encontrado. Rode: python src/apply_automation.py")
    else:
        success = run_apply_workflow()
        sys.exit(0 if success else 1)
