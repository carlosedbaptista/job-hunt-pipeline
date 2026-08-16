"""
cv_tailor.py  —  Tailors Carlos's CV for each specific role
Keeps 1 page, adjusts emphasis. Uses Claude Sonnet for quality.
"""

import json
import os
import sys
sys.path.insert(0, "../src")
sys.path.insert(0, "./src")
from kimi_client import call_kimi
from dotenv import load_dotenv

load_dotenv()

def load_cv_base() -> str:
    """Base CV for tailoring.

    Priority: config/cv_model.txt (the candidate's real template, kept out of git).
    Fallback: builds it from config/candidate_profile.json.
    """
    if os.path.exists("config/cv_model.txt"):
        with open("config/cv_model.txt", encoding="utf-8") as f:
            return f.read().strip()

    try:
        with open("config/candidate_profile.json", encoding="utf-8") as f:
            p = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""

    lines = [
        p.get("name", "").upper(),
        f"{p.get('address', '')} | {p.get('phone', '')}",
        f"{p.get('email', '')} | {p.get('linkedin', '')}",
        f"DOB: {p.get('dob', '')} | Nationality: {p.get('nationality', '')} | {p.get('permit', '')}",
        "",
        "PROFESSIONAL EXPERIENCE",
    ]
    for exp in p.get("experience", []):
        lines.append(f"\n{exp.get('title', '')}")
        lines.append(f"{exp.get('company', '')} | {exp.get('period', '')}")
        for b in exp.get("bullets", []):
            lines.append(f"- {b}")
    lines.append("\nEDUCATION")
    for edu in p.get("education", []):
        lines.append(f"\n{edu.get('degree', '')}")
        lines.append(f"{edu.get('institution', '')} | {edu.get('period', '')}")
    skills = p.get("skills", {})
    lines.append("\nTECHNICAL SKILLS")
    lines.append(", ".join(skills.get("technical_default", [])))
    certs = skills.get("certifications", [])
    if certs:
        lines.append("\nCERTIFICATIONS")
        lines.append(" | ".join(certs))
    return "\n".join(lines)

SYSTEM_PROMPT = """You are a CV tailor for Carlos. Your task:

1. KEEP the CV structure and length (1 page, ~400-500 words)
2. EMPHASIZE skills relevant to this specific role
3. HIGHLIGHT experience that matches job requirements
4. REORGANIZE bullet points to lead with most relevant achievements

RULES:
- Never add fake experience
- Never change dates or facts
- Follow the STRUCTURE, tone and formatting of the BASE CV exactly (same sections, same style)
- Keep certifications section (always valuable)
- Keep skills section, but REORDER by relevance to job
- Adjust language to match job posting language
- Maximum 1 page when printed
- Maintain professional tone

OUTPUT: Return the tailored CV as plain text, ready to save as .txt or paste into Word."""


def tailor_cv(job: dict, evaluation: dict) -> str:
    """Tailors Carlos's CV for a specific job."""
    company = job.get("company", "")
    title = job.get("title", "")
    description = job.get("description", "[No description]")
    language = job.get("language", "en")

    suggested_angle = evaluation.get("suggested_angle", "")

    user_prompt = f"""Tailor this CV for the job below:

BASE CV:
{load_cv_base()}

COMPANY: {company}
TITLE: {title}
JOB_DESCRIPTION: {description}

SUGGESTED ANGLE:
{suggested_angle}

Language: Use {'German' if language.lower() == 'de' else 'English'} in the CV.

Emphasize:
- Data analysis & insights experience
- Power BI / GA4 tools if relevant
- AI integration (Claude, ChatGPT daily usage)
- Business stakeholder communication
- Relevant certifications

Reorder the Professional Experience and Skills sections to lead with the most relevant items for this {title} role.

Keep it concise, 1 page."""

    try:
        return call_kimi(
            user_prompt,
            system=SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=1200,
        )

    except Exception as e:
        print(f"    ❌ Error tailoring CV: {e}")
        return None


def tailor_all_cvs(evaluations: list[dict], jobs_dict: dict) -> list[dict]:
    """Tailors CVs only for jobs with score >= 80 (APPLY)."""
    tailored = []
    apply_jobs = [e for e in evaluations if e.get("score", 0) >= 80]

    if not apply_jobs:
        print("No jobs with score >= 80. Nothing to tailor.")
        return []

    print(f"Tailoring CVs for {len(apply_jobs)} job(s)...\n")

    for i, eval_result in enumerate(apply_jobs, 1):
        job_key = eval_result.get("job", {}).get("company", "")
        job = jobs_dict.get(job_key)

        if not job:
            print(f"[{i}] Warning: job data not found for {job_key}")
            continue

        company = job.get("company", "")
        title = job.get("title", "")[:50]

        print(f"[{i}] Tailoring CV for {company} — {title}...")

        cv = tailor_cv(job, eval_result)

        if cv:
            cv_item = {
                "company": company,
                "title": job.get("title", ""),
                "cv_tailored": cv,
                "url": job.get("url", ""),
                "score": eval_result.get("score", 0),
            }
            tailored.append(cv_item)
            print(f"    ✅ CV tailored")
        else:
            print(f"    ❌ Failed to tailor")

    return tailored


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

    jobs_dict = {j["company"]: j for j in jobs_list}

    print("Tailoring CVs...\n")
    tailored_cvs = tailor_all_cvs(evaluations, jobs_dict)

    if tailored_cvs:
        os.makedirs("digests", exist_ok=True)
        output = "digests/tailored_cvs_latest.json"
        with open(output, "w", encoding="utf-8") as f:
            json.dump(tailored_cvs, f, ensure_ascii=False, indent=2)

        print(f"\n✅ {len(tailored_cvs)} CV(s) tailored → {output}")

        print(f"\nFirst CV preview (first 10 lines):")
        print("=" * 60)
        print("\n".join(tailored_cvs[0]["cv_tailored"].split("\n")[:10]))
        print("=" * 60)
    else:
        print("\nNo CVs tailored.")
