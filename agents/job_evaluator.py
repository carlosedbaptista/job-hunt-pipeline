"""
job_evaluator.py -- 1 job per API call, small prompt, 2s delay
Output structure compatible with digest_generator and email_notifier.

API failures produce decision "ERROR" with score None: they are excluded from
ranking/metrics downstream instead of polluting history with fake scores.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json
from utils import THRESHOLD_APPLY, THRESHOLD_REVIEW

# Cost guard: cap LLM calls per run (business rule: control daily spend).
MAX_EVALUATIONS_PER_RUN = int(os.environ.get("MAX_EVALUATIONS_PER_RUN", "30"))


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
        f"Skills: {', '.join(tech)}. "
        f"Experience: {exp_summary}. "
        f"Education: {edu_summary}. "
        f"Certifications: {', '.join(certs)}. "
        f"Languages: PT native, EN C1, ES B2, DE A2."
    )


PROFILE = load_profile_summary()

SYSTEM_PROMPT = (
    'Evaluate job vs candidate. Return JSON: {"score":0-100,"technical_fit":"brief",'
    '"contextual_fit":"brief","salary_estimate":"range or Not disclosed","culture_fit":"brief",'
    '"concerns":[],"decision":"APPLY|REVIEW|SKIP","portuguese_comment":"PT brief"}. '
    f"Rules: >={THRESHOLD_APPLY} APPLY, {THRESHOLD_REVIEW}-{THRESHOLD_APPLY - 1} REVIEW, "
    f"<{THRESHOLD_REVIEW} SKIP. Auto-SKIP: not Zurich/Zug, not English, pure SWE. "
    "Weighting: candidate is a deliberate career changer, open to unfamiliar business "
    "domains (finance, healthcare, retail, etc.) -- do NOT penalize lack of domain "
    "experience if the technical/functional role itself matches. Technical fit and "
    "logistics (location, permit, availability) should drive the score; culture_fit and "
    "domain unfamiliarity are minor, non-decisive signals and should rarely by "
    "themselves keep a technically strong match out of APPLY. "
    "Perspective: score as the candidate would score it for himself -- how excited he'd "
    "be, how much he'd grow -- not as an HR recruiter filtering out risk. "
    "Calibration example (candidate-rated 100/APPLY): 'AI Platform Engineer Intern' at a "
    "small regulated investment firm, no finance background required of him and some "
    "tools in the stack (Microsoft no-code) he'd never used. Rated 100 because: hands-on "
    "ownership from day one ('junior builder, not support hand'), greenfield AI/"
    "automation building on a real platform, direct work with LLMs and agentic "
    "workflows in production. Role SHAPE -- ownership, building vs. maintaining, "
    "hands-on AI/automation work -- matters more than a perfect skills or domain "
    "checklist match. Weigh it accordingly."
)

ERROR_LOG = os.path.join("digests", "evaluation_errors.txt")  # .txt: *.log is in .gitignore and would not be committed
HISTORY_DIR = os.path.join("data", "history")


def log_error(msg):
    """Logs real API errors for diagnosis (committed by the workflow)."""
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def _job_block(job):
    return {
        "empresa": job.get("empresa", job.get("company", "Unknown")),
        "titulo": job.get("titulo", job.get("title", "Unknown")),
        "localizacao": job.get("localizacao", job.get("location", "Unknown")),
        "url": job.get("url", ""),
        "portal": job.get("portal", job.get("source", "adzuna")),
    }


def evaluate_job(job):
    title = job.get("titulo", job.get("title", "Unknown"))
    company = job.get("empresa", job.get("company", "Unknown"))
    location = job.get("localizacao", job.get("location", "Unknown"))
    desc = job.get("descricao", job.get("description", ""))[:1500]
    url = job.get("url", "")

    prompt = f"Job: {title} at {company}\nLocation: {location}\nDesc: {desc}\nURL: {url}\nEvaluate."

    try:
        ev = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT, max_tokens=1000)

        score = ev.get("score", 50)
        decision = ev.get("decision", "REVIEW")

        recommendation = decision
        key_match_points = []
        red_flags = []

        if score >= THRESHOLD_APPLY:
            key_match_points = [ev.get("technical_fit", ""), ev.get("contextual_fit", "")]
            key_match_points = [p for p in key_match_points if p]
        elif score >= THRESHOLD_REVIEW:
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
            "job": _job_block(job),
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
        print(f"API ERROR -> decision ERROR (no fake score) | {err_msg[:200]}")
        log_error(f"{title} @ {company}: {err_msg}")
        # No invented score: ERROR entries are excluded from ranking and
        # metrics downstream. A fake 55/REVIEW once polluted 8 weeks of data.
        return {
            "score": None,
            "recommendation": "ERROR",
            "key_match_points": [],
            "red_flags": [f"API error: {err_msg[:150]}"],
            "job": _job_block(job),
            "technical_fit": "Not evaluated (API error)",
            "contextual_fit": "Not evaluated (API error)",
            "salary_estimate": "Not disclosed",
            "culture_fit": "Not evaluated",
            "concerns": [f"API error: {err_msg[:150]}"],
            "decision": "ERROR",
            "portuguese_comment": "Nao avaliada: erro de API. Verifique creditos/chave.",
            "materials_needed": [],
        }


def append_history(evaluations):
    """Appends this run's evaluations to data/history/evaluations_YYYYMMDD.json
    so the full evaluation history survives (job_evaluations_latest.json is
    overwritten every run and digests only keep the top 5)."""
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        path = os.path.join(HISTORY_DIR, f"evaluations_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json")
        existing = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []
        run_ts = datetime.now(timezone.utc).isoformat()
        for ev in evaluations:
            entry = dict(ev)
            entry["evaluated_at"] = run_ts
            existing.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"History: {len(evaluations)} evaluations appended to {path}")
    except OSError as e:
        print(f"WARNING: could not write history: {e}")


def main():
    os.makedirs("digests", exist_ok=True)
    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print("No jobs to evaluate."); return
    if not jobs:
        print("No jobs to evaluate."); return

    if len(jobs) > MAX_EVALUATIONS_PER_RUN:
        print(f"Cost guard: {len(jobs)} jobs found, capping at {MAX_EVALUATIONS_PER_RUN} "
              f"(set MAX_EVALUATIONS_PER_RUN to change).")
        jobs = jobs[:MAX_EVALUATIONS_PER_RUN]

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

    scored = [e for e in evaluations if e.get("score") is not None]
    errors = [e for e in evaluations if e.get("decision") == "ERROR"]
    apply_ = [e for e in scored if e["score"] >= THRESHOLD_APPLY]
    review = [e for e in scored if THRESHOLD_REVIEW <= e["score"] < THRESHOLD_APPLY]
    skip = [e for e in scored if e["score"] < THRESHOLD_REVIEW]

    print(f"\n{'='*50}")
    print(f"DONE: {len(evaluations)} jobs | APPLY: {len(apply_)} | REVIEW: {len(review)} | "
          f"SKIP: {len(skip)} | ERROR: {len(errors)}")
    print(f"{'='*50}")
    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

    append_history(evaluations)

    if errors:
        print(f"WARNING: {len(errors)}/{len(evaluations)} evaluations failed "
              f"(see digests/evaluation_errors.txt). These jobs were NOT scored.")

    # Fail loud: if EVERY evaluation failed, the LLM provider is down or the
    # account has no credits -- a green "0 APPLY" run hides outages.
    if errors and len(errors) == len(evaluations):
        print(f"FATAL: all {len(errors)} evaluations failed. "
              f"Check KIMI_API_KEY / KIMI_BASE_URL and account balance.")
        sys.exit(1)


if __name__ == "__main__":
    main()
