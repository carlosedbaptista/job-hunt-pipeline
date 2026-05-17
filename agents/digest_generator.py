"""
digest_generator.py  —  Gera digest diário com top 5 vagas
Salva em arquivo + imprime no terminal pra você ler
"""

import json
import os
from datetime import datetime
from pathlib import Path


def load_evaluations():
    """Carrega as vagas avaliadas."""
    eval_file = "digests/job_evaluations_latest.json"
    if not os.path.exists(eval_file):
        return []

    with open(eval_file, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_digest(max_jobs: int = 5):
    """
    Gera digest diário com as top N vagas.
    Ordena por score (melhor primeiro).
    """
    evaluations = load_evaluations()

    if not evaluations:
        print("❌ Nenhuma vaga avaliada. Rode primeiro: python agents/job_evaluator.py")
        return None

    # Ordena por score (descendente)
    sorted_evals = sorted(evaluations, key=lambda x: x.get("score", 0), reverse=True)
    top_jobs = sorted_evals[:max_jobs]

    timestamp = datetime.now()
    digest = {
        "generated_at": timestamp.isoformat(),
        "total_evaluated": len(evaluations),
        "top_jobs": top_jobs,
    }

    return digest, top_jobs


def format_digest_text(digest: dict, top_jobs: list) -> str:
    """Formata o digest em texto legível."""
    lines = []

    lines.append("=" * 70)
    lines.append("JOB HUNT — DIGEST DIÁRIO")
    lines.append(f"Gerado: {digest['generated_at'][:10]} {digest['generated_at'][11:16]}")
    lines.append("=" * 70)
    lines.append("")

    lines.append(f"Total de vagas avaliadas: {digest['total_evaluated']}")
    lines.append("")

    lines.append("TOP 5 VAGAS (ordenadas por fit score):")
    lines.append("-" * 70)

    for i, job_eval in enumerate(top_jobs, 1):
        score = job_eval.get("score", 0)
        recommendation = job_eval.get("recommendation", "?")
        job = job_eval.get("job", {})

        empresa = job.get("empresa", "N/A")
        titulo = job.get("titulo", "N/A")
        localizacao = job.get("localizacao", "N/A")
        url = job.get("url", "")
        portal = job.get("portal", "")

        # Emoji baseado no recommendation
        icon = "✅" if score >= 65 else "⚠️" if score >= 45 else "❌"

        lines.append("")
        lines.append(f"{i}. {icon} [{score}/100] {empresa}")
        lines.append(f"   Título: {titulo}")
        lines.append(f"   Local: {localizacao} | Portal: {portal}")
        lines.append(f"   Status: {recommendation}")

        # Inclui pontos-chave
        key_points = job_eval.get("key_match_points", [])
        if key_points:
            lines.append(f"   Pontos positivos: {'; '.join(key_points[:2])}")

        # Inclui red flags
        red_flags = job_eval.get("red_flags", [])
        if red_flags:
            lines.append(f"   ⚠️  Problemas: {'; '.join(red_flags[:2])}")

        if url:
            lines.append(f"   Link: {url[:80]}...")

    lines.append("")
    lines.append("=" * 70)
    lines.append("PRÓXIMO PASSO:")
    lines.append('  python src/approval_handler.py --approve "1,3,5"')
    lines.append("(Substitua 1,3,5 pelos números das vagas que quer aplicar)")
    lines.append("=" * 70)
    lines.append("")

    return "\n".join(lines)


def save_digest(digest: dict, text: str):
    """Salva o digest em arquivo."""
    os.makedirs("digests", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    # Salva JSON
    json_file = f"digests/digest_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)

    # Salva texto
    txt_file = f"digests/digest_{timestamp}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(text)

    # Sobrescreve o "latest"
    with open("digests/digest_latest.json", "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)

    with open("digests/digest_latest.txt", "w", encoding="utf-8") as f:
        f.write(text)

    return json_file, txt_file


if __name__ == "__main__":
    result = generate_digest(max_jobs=5)

    if not result:
        exit(1)

    digest, top_jobs = result
    text = format_digest_text(digest, top_jobs)

    # Imprime no terminal
    print(text)

    # Salva em arquivo
    json_file, txt_file = save_digest(digest, text)

    print(f"\n✅ Digest salvo:")
    print(f"   • {json_file}")
    print(f"   • {txt_file}")
    print(f"   • digests/digest_latest.json (latest)")
    print(f"   • digests/digest_latest.txt (latest)")
