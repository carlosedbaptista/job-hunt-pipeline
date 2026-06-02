"""
job_evaluator.py — 1 vaga por chamada, prompt pequeno, delay 5s
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json

PROFILE = "Candidate: Carlos Eduardo Baptista — Data/Business Analyst, Wallisellen CH (Permit B), 2 weeks notice. Skills: SQL, Python, Power BI, GA4. Languages: PT, EN(C1), ES, DE(A2)."

SYSTEM_PROMPT = """Evaluate job vs candidate. Return JSON: {"score":0-100,"technical_fit":"brief","contextual_fit":"brief","salary_estimate":"range or Not disclosed","culture_fit":"brief","concerns":[],"decision":"APPLY|REVIEW|SKIP","portuguese_comment":"PT brief"}. Rules: >=65 APPLY, 45-64 REVIEW, <45 SKIP. Auto-SKIP: not Zurich/Zug, not English, pure SWE."""

def evaluate_job(job):
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:100]
    url = job.get("url", "")
    prompt = f"Job: {title} at {company}\nLocation: {location}\nDesc: {desc}\nURL: {url}\nEvaluate."
    try:
        ev = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT, max_tokens=1000)
        ev.setdefault("empresa", company)
        ev.setdefault("titulo", title)
        ev.setdefault("url", url)
        ev.setdefault("score", 50)
        ev.setdefault("decision", "REVIEW")
        return ev
    except Exception as e:
        print(f"API timeout -> REVIEW padrao")
        return {"empresa": company, "titulo": title, "url": url, "score": 55, "decision": "REVIEW", "technical_fit": "Nao avaliado (timeout)", "contextual_fit": "Nao avaliado (timeout)", "salary_estimate": "Not disclosed", "culture_fit": "Nao avaliado", "concerns": ["API timeout"], "portuguese_comment": "Verificar manualmente no link", "materials_needed": ["cv"]}

def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No jobs to evaluate."); return
    if not jobs:
        print("No jobs to evaluate."); return

    print(f"Loaded {len(jobs)} jobs. 1 by 1 with 5s delay...\n")
    evaluations = []
    for i, job in enumerate(jobs, 1):
        title = job.get("titulo", job.get("title", "Unknown"))[:50]
        print(f"[{i}/{len(jobs)}] {title}...", end=" ", flush=True)
        ev = evaluate_job(job)
        evaluations.append(ev)
        print(f"score={ev.get('score','?')} ({ev.get('decision','?')})")
        if i < len(jobs):
            time.sleep(5)

    apply = [e for e in evaluations if e.get("score",0) >= 65]
    review = [e for e in evaluations if 45 <= e.get("score",0) < 65]
    skip = [e for e in evaluations if e.get("score",0) < 45]
    print(f"\n{'='*50}")
    print(f"DONE: {len(evaluations)} jobs | APPLY: {len(apply)} | REVIEW: {len(review)} | SKIP: {len(skip)}")
    print(f"{'='*50}")
    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
