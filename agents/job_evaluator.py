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
from utils import THRESHOLD_APPLY, THRESHOLD_REVIEW, decision_from_score

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
                "Skills: SQL, Python, Power BI, GA4. Languages: PT, EN(C1), ES, DE(B1).")

    skills = p.get("skills", {})
    tech = skills.get("technical_default", [])
    certs = skills.get("certifications", [])
    exp = p.get("experience", [])
    exp_summary = "; ".join(f"{e.get('title', '')} @ {e.get('company', '').split('--')[0].strip()}" for e in exp[:3])
    edu = p.get("education", [])
    edu_summary = edu[0].get("degree", "") if edu else ""
    motivation = p.get("summary", "")
    projects = p.get("projects", [])
    project_summary = "; ".join(pr.get("title", "") for pr in projects[:2])

    return (
        f"Candidate: {p.get('role', 'Data/Business Analyst')}, Zurich Area CH "
        f"({p.get('permit', 'Permit B')}), notice {p.get('notice_period', '2 weeks')}. "
        f"Motivation (in his own words, weigh this for role-shape/excitement fit): {motivation} "
        f"Skills: {', '.join(tech)}. "
        f"Experience: {exp_summary}. "
        f"Projects: {project_summary}. "
        f"Education: {edu_summary}. "
        f"Certifications: {', '.join(certs)}. "
        f"Languages: {p.get('languages', 'PT native, EN C1, ES B2, DE B1')}."
    )


PROFILE = load_profile_summary()

SYSTEM_PROMPT = (
    'Evaluate job vs candidate. Return JSON: {"score":0-100,"technical_fit":"brief",'
    '"contextual_fit":"brief","salary_estimate":"range or Not disclosed","culture_fit":"brief",'
    '"concerns":["prefix hard eligibility blockers (unmet hard language requirement, '
    'wrong permit/location, etc.) with \'Blocker: \'; everything else (skill-depth notes, '
    'minor gaps, things merely worth knowing) stays unprefixed -- do not call a soft note '
    'a blocker just to sound thorough"],"decision":"APPLY|REVIEW|SKIP",'
    '"detected_company":"company name from the job text, or empty if not clearly stated",'
    '"detected_title":"job title from the job text, or empty if not clearly stated",'
    '"detected_location":"city/canton the role is based in, inferred from the job text '
    '(office address, \'based in\', regulatory/site mentions), or empty if not clearly stated"}. '
    f"Rules: >={THRESHOLD_APPLY} APPLY, {THRESHOLD_REVIEW}-{THRESHOLD_APPLY - 1} REVIEW, "
    f"<{THRESHOLD_REVIEW} SKIP. Auto-SKIP: not Zurich/Zug, not English, pure SWE. "
    "Also always auto-SKIP -- score below the SKIP threshold, no exception, regardless of "
    "how strong the rest of the match is -- when the role explicitly REQUIRES fluent/native "
    "German (or any language beyond English) for the candidate to do the job: his German is "
    "B1 (solid but not fluent), so a native/C1-fluent requirement is a hard eligibility "
    "blocker he cannot currently meet, not a 'domain gap' to wave off. This is deliberate: "
    "an otherwise-perfect job he is disqualified from is worse than useless to surface, it's "
    "noise. Distinguish that HARD requirement ('fluent German required', 'German native "
    "speaker', 'verhandlungssicheres Deutsch', 'C1/C2 German') from a SOFT one ('German is a "
    "plus', 'German helpful but not required', B1/B2 German acceptable, or the role states "
    "English as the working language) -- a soft or B1-level requirement is a minor signal "
    "like any other soft criterion and should NOT trigger this auto-SKIP. "
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
        "company": job.get("company", "Unknown"),
        "title": job.get("title", "Unknown"),
        "location": job.get("location", "Unknown"),
        "url": job.get("url", ""),
        "portal": job.get("portal", job.get("source", "adzuna")),
        # Persisted (truncated, same window the score itself was based on)
        # so doc_generator.py can write a CV/CL grounded in the actual
        # posting -- it used to only have title/company/location to work
        # with, since this was never saved, producing generic-sounding
        # materials regardless of how good the underlying description was.
        "description": job.get("description", "")[:1500],
    }


def evaluate_job(job):
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    location = job.get("location", "Unknown")
    desc = job.get("description", "")[:1500]
    url = job.get("url", "")

    prompt = f"Job: {title} at {company}\nLocation: {location}\nDesc: {desc}\nURL: {url}\nEvaluate."

    try:
        ev = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT, max_tokens=1000)

        score = ev.get("score", 50)
        # Decision is always derived from score, never trusted verbatim from
        # the model: the model's own "decision" field regularly drifts from
        # what its own score implies (e.g. score=68 with decision="REVIEW",
        # when 68 is below THRESHOLD_REVIEW=70) since it's freeform text, not
        # a constrained field. Thresholds are the single source of truth.
        decision = decision_from_score(score)
        model_decision = ev.get("decision")
        if model_decision and model_decision != decision:
            print(f"  Note: model said decision={model_decision} but score={score} "
                  f"maps to {decision}; using {decision}.")

        recommendation = decision
        key_match_points = []
        # Concerns always surface, regardless of tier -- they used to be
        # dropped for APPLY-tier jobs (score >= THRESHOLD_APPLY never copied
        # them from ev["concerns"]), which meant digest_generator.py (reads
        # only "red_flags") silently hid real caveats -- e.g. a hard German-
        # fluency requirement -- on exactly the highest-scoring jobs, where
        # they matter most.
        red_flags = ev.get("concerns", [] if score >= THRESHOLD_REVIEW else ["Score below threshold"])

        if score >= THRESHOLD_APPLY:
            key_match_points = [ev.get("technical_fit", ""), ev.get("contextual_fit", "")]
            key_match_points = [p for p in key_match_points if p]
        elif score >= THRESHOLD_REVIEW:
            key_match_points = [ev.get("technical_fit", "")]
            key_match_points = [p for p in key_match_points if p]

        # Backfill company/title/location from what the model detected in
        # the description when the caller didn't supply them: this is the
        # same reasoning the model already does for technical_fit/
        # contextual_fit (e.g. it correctly wrote "Zurich area (Wallisellen)"
        # in contextual_fit while the structured `location` field stayed
        # "Unknown" -- manually-added jobs in particular never had any
        # location-extraction logic at all).
        resolved_job = dict(job)
        for field, detected_key in (("company", "detected_company"), ("title", "detected_title"), ("location", "detected_location")):
            if resolved_job.get(field, "Unknown") in ("Unknown", "", None):
                detected = ev.get(detected_key)
                if detected and detected.strip() and detected.strip().lower() != "unknown":
                    resolved_job[field] = detected.strip()

        return {
            "score": score,
            "recommendation": recommendation,
            "key_match_points": key_match_points,
            "red_flags": red_flags,
            "job": _job_block(resolved_job),
            "technical_fit": ev.get("technical_fit", ""),
            "contextual_fit": ev.get("contextual_fit", ""),
            "salary_estimate": ev.get("salary_estimate", "Not disclosed"),
            "culture_fit": ev.get("culture_fit", ""),
            "concerns": ev.get("concerns", []),
            "decision": decision,
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
        title = job.get("title", "Unknown")[:50]
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
