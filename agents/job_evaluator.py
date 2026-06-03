"""
job_evaluator.py -- 1 job per API call, small prompt, 2s delay
Output structure compatible with digest_generator and email_notifier.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json

PROFILE = "Candidate: Carlos Eduardo Baptista -- Data/Business Analyst, Wallisellen CH (Permit B), 2 weeks notice. Skills: SQL, Python, Power BI, GA4. Languages: PT, EN(C1), ES, DE(A2)."

SYSTEM_PROMPT = """Evaluate job vs candidate. Return JSON: {"score":0-100,"technical_fit":"brief","contextual_fit":"brief","salary_estimate":"range or Not disclosed","culture_fit":"brief","concerns":[],"decision":"APPLY|REVIEW|SKIP","portuguese_comment":"PT brief"}. Rules: >=65 APPLY, 45-64 REVIEW, <45 SKIP. Auto-SKIP: not Zurich/Zug, not English, pure SWE."""


def evaluate_job(job):
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:200]
    url = job.get("url", "")
    portal = job.get("portal", job.get("source", "adzuna"))

    prompt = f"Job: {title} at {company}\nLocation: {location}\nDesc: {desc}\nURL: {url}\nEvaluate."

    try:
        ev = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT, max_tokens=1000)

        score = ev.get("score", 50)
        decision = ev.get("decision", "REVIEW")

        recommendation = decision
        key_match_points = []
        red_flags = []

        if score >= 65:
            key_match_points = [ev.get("technical_fit", ""), ev.get("contextual_fit", "")]
            key_match_points = [p for p in key_match_points if p]
        elif score >= 45:
            key_match_points = [ev.get("technical_fit", "")]
            key_match_points = [p for p in key_match_points if p]
            red_flags = ev.get("concerns", [])
        else:
            red_flags = ev.get("concerns", ["Score below threshold"])

        return {
            "score": score,
            "recommendation": recommendation,
            "key_match_points": key_match_points,
            "red_flags": red_flags,
            "job": {
                "empresa": company,
                "titulo": title,
                "localizacao": location,
                "url": url,
                "portal": portal,
            },
            "technical_fit": ev.get("technical_fit", ""),
            "contextual_fit": ev.get("contextual_fit", ""),
            "salary_estimate": ev.get("salary_estimate", "Not disclosed"),
            "culture_fit": ev.get("culture_fit", ""),
            "concerns": ev.get("concerns", []),
            "decision": decision,
            "portuguese_comment": ev.get("portuguese_comment", ""),
            "materials_needed": ["cv"] if decision == "APPLY" else [],
        }
    except Exception as e:
        print(f"API timeout -> default REVIEW")
        return {
            "score": 55,
            "recommendation": "REVIEW",
            "key_match_points": [],
            "red_flags": ["API timeout"],
            "job": {
                "empresa": company,
                "titulo": title,
                "localizacao": location,
                "url": url,
                "portal": portal,
            },
            "technical_fit": "Not evaluated (timeout)",
            "contextual_fit": "Not evaluated (timeout)",
            "salary_estimate": "Not disclosed",
            "culture_fit": "Nao avaliado",
            "concerns": ["API timeout"],
            "decision": "REVIEW",
            "portuguese_comment": "Check manually via link",
            "materials_needed": ["cv"],
        }


def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No jobs to evaluate."); return
    if not jobs:
        print("No jobs to evaluate."); return

    print(f"Loaded {len(jobs)} jobs. 1 by 1 with 2s delay...\n")
    evaluations = []
    for i, job in enumerate(jobs, 1):
        title = job.get("titulo", job.get("title", "Unknown"))[:50]
        print(f"[{i}/{len(jobs)}] {title}...", end=" ", flush=True)
        ev = evaluate_job(job)
        evaluations.append(ev)
        print(f"score={ev.get('score','?')} ({ev.get('decision','?')})")
        if i < len(jobs):
            time.sleep(2)

    apply = [e for e in evaluations if e.get("score", 0) >= 65]
    review = [e for e in evaluations if 45 <= e.get("score", 0) < 65]
    skip = [e for e in evaluations if e.get("score", 0) < 45]
    print(f"\n{'='*50}")
    print(f"DONE: {len(evaluations)} jobs | APPLY: {len(apply)} | REVIEW: {len(review)} | SKIP: {len(skip)}")
    print(f"{'='*50}")
    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
