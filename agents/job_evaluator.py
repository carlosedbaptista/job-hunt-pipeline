"""
job_evaluator.py -- 1 job per API call, small prompt, 2s delay
Output structure compatible with digest_generator and email_notifier.

API failures produce decision "ERROR" with score None: they are excluded from
ranking/metrics downstream instead of polluting history with fake scores.
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi_json
from utils import (THRESHOLD_APPLY, THRESHOLD_REVIEW,
                   effective_decision, is_spurious_blocker, max_evaluations_per_run)

# Cost guard: cap LLM calls per run (business rule: control daily spend).
MAX_EVALUATIONS_PER_RUN = max_evaluations_per_run()

# The model only sees description[:DESCRIPTION_WINDOW]. Matches the window
# Adzuna keeps (4000); the old 1500-char window cut off exactly the final
# "Requirements/Anforderungen" block where Swiss postings put their hard
# language requirements -- a C1-German clause past char 1500 invisibly
# flipped an auto-SKIP job to a 96/APPLY (2026-08-17 audit, scenario 4).
DESCRIPTION_WINDOW = 4000

# Below this much real posting text there is not enough signal for a
# confident evaluation -- evaluate_job caps such jobs at REVIEW so a bare
# title never earns automatic APPLY / CV-CL generation (the model otherwise
# fabricates confidence: a title-only "AI Engineer" posting scored 78 with
# "Technical fit: Strong" in the 2026-08-17 audit).
MIN_DESCRIPTION_CHARS = 200

PROFILE_IS_FALLBACK = False


def load_profile_summary() -> str:
    """Builds the candidate summary from config/candidate_profile.json,
    so the match criteria reflect the real CV (not a fixed summary)."""
    global PROFILE_IS_FALLBACK
    try:
        with open("config/candidate_profile.json", encoding="utf-8") as f:
            p = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # Fallback: minimal summary without PII. Loud, because scoring the
        # whole run against a generic profile silently distorts every score
        # (main() refuses to run in this state; single-job callers like
        # add_job.py only get this warning).
        PROFILE_IS_FALLBACK = True
        print(f"WARNING: config/candidate_profile.json unavailable ({type(e).__name__}) -- "
              "using the generic fallback profile; scores will NOT reflect the real candidate.",
              file=sys.stderr)
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
    '"hard_blockers":["ONLY true hard eligibility blockers: an unmet HARD language requirement, '
    'wrong permit/location. EMPTY LIST when none -- never write None/no-blocker text here"],'
    '"concerns":["soft signals only: skill-depth notes, minor gaps, things merely worth '
    'knowing -- hard blockers belong in hard_blockers, not here"],'
    '"decision":"APPLY|REVIEW|SKIP",'
    '"detected_company":"company name from the job text, or empty if not clearly stated",'
    '"detected_title":"job title from the job text, or empty if not clearly stated",'
    '"detected_location":"city/canton the role is based in, inferred from the job text '
    '(office address, \'based in\', regulatory/site mentions), or empty if not clearly stated"}. '
    f"Rules: >={THRESHOLD_APPLY} APPLY, {THRESHOLD_REVIEW}-{THRESHOLD_APPLY - 1} REVIEW, "
    f"<{THRESHOLD_REVIEW} SKIP. Auto-SKIP: not Zurich/Zug (a fully-remote role based in "
    "Switzerland counts as Zurich-area -- do NOT skip it for location), not English, pure SWE. "
    "Also always auto-SKIP -- score below the SKIP threshold AND an entry in hard_blockers, "
    "no exception, regardless of how strong the rest of the match is -- when the role "
    "explicitly REQUIRES fluent/native German (or any language beyond English) for the "
    "candidate to do the job: his German is B1 (solid but not fluent), so a native/C1-fluent "
    "requirement is a hard eligibility blocker he cannot currently meet, not a 'domain gap' "
    "to wave off. This is deliberate: an otherwise-perfect job he is disqualified from is "
    "worse than useless to surface, it's noise. Distinguish that HARD requirement ('fluent "
    "German required', 'German native speaker', 'verhandlungssicheres Deutsch', 'C1/C2 "
    "German') from a SOFT one ('German is a plus', 'German helpful but not required', B1/B2 "
    "German acceptable, or the role states English as the working language) -- a soft or "
    "B1-level requirement is a minor signal like any other soft criterion, stays out of "
    "hard_blockers, and should NOT trigger this auto-SKIP. "
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


# Hard language requirements in Swiss postings live in the final
# 'Requirements/Anforderungen' block -- past the excerpt window on long
# descriptions. This deterministic pre-check scans the FULL text so such a
# clause is never invisible to the scorer. English is deliberately absent
# (the candidate is C1); German/French/Italian are the local risks.
_HARD_LANGUAGE_RE = re.compile(
    r"(?:fluent|native|mother[\s-]?tongue|verhandlungssicher\w*|\bc1\b|\bc2\b)"
    r"[^.\n]{0,80}(?:german|deutsch|french|fran[cç]ais|franz[oö]sisch|italian\w*|italienisch)"
    r"|(?:german|deutsch|french|fran[cç]ais|franz[oö]sisch|italian\w*|italienisch)"
    r"[^.\n]{0,80}(?:fluent|native|mother[\s-]?tongue|verhandlungssicher\w*|\bc1\b|\bc2\b)",
    re.IGNORECASE,
)


def detect_hard_language_requirement(full_description: str):
    """Scans the FULL description for what looks like a hard language
    requirement beyond English/B1-German, returning a short evidence
    snippet (or None). Soft mentions ('German is a plus', B1/B2 acceptable)
    deliberately do not match. The snippet is injected into the prompt as
    pipeline evidence -- the model still judges, but can no longer be blind
    to a requirement past the truncation window."""
    m = _HARD_LANGUAGE_RE.search(full_description or "")
    if not m:
        return None
    start = max(0, m.start() - 80)
    end = min(len(full_description), m.end() + 80)
    return re.sub(r"\s+", " ", full_description[start:end]).strip()


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
        "description": (job.get("description") or "")[:DESCRIPTION_WINDOW],
    }


def _sanitize_score(raw):
    """Coerces the model's score to an int in [0, 100]; None when absent or
    unparseable. The model sometimes returns "85" (a string -- used to crash
    the threshold comparison and turn a good evaluation into ERROR) or 120
    (passed straight through as APPLY)."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = raw
    elif isinstance(raw, str):
        try:
            value = float(raw.strip())
        except ValueError:
            return None
    else:
        return None
    return max(0, min(100, int(round(value))))


def _error_record(job, err_msg):
    """No invented score: ERROR entries are excluded from ranking and
    metrics downstream. A fake 55/REVIEW once polluted 8 weeks of data."""
    return {
        "score": None,
        "recommendation": "ERROR",
        "hard_blockers": [],
        "insufficient_info": False,
        "key_match_points": [],
        "red_flags": [err_msg[:150]],
        "job": _job_block(job),
        "technical_fit": "Not evaluated",
        "contextual_fit": "Not evaluated",
        "salary_estimate": "Not disclosed",
        "culture_fit": "Not evaluated",
        "concerns": [err_msg[:150]],
        "decision": "ERROR",
        "materials_needed": [],
    }


def evaluate_job(job):
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    location = job.get("location", "Unknown")
    desc_full = job.get("description", "") or ""
    desc = desc_full[:DESCRIPTION_WINDOW]
    insufficient_info = len(desc_full.strip()) < MIN_DESCRIPTION_CHARS
    url = job.get("url", "")

    # Today's date grounds any timeline reasoning (notice period vs start
    # date, posting age) -- without it the model works off its training
    # cutoff and once invented a "start date 16+ months away" blocker for a
    # start 2 months out.
    prompt = (f"Today's date: {date.today().isoformat()}\n"
              f"Job: {title} at {company}\nLocation: {location}\nDesc: {desc}\nURL: {url}")
    lang_evidence = detect_hard_language_requirement(desc_full)
    if lang_evidence:
        prompt += (f"\n[Pipeline note: the full posting contains this text, possibly beyond "
                   f"the excerpt above: \"{lang_evidence}\" -- if it is a HARD language "
                   f"requirement beyond English (or beyond B1-level German), the auto-SKIP "
                   f"rule applies and it belongs in hard_blockers.]")
    prompt += "\nEvaluate."

    try:
        ev = call_kimi_json(prompt, system=PROFILE + "\n" + SYSTEM_PROMPT, max_tokens=1000)

        score = _sanitize_score(ev.get("score"))
        if score is None:
            # A missing/invalid score is an evaluation failure, NOT a silent
            # 50/SKIP -- the old default fabricated exactly the kind of score
            # the no-fake-scores rule exists to prevent.
            msg = f"Model returned no usable score: {ev.get('score')!r}"
            print(f"EVALUATION ERROR -> {msg}")
            log_error(f"{title} @ {company}: {msg}")
            return _error_record(job, f"Evaluation error: {msg}")

        raw_concerns = ev.get("concerns") or []  # 'concerns': null must not propagate None
        if not isinstance(raw_concerns, list):
            raw_concerns = [raw_concerns]
        concerns = [str(c) for c in raw_concerns]
        soft_concerns = [c for c in concerns if not c.startswith("Blocker:")]

        model_blockers = ev.get("hard_blockers")
        if model_blockers is None:
            # Backward compat: a model still on the old contract reports
            # blockers as 'Blocker: '-prefixed concerns.
            model_blockers = [c[len("Blocker:"):].strip() for c in concerns
                              if c.startswith("Blocker:")]
        if not isinstance(model_blockers, list):
            model_blockers = [model_blockers]
        # Spurious 'Blocker: None -- ...' entries are filtered: the model
        # uses the prefix to say there is NO blocker, and taking the prefix
        # literally would SKIP the best jobs (2026-08-17 smoke, scenario 1).
        real_blockers = [b for b in (str(x).strip() for x in model_blockers)
                         if b and not is_spurious_blocker(b)]

        # Concerns always surface, regardless of tier (a real bug used to
        # drop them for APPLY-tier jobs -- exactly where they matter most).
        red_flags = [f"Blocker: {b}" for b in real_blockers] + soft_concerns
        if insufficient_info:
            red_flags.append("Low confidence: posting text under "
                             f"{MIN_DESCRIPTION_CHARS} chars -- score is title-based")
        if not red_flags and score < THRESHOLD_REVIEW:
            red_flags = ["Score below threshold"]

        key_match_points = []
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

        record = {
            "score": score,
            "hard_blockers": real_blockers,
            "insufficient_info": insufficient_info,
            "key_match_points": key_match_points,
            "red_flags": red_flags,
            "job": _job_block(resolved_job),
            "technical_fit": ev.get("technical_fit", ""),
            "contextual_fit": ev.get("contextual_fit", ""),
            "salary_estimate": ev.get("salary_estimate", "Not disclosed"),
            "culture_fit": ev.get("culture_fit", ""),
            "concerns": concerns,
        }

        # Decision is ALWAYS derived locally, never trusted verbatim from the
        # model: thresholds on the score + the hard-blocker lock (business
        # rule, no exception) + the low-confidence cap. See utils.py.
        decision = effective_decision(record)
        model_decision = ev.get("decision")
        if model_decision and model_decision != decision:
            print(f"  Note: model said decision={model_decision} but local rules map to "
                  f"{decision} (score={score}, blockers={len(real_blockers)}, "
                  f"insufficient={insufficient_info}); using {decision}.")

        record["recommendation"] = decision
        record["decision"] = decision
        record["materials_needed"] = ["cv"] if decision == "APPLY" else []
        return record
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        print(f"API ERROR -> decision ERROR (no fake score) | {err_msg[:200]}")
        log_error(f"{title} @ {company}: {err_msg}")
        return _error_record(job, f"API error: {err_msg}")


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
    if PROFILE_IS_FALLBACK:
        # Scoring the whole run against a generic profile would silently
        # distort every score -- fail loud instead (usually means the
        # CANDIDATE_PROFILE_B64 secret was not restored in CI).
        print("FATAL: config/candidate_profile.json missing/invalid. "
              "Refusing to evaluate with the generic fallback profile.")
        sys.exit(1)

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
