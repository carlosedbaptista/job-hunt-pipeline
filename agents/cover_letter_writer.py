"""
cover_letter_writer.py  —  Generates tailored cover letters for high-fit jobs
Uses Claude Sonnet. Runs only for jobs with score >= 80.
"""

import json
import os
import sys
sys.path.insert(0, "../src")
sys.path.insert(0, "./src")
from kimi_client import call_kimi
from dotenv import load_dotenv

load_dotenv()

CARLOS_VOICE = """
TONE: Professional but human. Direct, specific, honest.
STYLE: Shows genuine interest. Never generic.
BACKGROUND_SUMMARY:
  - Brazilian based in Zurich Area, Swiss Work Permit B (no sponsorship), 2 weeks' notice
  - Career changer: Law (Brazilian High Court) -> software engineering, driven by data & automation
  - Currently: Data & Analytics Intern at netzdenker.com (Swiss digital agency) -- builds and maintains
    agentic AI workflows, LLM tool-use and data pipelines in production (Python, JavaScript, CI/CD)
  - Before: Business Process & NetSuite Developer at QUOD (credit bureau, Brazil) -- ~40% less manual data entry
  - Postgraduate specialisation in Data Science (ML, statistical modelling) -- expected Oct 2026
  - Built a full agentic AI pipeline solo (ingestion -> LLM scoring -> dashboard -> alerts, CI/CD on GitHub Actions)

KEY_SELLING_POINTS:
  1. Hands-on agentic AI in production — builds and maintains LLM workflows, not just "familiar with AI"
  2. Career-change story (Law -> tech) — learns new domains fast
  3. Swiss Work Permit B valid — zero complications
  4. Quantified results (~40% reduction in manual data entry at QUOD)
  5. Actively learning (Data Science postgrad, AI Essentials, Claude Courses, GA4)

WHAT TO EMPHASIZE:
  - For AI/platform roles: agentic workflows, LLM tool-use orchestration, CI/CD for AI, own pipeline project
  - For Data/BI roles: data pipelines, Power BI, GA4, statistical modelling
  - For Analytics roles: business insights, stakeholder communication
  - Always: genuine interest in THIS company (research 2-3 facts)
"""

SYSTEM_PROMPT = f"""You are a cover letter writer for Carlos, an AI Platform Engineer (agentic AI, LLM workflows, data pipelines).

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
  - Signed with the candidate full name from the candidate profile

OUTPUT: Return the cover letter as plain text, ready to copy-paste. No markdown, no headers."""


def _candidate_name() -> str:
    try:
        with open("config/candidate_profile.json", encoding="utf-8") as f:
            return json.load(f).get("name", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def _cl_model() -> str:
    """Candidate's real cover letter model (config/cover_letter_model.txt, not in git)."""
    if os.path.exists("config/cover_letter_model.txt"):
        with open("config/cover_letter_model.txt", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def generate_cover_letter(job: dict, evaluation: dict) -> str:
    """Generates a tailored cover letter for a high-fit job."""
    company = job.get("company", "")
    title = job.get("title", "")
    location = job.get("location", "")
    language = job.get("language", "en")
    description = job.get("description") or "[No description available]"

    lang_name = "English" if language in ("en", "english") else "German" if language in ("de", "deutsch") else "English"

    suggested_angle = evaluation.get("suggested_angle", "")

    cl_model = _cl_model()
    model_block = (
        f"\n\nREFERENCE COVER LETTER (match this structure, voice and opening style — personal story hook, "
        f"concrete achievements, honest motivation — but write about THIS company):\n{cl_model}\n"
        if cl_model else ""
    )

    user_prompt = f"""Write a cover letter for this job:

CANDIDATE NAME (sign the letter with it): {_candidate_name()}

COMPANY: {company}
TITLE: {title}
LOCATION: {location}
LANGUAGE: {lang_name}
JOB_DESCRIPTION: {description}

SUGGESTED ANGLE (from fit evaluation):
{suggested_angle}
{model_block}
Write in {lang_name}. Make it specific to {company} and this {title} role.
Research fact: [{company} is likely in {location}. What is their business?]
Show genuine interest, not generic enthusiasm."""

    try:
        return call_kimi(
            user_prompt,
            system=SYSTEM_PROMPT,
            temperature=0.4,
            max_tokens=1000,
        )

    except Exception as e:
        print(f"    ❌ Error generating cover letter: {e}")
        return None


def generate_materials(evaluations: list[dict], jobs_dict: dict) -> list[dict]:
    """Generates cover letters only for jobs with score >= 80 (APPLY)."""
    materials = []
    apply_jobs = [e for e in evaluations if e.get("score", 0) >= 80]

    if not apply_jobs:
        print("No jobs with score >= 80. Nothing to generate.")
        return []

    print(f"Generating cover letters for {len(apply_jobs)} job(s)...\n")

    for i, eval_result in enumerate(apply_jobs, 1):
        job_key = eval_result.get("job", {}).get("company", "")
        job = jobs_dict.get(job_key)

        if not job:
            print(f"[{i}] Warning: job data not found for {job_key}")
            continue

        company = job.get("company", "")
        title = job.get("title", "")[:50]

        print(f"[{i}] Generating cover letter for {company} — {title}...")

        cover_letter = generate_cover_letter(job, eval_result)

        if cover_letter:
            material = {
                "company": company,
                "title": job.get("title", ""),
                "location": job.get("location", ""),
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

    jobs_dict = {j["company"]: j for j in jobs_list}

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
