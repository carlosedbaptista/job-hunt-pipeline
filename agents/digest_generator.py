"""
digest_generator.py  --  Generates a daily digest with the top N evaluated jobs
"""
import json
import os
from datetime import datetime


def load_evaluations():
    eval_file = "digests/job_evaluations_latest.json"
    if not os.path.exists(eval_file):
        return []
    with open(eval_file, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_job_field(eval_item, field, default="N/A"):
    """Extrai campo da avaliacao -- suporta formato aninhado OU direto."""
    job = eval_item.get("job")
    if job and isinstance(job, dict):
        val = job.get(field)
        if val:
            return val
        en_map = {"empresa": "company", "titulo": "title", "localizacao": "location"}
        if field in en_map:
            val = job.get(en_map[field])
            if val:
                return val
    val = eval_item.get(field)
    if val:
        return val
    en_map = {"empresa": "company", "titulo": "title", "localizacao": "location"}
    if field in en_map:
        val = eval_item.get(en_map[field])
        if val:
            return val
    return default


def generate_digest(max_jobs=5):
    evaluations = load_evaluations()
    if not evaluations:
        print("X No jobs evaluated. Run first: python agents/job_evaluator.py")
        return None

    sorted_evals = sorted(evaluations, key=lambda x: x.get("score", 0), reverse=True)
    top_jobs = sorted_evals[:max_jobs]

    timestamp = datetime.now()
    digest = {
        "generated_at": timestamp.isoformat(),
        "total_evaluated": len(evaluations),
        "top_jobs": top_jobs,
    }
    return digest, top_jobs


def format_digest_text(digest, top_jobs):
    lines = []
    lines.append("=" * 70)
    lines.append("JOB HUNT -- DAILY DIGEST")
    lines.append(f"Generated: {digest['generated_at'][:10]} {digest['generated_at'][11:16]}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Total jobs evaluated: {digest['total_evaluated']}")
    lines.append("")
    lines.append("TOP JOBS (sorted by fit score):")
    lines.append("-" * 70)

    for i, job_eval in enumerate(top_jobs, 1):
        score = job_eval.get("score", 0)
        recommendation = job_eval.get("recommendation", job_eval.get("decision", "?"))

        empresa = _get_job_field(job_eval, "empresa")
        titulo = _get_job_field(job_eval, "titulo")
        localizacao = _get_job_field(job_eval, "localizacao")
        url = _get_job_field(job_eval, "url")
        portal = _get_job_field(job_eval, "portal")

        icon = ">>>" if score >= 65 else "!!" if score >= 45 else "XXX"

        lines.append("")
        lines.append(f"{i}. {icon} [{score}/100] {empresa}")
        lines.append(f"   Title: {titulo}")
        lines.append(f"   Location: {localizacao} | Source: {portal}")
        lines.append(f"   Status: {recommendation}")

        key_points = job_eval.get("key_match_points", [])
        if key_points:
            lines.append(f"   Highlights: {'; '.join(key_points[:2])}")

        red_flags = job_eval.get("red_flags", [])
        if red_flags:
            lines.append(f"   !!  Issues: {'; '.join(red_flags[:2])}")

        if url and url != "N/A":
            lines.append(f"   Link: {url[:80]}...")

    lines.append("")
    lines.append("=" * 70)
    lines.append("NEXT STEP:")
    lines.append('  python src/approval_handler.py --approve "1,3,5"')
    lines.append("(Replace 1,3,5 with the job numbers you want to apply to)")
    lines.append("=" * 70)
    lines.append("")
    return "\n".join(lines)


def save_digest(digest, text):
    os.makedirs("digests", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    json_file = f"digests/digest_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(digest, f, ensure_ascii=False, indent=2)

    txt_file = f"digests/digest_{timestamp}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write(text)

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
    print(text)
    json_file, txt_file = save_digest(digest, text)
    print(f"\nOK Digest saved:")
    print(f"   * {json_file}")
    print(f"   * {txt_file}")
    print(f"   * digests/digest_latest.json (latest)")
    print(f"   * digests/digest_latest.txt (latest)")
