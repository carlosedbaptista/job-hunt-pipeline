#!/usr/bin/env python3
"""
job_evaluator.py  —  Scores each job for fit against Carlos's profile
Uses Kimi K2-6 for evaluation.
"""

import json
import os
import sys
sys.path.insert(0, "../src")
sys.path.insert(0, "./src")
from kimi_client import call_kimi_json

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
    """Evaluates a single job using Kimi K2-6. Returns score 0-100 plus analysis."""
    empresa = job.get("empresa", "Unknown")
    titulo = job.get("titulo", "Unknown")
    descricao = job.get("descricao") or "[No description]"
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
        evaluation = call_kimi_json(
            user_prompt,
            system=SYSTEM_PROMPT,
            max_tokens=1500,
        )

        evaluation["job"] = {
            "empresa": empresa,
            "titulo": titulo,
            "localizacao": localizacao,
            "url": url,
            "portal": job.get("portal", "unknown"),
        }

        return evaluation

    except json.JSONDecodeError as e:
        print(f"  ❌ Invalid JSON: {e}")
        return None
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return None


def evaluate_all_jobs(jobs: list[dict], max_jobs: int = 10) -> list[dict]:
    """Evaluates jobs and returns results sorted by score descending."""
    evaluations = []
    total = len(jobs)
    to_eval = jobs[:max_jobs]

    if total > max_jobs:
        print(f"⚡ Limitando a {max_jobs} vagas (de {total} total)")

    for i, job in enumerate(to_eval, 1):
        titulo = (job.get("titulo") or "")[:50]
        print(f"[{i}/{len(to_eval)}] Evaluating: {titulo}...")

        eval_result = evaluate_job(job)
        if eval_result:
            evaluations.append(eval_result)
            score = eval_result.get("score", 0)
            rec = eval_result.get("recommendation", "?")
            print(f"        → Score: {score}/100 ({rec})")
        else:
            print(f"        → Evaluation error")

    evaluations.sort(key=lambda x: x.get("score", 0), reverse=True)
    return evaluations


def generate_cv(title: str, company: str, description: str) -> str:
    """Generates a tailored CV markdown for a specific job."""
    prompt = f"""Gere CV markdown 1 pagina para Carlos Eduardo Duarte Baptista (Data Analyst, Wallisellen CH, Permit B, 2 weeks notice, carlosedbaptista@gmail.com, +41 78 261 34 74, linkedin.com/in/carlosedbaptista). Experiencias: QUOD (40% reducao manual, SQL/Python/Power BI), netzdenker.com (Power BI/GA4/AI workflows). Educacao: Pos Data Science (out/2026), Bacharel Sistemas. Certificacoes: Google AI Essentials, Anthropic Claude, GA4. Idiomas: PT nativo, EN C1, ES B2, DE A2. Adapte para vaga: {title} em {company}. Descricao: {description[:2000]}. APENAS markdown."""

    from kimi_client import call_kimi
    return call_kimi(
        prompt,
        system="Redator de CV/cover letter. Tom profissional, direto. CV 1 pagina. Cover 3 paragrafos. NUNCA minta.",
        max_tokens=2048,
    )


def generate_cover_letter(title: str, company: str, description: str) -> str:
    """Generates a tailored cover letter for a specific job."""
    prompt = f"""Gere cover letter (3 paragrafos, max 250 palavras) de Carlos Eduardo Duarte Baptista para {company} - {title}. Paragrafo 1: por que empresa/role. Paragrafo 2: match habilidades (SQL, Python, Power BI, GA4, automacao IA), mencione 40% reducao QUOD e perfil cross-cultural BR->CH. Paragrafo 3: call to action, 2 weeks notice. Contato: carlosedbaptista@gmail.com | +41 78 261 34 74. APENAS texto."""

    from kimi_client import call_kimi
    return call_kimi(
        prompt,
        system="Redator de CV/cover letter. Tom profissional, direto. CV 1 pagina. Cover 3 paragrafos. NUNCA minta.",
        max_tokens=1024,
    )


if __name__ == "__main__":
    input_file = "digests/new_jobs_latest.json"

    if not os.path.exists(input_file):
        print(f"File not found: {input_file}")
        print("Run first: python src/pipeline.py")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as f:
        jobs = json.load(f)

    if not jobs:
        print("No jobs to evaluate.")
        sys.exit(0)

    print(f"Evaluating {len(jobs)} jobs...\n")
    evaluations = evaluate_all_jobs(jobs)

    os.makedirs("digests", exist_ok=True)
    output = "digests/job_evaluations_latest.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {len(evaluations)} jobs evaluated → {output}")

    apply_count = sum(1 for e in evaluations if e.get("score", 0) >= 65)
    review_count = sum(1 for e in evaluations if 45 <= e.get("score", 0) < 65)
    uncertain_count = sum(1 for e in evaluations if e.get("score", 0) < 45)

    print(f"\nSUMMARY:")
    print(f"  ✅ APPLY ({apply_count}): {[e['job']['empresa'] for e in evaluations if e.get('score', 0) >= 65]}")
    print(f"  ⚠️  REVIEW ({review_count}): {[e['job']['empresa'] for e in evaluations if 45 <= e.get('score', 0) < 65]}")
    print(f"  ❌ UNCERTAIN ({uncertain_count}): {[e['job']['empresa'] for e in evaluations if e.get('score', 0) < 45]}")
