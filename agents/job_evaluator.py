"""
job_evaluator.py  —  Subagente: avalia fit de cada vaga
Score 0-100 usando rubrica, Haiku (barato, rápido)
"""

import json
import os
import sys
import anthropic

client = anthropic.Anthropic()

# Positioning de Carlos (resumido)
CARLOS_PROFILE = """
NAME: Carlos Eduardo Duarte Baptista
POSITIONING: Data and business analysis professional, Analyst & AI User (not software developer)
LOCATION: Wallisellen, Zurich (Switzerland)
WORK_PERMIT: Swiss Work Permit B (valid)

KEY_SKILLS:
- Business process analysis & operational data
- Power BI, GA4, Excel, SQL basics
- AI tools daily: Claude, ChatGPT, Gemini
- Stakeholder communication, data visualization
- Cross-functional coordination

BACKGROUND:
- QUOD (Brazil): Business Process Analyst — 40% manual work reduction
- netzdenker.com (Switzerland): Digital Marketing & Analytics Associate (pro bono)
- Education: Postgraduate Data Science (expected Oct 2026)

CERTIFICATIONS:
- Google AI Essentials (2025)
- Anthropic Claude Courses (2026)
- GA4 Certification (2026)

LANGUAGES: Portuguese (native), English (C1), Spanish (B2), German (A2, improving)
"""

EVALUATION_RUBRIC = """
TECHNICAL FIT (40 points max):
  - Role type matches targets (Analyst, BI, Data, Insights, AI): 20pts
  - Tools mentioned match Carlos's skills (Power BI, GA4, Excel, SQL): 10pts
  - AI/data component present: 10pts

CONTEXTUAL FIT (35 points max):
  - Location matches (Zurich area or remote): 15pts
  - Contract type is internship or entry-level: 10pts
  - Language requirement is English (EN+DE where DE is nice-to-have): 10pts

OPPORTUNITY FIT (25 points max):
  - Duration 6-12 months: 10pts
  - Industry is accessible (no clearance, no specific degree required): 10pts
  - Company brand/growth potential: 5pts

DEAL-BREAKERS (auto-score 0, do not apply):
  - Requires German B2+ or C1 as mandatory
  - Location outside Zurich/Zug canton or not remote-friendly
  - Role is pure software engineering, DevOps, or coding-only
  - Requires completed degree Carlos does not have
  - Requires Swiss nationality or clearance
  - Salary below 1500 CHF/month (if stated)
"""

SYSTEM_PROMPT = f"""You are a job fit evaluator for Carlos, a Data & Business Analyst looking for internships in Switzerland.

CARLOS'S PROFILE:
{CARLOS_PROFILE}

EVALUATION RUBRIC:
{EVALUATION_RUBRIC}

Your task: Score this job posting on fit (0-100) using the rubric above.

Return ONLY a valid JSON object. No preamble, no explanation, no markdown.

Output format:
{{
  "score": <0-100>,
  "recommendation": "APPLY | REVIEW | UNCERTAIN",
  "technical_fit": {{"score": <0-40>, "notes": "Brief explanation"}},
  "contextual_fit": {{"score": <0-35>, "notes": "Brief explanation"}},
  "opportunity_fit": {{"score": <0-25>, "notes": "Brief explanation"}},
  "deal_breakers_found": <list of strings or empty list>,
  "key_match_points": <list of 2-3 positive points>,
  "red_flags": <list of 2-3 concerns if any>,
  "suggested_angle": "One sentence on how to frame the cover letter for this role",
  "job_summary_for_user": "2-3 sentence summary of the role"
}}

SCORING THRESHOLDS:
  - Score >= 65: APPLY immediately, generate materials
  - Score 45-64: REVIEW — flag for Carlos to decide
  - Score < 45: UNCERTAIN — describe the job, ask what to do
"""


def evaluate_job(job: dict) -> dict:
    """
    Avalia uma vaga usando Claude Haiku.
    Retorna score 0-100 + recomendações.
    """
    empresa = job.get("empresa", "Unknown")
    titulo = job.get("titulo", "Unknown")
    descricao = job.get("descricao") or "[Sem descrição]"
    localizacao = job.get("localizacao", "Unknown")
    idioma = job.get("idioma", "Unknown")
    url = job.get("url", "")

    user_prompt = f"""Evaluate this job posting:

COMPANY: {empresa}
TITLE: {titulo}
LOCATION: {localizacao}
LANGUAGE: {idioma}
URL: {url}

DESCRIPTION:
{descricao}

Score this job against Carlos's profile and rubric."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        raw_text = response.content[0].text.strip()

        # Clean markdown if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        evaluation = json.loads(raw_text)

        # Preserve original job data
        evaluation["job"] = {
            "empresa": empresa,
            "titulo": titulo,
            "localizacao": localizacao,
            "url": url,
            "portal": job.get("portal", "unknown"),
        }

        return evaluation

    except json.JSONDecodeError as e:
        print(f"  ❌ JSON inválido: {e}")
        return None
    except Exception as e:
        print(f"  ❌ Erro: {e}")
        return None


def evaluate_all_jobs(jobs: list[dict]) -> list[dict]:
    """
    Avalia todas as vagas e retorna scores ordenados.
    """
    evaluations = []
    total = len(jobs)

    for i, job in enumerate(jobs, 1):
        titulo = job.get("titulo", "")[:50]
        print(f"[{i}/{total}] Avaliando: {titulo}...")

        eval_result = evaluate_job(job)
        if eval_result:
            evaluations.append(eval_result)
            score = eval_result.get("score", 0)
            rec = eval_result.get("recommendation", "?")
            print(f"        → Score: {score}/100 ({rec})")
        else:
            print(f"        → Erro na avaliação")

    # Ordena por score descrescente
    evaluations.sort(key=lambda x: x.get("score", 0), reverse=True)
    return evaluations


if __name__ == "__main__":
    input_file = "digests/new_jobs_latest.json"

    if not os.path.exists(input_file):
        print(f"Arquivo não encontrado: {input_file}")
        print("Rode primeiro: python src/pipeline.py")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not jobs:
        print("Nenhuma vaga para avaliar.")
        sys.exit(0)

    print(f"Avaliando {len(jobs)} vagas...\n")
    evaluations = evaluate_all_jobs(jobs)

    os.makedirs("digests", exist_ok=True)
    output = "digests/job_evaluations_latest.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(evaluations)} vagas avaliadas → {output}")

    # Resume
    apply_count = sum(1 for e in evaluations if e.get("score", 0) >= 65)
    review_count = sum(1 for e in evaluations if 45 <= e.get("score", 0) < 65)
    uncertain_count = sum(1 for e in evaluations if e.get("score", 0) < 45)

    print(f"\nRESUMO:")
    print(f"  ✅ APPLY ({apply_count}): {[e['job']['empresa'] for e in evaluations if e.get('score', 0) >= 65]}")
    print(f"  ⚠️  REVIEW ({review_count}): {[e['job']['empresa'] for e in evaluations if 45 <= e.get('score', 0) < 75]}")
    print(f"  ❌ UNCERTAIN ({uncertain_count}): {[e['job']['empresa'] for e in evaluations if e.get('score', 0) < 45]}")
