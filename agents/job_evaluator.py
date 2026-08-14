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

def load_profile_summary() -> str:
    """Builds the candidate summary from config/candidate_profile.json,
    so the match criteria reflect the real CV (not a fixed summary)."""
    try:
        with open("config/candidate_profile.json", encoding="utf-8") as f:
            p = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Fallback: minimal summary without PII
        return ("Candidate: Data/Business Analyst, Zurich Area CH (Permit B), 2 weeks notice. "
                "Skills: SQL, Python, Power BI, GA4. Languages: PT, EN(C1), ES, DE(A2).")

    skills = p.get("skills", {})
    tech = skills.get("technical_default", [])
    certs = skills.get("certifications", [])
    exp = p.get("experience", [])
    exp_summary = "; ".join(f"{e.get('title', '')} @ {e.get('company', '').split('--')[0].strip()}" for e in exp[:3])
    edu = p.get("education", [])
    edu_summary = edu[0].get("degree", "") if edu else ""

    return (
        f"Candidate: {p.get('role', 'Data/Business Analyst')}, Zurich Area CH "
        f"({p.get('permit', 'Permit B')}), notice {p.get('notice_period', '2 weeks')}. "
        f"Skills: {', '.join(tech[:8])}. "
        f"Experience: {exp_summary}. "
        f"Education: {edu_summary}. "
        f"Certifications: {', '.join(certs)}. "
        f"Languages: PT native, EN C1, ES B2, DE A2."
    )


PROFILE = load_profile_summary()

SYSTEM_PROMPT = """Evaluate job vs candidate. Return JSON: {"score":0-100,"technical_fit":"brief","contextual_fit":"brief","salary_estimate":"range or Not disclosed","culture_fit":"brief","concerns":[],"decision":"APPLY|REVIEW|SKIP","portuguese_comment":"PT brief"}. Rules: >=75 APPLY, 45-74 REVIEW, <45 SKIP. Auto-SKIP: not Zurich/Zug, not English, pure SWE."""

ERROR_LOG = os.path.join("digests", "evaluation_errors.txt")  # .txt: *.log is in .gitignore and would not be committed


def log_error(msg):
    """Logs real API errors for diagnosis (committed by the workflow)."""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def evaluate_job(job):
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:1500]
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

        if score >= 75:
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
        err_msg = f"{type(e).__name__}: {e}"
        print(f"API ERROR -> default REVIEW | {err_msg[:200]}")
        log_error(f"{title} @ {company}: {err_msg}")
        return {
            "score": 55,
            "recommendation": "REVIEW",
            "key_match_points": [],
            "red_flags": [f"API error: {err_msg[:150]}"],
            "job": {
                "empresa": company,
                "titulo": title,
                "localizacao": location,
                "url": url,
                "portal": portal,
            },
            "technical_fit": "Not evaluated (API error)",
            "contextual_fit": "Not evaluated (API error)",
            "salary_estimate": "Not disclosed",
            "culture_fit": "Not evaluated",
            "concerns": [f"API error: {err_msg[:150]}"],
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

    apply = [e for e in evaluations if e.get("score", 0) >= 75]
    review = [e for e in evaluations if 45 <= e.get("score", 0) < 75]
    skip = [e for e in evaluations if e.get("score", 0) < 45]
    api_errors = [e for e in evaluations
                  if any("API error" in str(f) for f in e.get("red_flags", []))]
    print(f"\n{'='*50}")
    print(f"DONE: {len(evaluations)} jobs | APPLY: {len(apply)} | REVIEW: {len(review)} | SKIP: {len(skip)}")
    print(f"{'='*50}")
    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

    # Fail loud: if EVERY evaluation fell back to the default score, the LLM
    # provider is down/misconfigured -- a green "0 APPLY" run hides outages.
    if api_errors and len(api_errors) == len(evaluations):
        print(f"FATAL: all {len(api_errors)} evaluations failed (see digests/evaluation_errors.txt). "
              f"Check KIMI_API_KEY / KIMI_BASE_URL and account balance.")
        sys.exit(1)


if __name__ == "__main__":
    main()
