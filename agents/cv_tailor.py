"""
cv_tailor.py  —  Subagente: adapta CV para cada role
Mantém 1 página, ajusta ênfase, Sonnet pra qualidade
"""

import json
import os
import sys
import anthropic

client = anthropic.Anthropic()

# CV base de Carlos (versão texto)
CARLOS_CV_BASE = """
CARLOS EDUARDO DUARTE BAPTISTA
Alte Winterthurerstrasse 107, 8304 Wallisellen | +41 78 261 34 74
carlosedbaptista@gmail.com | linkedin.com/in/carlosedbaptista
DOB: 10.03.1999 | Nationality: Brazilian | Swiss Work Permit B (valid)

PROFILE
Data and business analysis professional completing a Postgraduate degree in Data Science. Experienced in translating operational data into structured insights that support business decisions. Uses Claude, ChatGPT, and Gemini as core professional tools daily to improve analytical workflows and content quality.

PROFESSIONAL EXPERIENCE

Digital Marketing & Analytics Associate (Pro Bono, 20h/week)
netzdenker.com — Wallisellen, Switzerland | 06.2025–Present
- Produced presentations and structured documentation to support stakeholder engagement
- Used AI tools to improve content quality, automate reporting workflows, adapt communication
- Coordinated operational workflows and supported cross-functional collaboration

Operations Support Associate (Freelancer)
Coople (Schweiz) AG — Switzerland | 06.2025–Present
- Customer-facing service and operations support in dynamic event environments
- Adapted quickly to diverse operational contexts in multilingual Swiss work environment

NetSuite Developer & Business Process Analyst (Internship)
Gestora de Inteligência de Crédito S.A. (QUOD) — São Paulo, Brazil | 03.2023–11.2024
- Worked as Business Process Analyst coordinating cross-functional teams
- Contributed to process transformation initiative that reduced manual work by 40%
- Coordinated stakeholder communication and supported user adoption

IT Resident (Technology Training Program)
BRISA / CIEDS — Rio de Janeiro, Brazil | 05.2023–01.2024
- Co-developed full-stack event management platform including data modeling, backend logic, workflow structure
- Delivered 65% of project scope within program timeline

Administrative Support Intern
Criminal Registry — High Court of Rio de Janeiro, Brazil | 04.2021–01.2023
- Contributed to digitization of criminal case archive: team virtualized 90% of physical records (2,000+ cases)
- Managed digital workflow within electronic case management system

EDUCATION

Postgraduate Studies in Data Science (expected 10.2026)
UNIAMERICA University — Remote

Bachelor's Degree in System Analysis and Development (12.2024)
UNIAMERICA University — Rio de Janeiro, Brazil

TECHNICAL SKILLS
MS Office (PowerPoint, Excel, SharePoint), AI Tools (Claude, ChatGPT, Gemini), Jira, Power BI, GA4, Data Modeling, Oracle NetSuite

CERTIFICATIONS
Google AI Essentials (2025) | Anthropic Claude Courses (2026) | GA4 Certification (2026)

LANGUAGES
Portuguese (native) | English (C1 Advanced) | Spanish (B2 Intermediate) | German (A2, improving)
"""

SYSTEM_PROMPT = """You are a CV tailor for Carlos. Your task:

1. KEEP the CV structure and length (1 page, ~400-500 words)
2. EMPHASIZE skills relevant to this specific role
3. HIGHLIGHT experience that matches job requirements
4. REORGANIZE bullet points to lead with most relevant achievements

RULES:
- Never add fake experience
- Never change dates or facts
- Keep certifications section (always valuable)
- Keep skills section, but REORDER by relevance to job
- Adjust language to match job posting language
- Maximum 1 page when printed
- Maintain professional tone

OUTPUT: Return the tailored CV as plain text, ready to save as .txt or paste into Word."""


def tailor_cv(job: dict, evaluation: dict) -> str:
    """
    Adapta o CV de Carlos pra uma vaga específica.
    """
    empresa = job.get("empresa", "")
    titulo = job.get("titulo", "")
    descricao = job.get("descricao", "[Sem descrição]")
    idioma = job.get("idioma", "en")

    suggested_angle = evaluation.get("suggested_angle", "")

    user_prompt = f"""Tailor Carlos's CV for this job:

COMPANY: {empresa}
TITLE: {titulo}
JOB_DESCRIPTION: {descricao}

SUGGESTED ANGLE:
{suggested_angle}

Language: Use {'German' if idioma.lower() == 'de' else 'English'} in the CV.

Emphasize:
- Data analysis & insights experience
- Power BI / GA4 tools if relevant
- AI integration (Claude, ChatGPT daily usage)
- Business stakeholder communication
- Relevant certifications

Reorder the Professional Experience and Skills sections to lead with the most relevant items for this {titulo} role.

Keep it concise, 1 page."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        tailored_cv = response.content[0].text.strip()
        return tailored_cv

    except Exception as e:
        print(f"    ❌ Erro ao adaptar CV: {e}")
        return None


def tailor_all_cvs(evaluations: list[dict], jobs_dict: dict) -> list[dict]:
    """
    Adapta CVs apenas para vagas com score >= 75.
    """
    tailored = []
    apply_jobs = [e for e in evaluations if e.get("score", 0) >= 75]

    if not apply_jobs:
        print("Nenhuma vaga com score >= 75. Nada pra adaptar.")
        return []

    print(f"Adaptando CVs para {len(apply_jobs)} vaga(s)...\n")

    for i, eval_result in enumerate(apply_jobs, 1):
        job_key = eval_result.get("job", {}).get("empresa", "")
        job = jobs_dict.get(job_key)

        if not job:
            print(f"[{i}] ⚠️  Job data não encontrado para {job_key}")
            continue

        empresa = job.get("empresa", "")
        titulo = job.get("titulo", "")[:50]

        print(f"[{i}] Adaptando CV para {empresa} — {titulo}...")

        cv = tailor_cv(job, eval_result)

        if cv:
            cv_item = {
                "empresa": empresa,
                "titulo": job.get("titulo", ""),
                "cv_tailored": cv,
                "url": job.get("url", ""),
                "score": eval_result.get("score", 0),
            }
            tailored.append(cv_item)
            print(f"    ✅ CV adaptado")
        else:
            print(f"    ❌ Falha ao adaptar")

    return tailored


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

    jobs_dict = {j["empresa"]: j for j in jobs_list}

    print(f"Adaptando CVs...\n")
    tailored_cvs = tailor_all_cvs(evaluations, jobs_dict)

    if tailored_cvs:
        os.makedirs("digests", exist_ok=True)
        output = "digests/tailored_cvs_latest.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(tailored_cvs, f, ensure_ascii=False, indent=2)

        print(f"\n✅ {len(tailored_cvs)} CV(s) adaptado(s) → {output}")

        # Preview
        print(f"\nPrimeiro CV (primeiras linhas):")
        print("=" * 60)
        print(tailored_cvs[0]["cv_tailored"].split("\n")[:10])
        print("=" * 60)
    else:
        print("\nNenhum CV adaptado.")
