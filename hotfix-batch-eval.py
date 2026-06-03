#!/usr/bin/env python3
"""
hotfix-batch-eval.py  -  Corrige job_evaluator para avaliar TODAS vagas em 1 chamada Kimi
"""

import os
import subprocess

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.returncode == 0, r.stdout, r.stderr

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

REPO = os.getcwd()
if not os.path.exists(f"{REPO}/.git"):
    print("ERRO: Rode dentro da pasta do repo")
    exit(1)

print("HOTFIX - Batch Evaluation (1 chamada para todas vagas)")

write_file(f"{REPO}/agents/job_evaluator.py", r'''
"""
job_evaluator.py  -  Avalia fit de cada vaga usando Kimi K2-6
                     AGORA: Todas as vagas em 1 chamada (batch)
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kimi_client import call_kimi_json


PROFILE = """
Candidate Profile:
- Name: Carlos Eduardo Duarte Baptista
- Role: Data and Business Analysis Professional
- Location: Wallisellen, Switzerland (Permit B)
- Notice period: 2 weeks
- Languages: Portuguese (native), English (C1), Spanish (B2), German (A2)
- Skills: SQL, Python, Power BI, GA4, automation with AI
- Experience: QUOD (40% manual reduction), netzdenker.com (Analytics)
- Education: Postgraduate Data Science (Oct 2026), Bachelor Systems
- Certifications: Google AI Essentials, Anthropic Claude, GA4
"""

SYSTEM_PROMPT = """You are a job fit evaluator. Evaluate each job against the candidate profile.
Respond ONLY with a valid JSON array. Each element must be an object with:
{
  "empresa": "same as input",
  "titulo": "same as input",
  "url": "same as input",
  "score": 0-100,
  "technical_fit": "brief justification",
  "contextual_fit": "brief justification",
  "salary_estimate": "salary range if mentioned, else 'Not disclosed'",
  "culture_fit": "brief note on company culture alignment",
  "concerns": ["list of concerns or empty list"],
  "decision": "APPLY" or "REVIEW" or "SKIP",
  "materials_needed": ["cv", "cover_letter", "recommendation"],
  "portuguese_comment": "brief comment in Portuguese for the candidate"
}

Scoring rules:
- >= 65: APPLY
- 45-64: REVIEW
- < 45: SKIP

Hard constraints (auto-SKIP if violated):
- NOT Zurich or Zug -> SKIP
- NOT English-speaking -> SKIP
- Pure software engineer / developer roles -> SKIP
"""


def build_batch_prompt(jobs: list) -> str:
    prompt = "Evaluate ALL the following jobs against this candidate profile:\n\n"
    prompt += PROFILE
    prompt += "\n\n=== JOBS TO EVALUATE ===\n\n"

    for i, job in enumerate(jobs, 1):
        title = job.get("titulo", job.get("title", "Unknown"))
        company = job.get("empresa", job.get("company", "Unknown"))
        location = job.get("localizacao", job.get("location", "Unknown"))
        desc = job.get("descricao", job.get("description", ""))[:500]
        url = job.get("url", "")

        prompt += f"\n--- JOB {i} ---\n"
        prompt += f"Title: {title}\n"
        prompt += f"Company: {company}\n"
        prompt += f"Location: {location}\n"
        prompt += f"Description: {desc}\n"
        prompt += f"URL: {url}\n"

    prompt += "\n\nRespond with a JSON array containing one evaluation object per job, in the SAME order."
    return prompt


def evaluate_all_jobs(jobs: list) -> list:
    if not jobs:
        return []

    print(f"Evaluating {len(jobs)} jobs in a SINGLE batch call to Kimi K2-6...")

    prompt = build_batch_prompt(jobs)

    try:
        result = call_kimi_json(prompt, system=SYSTEM_PROMPT, max_tokens=8000)

        if isinstance(result, list) and len(result) == len(jobs):
            for i, ev in enumerate(result):
                ev.setdefault("empresa", jobs[i].get("empresa", jobs[i].get("company", "")))
                ev.setdefault("titulo", jobs[i].get("titulo", jobs[i].get("title", "")))
                ev.setdefault("url", jobs[i].get("url", ""))
                ev.setdefault("score", 50)
                ev.setdefault("technical_fit", "Not evaluated")
                ev.setdefault("contextual_fit", "Not evaluated")
                ev.setdefault("salary_estimate", "Not disclosed")
                ev.setdefault("culture_fit", "Not evaluated")
                ev.setdefault("concerns", [])
                ev.setdefault("decision", "REVIEW")
                ev.setdefault("materials_needed", ["cv"])
                ev.setdefault("portuguese_comment", "Sem comentario")
            return result
        else:
            print(f"  Unexpected response. Got {type(result).__name__}, expected list of {len(jobs)}.")
            return fallback_evaluate(jobs)

    except Exception as e:
        print(f"  Batch evaluation failed: {e}")
        return fallback_evaluate(jobs)


def fallback_evaluate(jobs: list) -> list:
    """Fallback: evaluates 1 by 1 if batch fails."""
    print("  Falling back to individual evaluation...")
    evaluations = []
    for i, job in enumerate(jobs):
        title = job.get("titulo", job.get("title", "Unknown"))
        print(f"  [{i+1}/{len(jobs)}] {title[:50]}...", end=" ")
        try:
            ev = evaluate_single_job(job)
            evaluations.append(ev)
            print(f"score={ev.get('score', '?')}")
        except Exception as e:
            print(f"ERROR: {e}")
            evaluations.append({
                "empresa": job.get("empresa", job.get("company", "")),
                "titulo": title,
                "url": job.get("url", ""),
                "score": 50,
                "decision": "REVIEW",
                "technical_fit": "Evaluation error",
                "contextual_fit": "Evaluation error",
                "salary_estimate": "Not disclosed",
                "culture_fit": "Unknown",
                "concerns": [f"Evaluation error: {str(e)[:100]}"],
                "materials_needed": ["cv"],
                "portuguese_comment": "Erro na avaliacao",
            })
    return evaluations


def evaluate_single_job(job: dict) -> dict:
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:800]
    url = job.get("url", "")

    user_prompt = f"""Evaluate this job:
Title: {title}
Company: {company}
Location: {location}
Description: {desc}
URL: {url}
"""

    evaluation = call_kimi_json(
        user_prompt,
        system=SYSTEM_PROMPT,
        max_tokens=1500,
    )

    evaluation.setdefault("empresa", company)
    evaluation.setdefault("titulo", title)
    evaluation.setdefault("url", url)
    evaluation.setdefault("score", 50)
    evaluation.setdefault("decision", "REVIEW")
    return evaluation


def main():
    os.makedirs("digests", exist_ok=True)

    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No jobs to evaluate.")
        return

    if not jobs:
        print("No jobs to evaluate.")
        return

    print(f"Loaded {len(jobs)} jobs.\n")

    evaluations = evaluate_all_jobs(jobs)

    apply = [e for e in evaluations if e.get("score", 0) >= 65]
    review = [e for e in evaluations if 45 <= e.get("score", 0) < 65]
    skip = [e for e in evaluations if e.get("score", 0) < 45]

    print(f"\nEVALUATION COMPLETE: {len(evaluations)} jobs")
    print(f"  APPLY  (>=65): {len(apply)}")
    print(f"  REVIEW (45-64): {len(review)}")
    print(f"  SKIP   (<45): {len(skip)}")

    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

    print("Saved to digests/job_evaluations_latest.json")


if __name__ == "__main__":
    main()
''')

print("  job_evaluator.py reescrito com batch evaluation")

ok, out, err = run(f'cd {REPO} && git add agents/job_evaluator.py')
ok, out, err = run(f'cd {REPO} && git commit -m "perf: batch evaluation - todas vagas em 1 chamada Kimi"')
if ok:
    print("  Commit feito")
    run(f'cd {REPO} && git push origin main')
    print("  Push feito!")
else:
    print(f"  Erro: {err[:200]}")

print("\nPronto! Rode o workflow no GitHub Actions para testar.")
print("Esperado: Evaluator completa em ~30s em vez de 10-50min")
