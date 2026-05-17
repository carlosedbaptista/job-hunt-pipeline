"""
cover_letter_writer.py  —  Subagente: gera cover letters customizadas
Usa Claude Sonnet (qualidade melhor), roda apenas em vagas com score >= 75
"""

import json
import os
import sys
import anthropic

client = anthropic.Anthropic()

# Positioning de Carlos (para tom e voz)
CARLOS_VOICE = """
TONE: Professional but human. Direct, specific, honest.
STYLE: Shows genuine interest. Never generic.
BACKGROUND_SUMMARY:
  - Brazilian based in Zurich (Wallisellen)
  - Business process analyst at QUOD (Brazil) — 40% manual work reduction
  - Currently: Digital Marketing & Analytics Associate (pro bono at netzdenker.com)
  - Postgraduate in Data Science (expected Oct 2026)
  - STRONG AI integration: uses Claude, ChatGPT, Gemini daily as professional tools
  
KEY_SELLING_POINTS:
  1. Real AI integration — not just "familiar", uses as daily tools
  2. Cross-cultural & multilingual (Portuguese native, English C1, German improving)
  3. Swiss Work Permit B valid — zero complications
  4. Quantified results (40% reduction in manual work)
  5. Actively learning (AI Essentials, Claude Courses, GA4)

WHAT TO EMPHASIZE:
  - For Data/BI roles: Power BI, GA4, data storytelling
  - For Analytics roles: business insights, stakeholder communication
  - For AI roles: daily Claude/ChatGPT usage, prompt engineering
  - Always: genuine interest in THIS company (research 2-3 facts)
"""

SYSTEM_PROMPT = f"""You are a cover letter writer for Carlos, a Data & Business Analyst.

CARLOS'S VOICE & POSITIONING:
{CARLOS_VOICE}

Your task: Write a SHORT (3-4 paragraphs), authentic cover letter that:
  1. Opens with ONE company-specific fact (shows research)
  2. Connects Carlos's background to THIS role
  3. Emphasizes his AI integration & data skills
  4. Closes with enthusiasm for THIS company (not generic)

RULES:
  - Language: Match the job posting language (English if bilingual)
  - Length: 250-350 words ONLY (one page, concise)
  - Tone: Professional but warm, like talking to a smart colleague
  - Never generic phrases ("I am excited to...")
  - Always specific: "Your analytics work on X impressed me because..."
  - Signed: "Carlos Eduardo Duarte Baptista"

OUTPUT: Return the cover letter as plain text, ready to copy-paste. No markdown, no headers."""


def generate_cover_letter(job: dict, evaluation: dict) -> str:
    """
    Gera uma cover letter customizada para uma vaga de alto fit.
    """
    empresa = job.get("empresa", "")
    titulo = job.get("titulo", "")
    localizacao = job.get("localizacao", "")
    idioma = job.get("idioma", "en")
    url = job.get("url", "")
    descricao = job.get("descricao") or "[Sem descrição disponível]"

    # Detecta língua
    lang_name = "English" if idioma in ("en", "english") else "German" if idioma in ("de", "deutsch") else "English"

    suggested_angle = evaluation.get("suggested_angle", "")

    user_prompt = f"""Write a cover letter for this job:

COMPANY: {empresa}
TITLE: {titulo}
LOCATION: {localizacao}
LANGUAGE: {lang_name}
JOB_DESCRIPTION: {descricao}

SUGGESTED ANGLE (from fit evaluation):
{suggested_angle}

Write in {lang_name}. Make it specific to {empresa} and this {titulo} role.
Research fact: [{empresa} is likely in {localizacao}. What is their business?]
Show genuine interest, not generic enthusiasm."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        cover_letter = response.content[0].text.strip()
        return cover_letter

    except Exception as e:
        print(f"    ❌ Erro ao gerar cover letter: {e}")
        return None


def generate_materials(evaluations: list[dict], jobs_dict: dict) -> list[dict]:
    """
    Gera cover letters apenas para vagas com score >= 75 (APPLY).
    """
    materials = []
    apply_jobs = [e for e in evaluations if e.get("score", 0) >= 75]

    if not apply_jobs:
        print("Nenhuma vaga com score >= 75. Nada pra gerar.")
        return []

    print(f"Gerando materiais para {len(apply_jobs)} vaga(s)...\n")

    for i, eval_result in enumerate(apply_jobs, 1):
        job_key = eval_result.get("job", {}).get("empresa", "")
        job = jobs_dict.get(job_key)

        if not job:
            print(f"[{i}] ⚠️  Job data não encontrado para {job_key}")
            continue

        empresa = job.get("empresa", "")
        titulo = job.get("titulo", "")[:50]

        print(f"[{i}] Gerando cover letter para {empresa} — {titulo}...")

        cover_letter = generate_cover_letter(job, eval_result)

        if cover_letter:
            material = {
                "empresa": empresa,
                "titulo": job.get("titulo", ""),
                "localizacao": job.get("localizacao", ""),
                "score": eval_result.get("score", 0),
                "cover_letter": cover_letter,
                "url": job.get("url", ""),
                "evaluation": eval_result,
            }
            materials.append(material)
            print(f"    ✅ Cover letter gerada")
        else:
            print(f"    ❌ Falha ao gerar")

    return materials


if __name__ == "__main__":
    eval_file = "digests/job_evaluations_latest.json"
    jobs_file = "digests/new_jobs_latest.json"

    if not os.path.exists(eval_file) or not os.path.exists(jobs_file):
        print(f"Arquivos não encontrados.")
        print("Rode primeiro: python agents/job_evaluator.py")
        sys.exit(1)

    with open(eval_file, "r", encoding="utf-8") as f:
        evaluations = json.load(f)

    with open(jobs_file, "r", encoding="utf-8") as f:
        jobs_list = json.load(f)

    # Index jobs by company name
    jobs_dict = {j["empresa"]: j for j in jobs_list}

    print(f"Gerando cover letters...\n")
    materials = generate_materials(evaluations, jobs_dict)

    if materials:
        os.makedirs("digests", exist_ok=True)
        output = "digests/cover_letters_latest.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(materials, f, ensure_ascii=False, indent=2)

        print(f"\n✅ {len(materials)} cover letter(s) gerada(s) → {output}")

        # Preview
        print(f"\nPrimeira cover letter:")
        print("=" * 60)
        print(materials[0]["cover_letter"][:400] + "...")
        print("=" * 60)
    else:
        print("\nNenhum material gerado.")
