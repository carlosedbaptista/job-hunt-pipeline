"""
cover_letter_writer.py  —  Generates tailored cover letters for high-fit jobs
Uses Claude Sonnet. Runs only for jobs with score >= 65.
"""

import json
import os
import sys
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

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
    """Generates a tailored cover letter for a high-fit job."""
    empresa = job.get("empresa", "")
    titulo = job.get("titulo", "")
    localizacao = job.get("localizacao", "")
    idioma = job.get("idioma", "en")
    descricao = job.get("descricao") or "[No description available]"

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

        return response.content[0].text.strip()

    except Exception as e:
        print(f"    ❌ Error generating cover letter: {e}")
        return None


def generate_materials(evaluations: list[dict], jobs_dict: dict) -> list[dict]:
    """Generates cover letters only for jobs with score >= 65 (APPLY)."""
    materials = []
    apply_jobs = [e for e in evaluations if e.get("score", 0) >= 65]

    if not apply_jobs:
        print("No jobs with score >= 65. Nothing to generate.")
        return []

    print(f"Generating cover letters for {len(apply_jobs)} job(s)...\n")

    for i, eval_result in enumerate(apply_jobs, 1):
        job_key = eval_result.get("job", {}).get("empresa", "")
        job = jobs_dict.get(job_key)

        if not job:
            print(f"[{i}] Warning: job data not found for {job_key}")
            continue

        empresa = job.get("empresa", "")
        titulo = job.get("titulo", "")[:50]

        print(f"[{i}] Generating cover letter for {empresa} — {titulo}...")

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
            print(f"    ✅ Cover letter generated")
        else:
            print(f"    ❌ Failed to generate")

    return materials


if __name__ == "__main__":
    eval_file = "digests/job_evaluations_latest.json"
    jobs_file = "digests/new_jobs_latest.json"

    if not os.path.exists(eval_file) or not os.path.exists(jobs_file):
        print("Required files not found.")
        print("Run first: python agents/job_evaluator.py")
        sys.exit(1)

    with open(eval_file, "r", encoding="utf-8") as f:
        evaluations = json.load(f)

    with open(jobs_file, "r", encoding="utf-8") as f:
        jobs_list = json.load(f)

    jobs_dict = {j["empresa"]: j for j in jobs_list}

    print("Generating cover letters...\n")
    materials = generate_materials(evaluations, jobs_dict)

    if materials:
        os.makedirs("digests", exist_ok=True)
        output = "digests/cover_letters_latest.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(materials, f, ensure_ascii=False, indent=2)

        print(f"\n✅ {len(materials)} cover letter(s) generated → {output}")

        print(f"\nFirst cover letter preview:")
        print("=" * 60)
        print(materials[0]["cover_letter"][:400] + "...")
        print("=" * 60)
    else:
        print("\nNo materials generated.")
