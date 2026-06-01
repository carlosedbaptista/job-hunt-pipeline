"""
job_evaluator.py — Mini-batches de 3 vagas por chamada Kimi
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json

PROFILE = """
Candidate Profile:
- Name: Carlos Eduardo Duarte Baptista
- Role: Data and Business Analysis Professional
- Location: Wallisellen, Switzerland (Permit B)
- Notice period: 2 weeks
- Languages: PT (native), EN (C1), ES (B2), DE (A2)
- Skills: SQL, Python, Power BI, GA4, automation with AI
- Experience: QUOD (40% manual reduction), netzdenker.com (Analytics)
- Education: Postgraduate Data Science (Oct 2026), Bachelor Systems
- Certifications: Google AI Essentials, Anthropic Claude, GA4
"""

SYSTEM_PROMPT = """You are a job fit evaluator. Evaluate each job against the candidate profile.
Respond ONLY with a valid JSON array. Each element must be an object with:
{
  "empresa": "same as input", "titulo": "same as input", "url": "same as input",
  "score": 0-100, "technical_fit": "brief justification", "contextual_fit": "brief justification",
  "salary_estimate": "salary range if mentioned, else 'Not disclosed'",
  "culture_fit": "brief note", "concerns": ["list or empty"],
  "decision": "APPLY" or "REVIEW" or "SKIP",
  "materials_needed": ["cv", "cover_letter", "recommendation"],
  "portuguese_comment": "brief comment in Portuguese"
}
Scoring: >=65 APPLY, 45-64 REVIEW, <45 SKIP.
Hard constraints (auto-SKIP): NOT Zurich/Zug -> SKIP. NOT English -> SKIP. Pure SWE -> SKIP."""

def build_prompt(jobs):
    prompt = "Evaluate ALL jobs against this candidate profile:\n\n" + PROFILE + "\n\n=== JOBS ===\n\n"
    for i, job in enumerate(jobs, 1):
        title = job.get("titulo", job.get("title", "Unknown"))
        company = job.get("empresa", job.get("company", "Unknown"))
        location = job.get("localizacao", job.get("location", "Unknown"))
        desc = job.get("descricao", job.get("description", ""))[:150]
        url = job.get("url", "")
        prompt += f"\n--- JOB {i} ---\nTitle: {title}\nCompany: {company}\nLocation: {location}\nDescription: {desc}\nURL: {url}\n"
    prompt += "\n\nRespond with a JSON array of one evaluation object per job, in SAME order."
    return prompt

def evaluate_mini_batch(jobs):
    if not jobs:
        return []
    print(f"  Batch: {len(jobs)} jobs...", end=" ", flush=True)
    try:
        result = call_kimi_json(build_prompt(jobs), system=SYSTEM_PROMPT, max_tokens=3000)
        if isinstance(result, list) and len(result) == len(jobs):
            for i, ev in enumerate(result):
                ev.setdefault("empresa", jobs[i].get("empresa", jobs[i].get("company", "")))
                ev.setdefault("titulo", jobs[i].get("titulo", jobs[i].get("title", "")))
                ev.setdefault("url", jobs[i].get("url", ""))
                ev.setdefault("score", 50); ev.setdefault("decision", "REVIEW")
                ev.setdefault("technical_fit", ""); ev.setdefault("contextual_fit", "")
                ev.setdefault("salary_estimate", "Not disclosed"); ev.setdefault("culture_fit", "")
                ev.setdefault("concerns", []); ev.setdefault("materials_needed", ["cv"])
                ev.setdefault("portuguese_comment", "")
            print(f"OK (scores: {[e.get('score','?') for e in result]})")
            return result
    except Exception as e:
        print(f"ERRO: {str(e)[:80]}")
    return fallback_individual(jobs)

def fallback_individual(jobs):
    print("  -> API lenta. Atribuindo REVIEW padrao para", len(jobs), "jobs.")
    evaluations = []
    for job in jobs:
        evaluations.append({
            "empresa": job.get("empresa", job.get("company","")),
            "titulo": job.get("titulo", job.get("title", "Unknown")),
            "url": job.get("url",""),
            "score": 55, "decision": "REVIEW",
            "technical_fit": "Nao avaliado (API timeout)",
            "contextual_fit": "Nao avaliado (API timeout)",
            "salary_estimate": "Not disclosed", "culture_fit": "Nao avaliado",
            "concerns": ["API Kimi timeout — verificar manualmente"],
            "materials_needed": ["cv"],
            "portuguese_comment": "API lenta — verificar vaga manualmente no link"
        })
    return evaluations

def evaluate_single(job):
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:500]
    url = job.get("url", "")
    user_prompt = f"Evaluate this job:\nTitle: {title}\nCompany: {company}\nLocation: {location}\nDescription: {desc}\nURL: {url}\n"
    ev = call_kimi_json(user_prompt, system=SYSTEM_PROMPT, max_tokens=1500)
    ev.setdefault("empresa", company); ev.setdefault("titulo", title); ev.setdefault("url", url)
    ev.setdefault("score", 50); ev.setdefault("decision", "REVIEW")
    return ev

def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No jobs to evaluate."); return
    if not jobs:
        print("No jobs to evaluate."); return

    print(f"Loaded {len(jobs)} jobs. Mini-batches of 2...\n")
    BATCH_SIZE = 2
    evaluations = []
    total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
    for i in range(0, len(jobs), BATCH_SIZE):
        print(f"Batch {i//BATCH_SIZE + 1}/{total_batches}:")
        evaluations.extend(evaluate_mini_batch(jobs[i:i + BATCH_SIZE]))

    apply = [e for e in evaluations if e.get("score",0) >= 65]
    review = [e for e in evaluations if 45 <= e.get("score",0) < 65]
    skip = [e for e in evaluations if e.get("score",0) < 45]
    print(f"\n{'='*50}")
    print(f"COMPLETE: {len(evaluations)} jobs | APPLY: {len(apply)} | REVIEW: {len(review)} | SKIP: {len(skip)}")
    print(f"{'='*50}")

    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)
    print("Saved to digests/job_evaluations_latest.json")

if __name__ == "__main__":
    main()
