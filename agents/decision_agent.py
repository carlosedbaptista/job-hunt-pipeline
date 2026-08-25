"""
decision_agent.py -- the evaluation stage as a tool-using agent.

Drop-in replacement for job_evaluator.py with the SAME I/O contract: reads
digests/new_jobs_latest.json, writes digests/job_evaluations_latest.json,
appends data/history/, records APPLY-tier jobs in the tracker, exits 1 when
every evaluation failed or the profile is the generic fallback.

Mode is chosen at run time (EVALUATION_MODE, read dynamically like
utils.max_evaluations_per_run):

  rules (default) -> delegates to job_evaluator.main(), completely unchanged;
  agent           -> each job is decided by an LLM agent that INVESTIGATES
                     through tools wrapping the existing deterministic code
                     (posting text, language check, profile, outcome
                     calibration, past evaluations) and must finalize by
                     calling record_decision. The evaluation record is then
                     built in CODE from the tool payload, behind the same
                     rails the deterministic evaluator applies: score
                     sanitizing, spurious-blocker filtering, the hard-
                     language defence in depth, and effective_decision()
                     (blocker SKIP lock, low-confidence APPLY->REVIEW cap).
                     The model proposes; the code disposes.
"""
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from agent_runtime import Tool, run_agent
from kimi_client import KimiClient
from utils import (MIN_DESCRIPTION_CHARS, THRESHOLD_APPLY, THRESHOLD_REVIEW,
                   effective_decision, is_spurious_blocker,
                   is_truncated_description, max_evaluations_per_run)

import job_evaluator as je

# Measured 2026-08-25 on the first agent-mode run: a thorough investigation
# calls all five informational tools in a row, so a cap of 5 starves the
# mandatory record_decision (three capped evaluations, identical traces).
# 8 = full investigation + terminal call + one retry, still bounded.
DEFAULT_AGENT_MAX_ITERATIONS = 8


def evaluation_mode():
    """'rules' (default) or 'agent'. Read dynamically -- never a module-level
    constant -- so tests and CI can switch via env without re-importing. An
    invalid or blank value warns and falls back to 'rules': a typo in a
    workflow input must never silently change how jobs are scored."""
    raw = os.environ.get("EVALUATION_MODE")
    if raw is None:
        return "rules"
    value = raw.strip().lower()
    if value in ("rules", "agent"):
        return value
    print(f"WARNING: EVALUATION_MODE={raw!r} is not 'rules' or 'agent' -- "
          "falling back to 'rules'.")
    return "rules"


def agent_max_iterations():
    """Tool-loop budget per job. Same dynamic pattern (and failure
    philosophy) as max_evaluations_per_run: blank or invalid falls back to
    the default instead of aborting the run."""
    raw = (os.environ.get("AGENT_MAX_ITERATIONS") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        if raw:
            print(f"  AGENT_MAX_ITERATIONS={raw!r} is not a number -- "
                  f"using {DEFAULT_AGENT_MAX_ITERATIONS}.")
        return DEFAULT_AGENT_MAX_ITERATIONS
    return value if value > 0 else DEFAULT_AGENT_MAX_ITERATIONS


# Same scoring philosophy as job_evaluator.SYSTEM_PROMPT -- same thresholds,
# same language tiers derived from the candidate's own level, same auto-SKIP
# rules, same role-shape calibration anchor -- so agent scores stay
# calibrated with the committed history the outcome-calibration loop refers
# to. What changes is the contract: not one JSON answer, but an
# investigation that MUST end in a record_decision tool call.
AGENT_SYSTEM_PROMPT = (
    "You are the decision-maker of this job-hunt pipeline: for each posting you "
    "make the APPLY / REVIEW / SKIP call -- the call the candidate would make "
    "for himself. You do not judge from the title: you INVESTIGATE with the "
    "tools. Call get_posting_text to read the posting (it also reports the true "
    "length and whether the text is a cut-off teaser), check_language_requirement "
    "for the deterministic language verdict over the FULL text, "
    "get_candidate_profile for who the candidate is, get_outcome_calibration "
    "for what happened to past recommendations, and search_past_evaluations "
    "for how similar jobs scored before. Use ONLY facts the tools return -- "
    "never invent posting content, requirements, or outcome history. "
    "You MUST finalize by calling record_decision with your score (0-100), "
    "decision, rationale, concerns, hard_blockers and language_requirement. "
    "Ending the conversation without record_decision is a failed evaluation: "
    "the pipeline records an ERROR, never a guess.\n"
    f"Scoring rules: >={THRESHOLD_APPLY} APPLY, {THRESHOLD_REVIEW}-{THRESHOLD_APPLY - 1} "
    f"REVIEW, <{THRESHOLD_REVIEW} SKIP. Auto-SKIP: not Zurich/Zug (a fully-remote "
    "role based in Switzerland counts as Zurich-area -- do NOT skip it for "
    "location), not English, pure SWE. Also always auto-SKIP -- score below the "
    "SKIP threshold AND an entry in hard_blockers, no exception, regardless of "
    "how strong the rest of the match is -- when the role explicitly REQUIRES "
    "fluent/native German (or any language beyond English) for the candidate to "
    f"do the job: his German is {je._LEVEL_LABEL} and improving, so a native/"
    "C1-fluent requirement is a hard eligibility blocker he cannot currently "
    "meet, not a 'domain gap' to wave off. This is deliberate: an otherwise-"
    "perfect job he is disqualified from is worse than useless to surface, it's "
    "noise. Distinguish that HARD requirement ('fluent German required', "
    "'German native speaker', 'verhandlungssicheres Deutsch', 'C1/C2 German') "
    "from a SOFT one ('German is a plus', 'German helpful but not required', a "
    f"level at or below his own {je._LEVEL_LABEL}, or the role states English "
    "as the working language) -- a soft requirement is a minor signal like any "
    "other soft criterion, stays out of hard_blockers, and should NOT trigger "
    "this auto-SKIP. The INTERMEDIATE zone ('working/professional proficiency "
    f"in German', or a required level in the {je._INTERMEDIATE_LABEL} band) is "
    f"also NOT a blocker: it is above his {je._LEVEL_LABEL} but below fluent, "
    "and it is exactly what he is studying towards -- set "
    "language_requirement='intermediate', report it as a prominent concern, "
    "and score normally; the pipeline caps such jobs at REVIEW so he judges "
    "case by case. "
    "Weighting: the candidate is a deliberate career changer, open to "
    "unfamiliar business domains (finance, healthcare, retail, etc.) -- do NOT "
    "penalize lack of domain experience if the technical/functional role "
    "itself matches. Technical fit and logistics (location, permit, "
    "availability) drive the score; culture fit and domain unfamiliarity are "
    "minor, non-decisive signals. Perspective: score as the candidate would "
    "score it for himself -- how excited he'd be, how much he'd grow -- not as "
    "an HR recruiter filtering out risk. Role SHAPE -- ownership, building vs. "
    "maintaining, hands-on AI/automation work -- matters more than a perfect "
    "skills or domain checklist match.\n"
    "Known failure modes, each seen in production: never inflate confidence on "
    "thin text -- if get_posting_text reports truncated=true (or very few "
    "characters), the requirements section was never seen, so keep the score "
    "conservative and say in concerns that the requirements were not visible; "
    "the pipeline caps such jobs at REVIEW. A hard language requirement is "
    "disqualifying: it belongs in hard_blockers with a score below the SKIP "
    "threshold, no matter how perfect the rest of the match. And a 'blocker' "
    "that says there is NO blocker ('None -- English is the working language') "
    "is not one: hard_blockers stays empty."
)


def _agent_system() -> str:
    """Profile + decision rules + live outcome evidence. Built per job (not at
    import) so a run always scores against the freshest calibration, and so
    tests can point the tracker DB elsewhere."""
    return je.PROFILE + "\n" + AGENT_SYSTEM_PROMPT + "\n" + je.load_outcome_calibration()


def _build_tools(job, holder):
    """The agent's toolbox for ONE posting. Every tool wraps existing
    deterministic code -- the model investigates, it never computes. The
    record_decision payload lands in `holder`, per job, so the record is
    built in code afterwards (never from the model's freeform JSON)."""
    desc_full = job.get("description") or ""

    def get_posting_text():
        return {
            # Same head+tail window the deterministic scorer reads.
            "text": je._excerpt(desc_full),
            "chars": len(desc_full),
            "truncated": is_truncated_description(desc_full),
        }

    def check_language_requirement():
        evidence = []
        for line in desc_full.splitlines():
            if je._HARD_LANGUAGE_RE.search(line) or je._INTERMEDIATE_LANGUAGE_RE.search(line):
                evidence.append(re.sub(r"\s+", " ", line).strip())
            if len(evidence) >= 5:
                break
        tier = je.detect_language_requirement_tier(desc_full)
        if tier is None:
            # The deterministic detector deliberately ignores soft mentions
            # ('German is a plus'); report them as 'soft' so the agent knows
            # languages came up at all.
            tier = "soft" if re.search(je._LANG_NAME_RE, desc_full, re.IGNORECASE) else "none"
        return {"tier": tier,
                "evidence": evidence,
                "candidate_level": je.GERMAN_LEVEL or "unknown"}

    def get_candidate_profile():
        p = je.PROFILE_DATA
        return {"role": p.get("role", ""),
                "target_role": p.get("target_role", ""),
                "summary": p.get("summary", ""),
                "skills": p.get("skills", {}),
                "language_levels": p.get("language_levels", {}),
                "languages": p.get("languages", "")}

    def get_outcome_calibration():
        import tracker_updater
        return tracker_updater.get_outcome_summary()

    def search_past_evaluations(query):
        """Case-insensitive substring match over the committed evaluation
        history (company/title). Pure lookup -- no LLM in here."""
        q = str(query or "").strip().lower()
        if not q or not os.path.isdir(je.HISTORY_DIR):
            return []
        matches = []
        for fname in sorted(os.listdir(je.HISTORY_DIR), reverse=True):  # newest date first
            if not (fname.startswith("evaluations_") and fname.endswith(".json")):
                continue
            try:
                with open(os.path.join(je.HISTORY_DIR, fname), encoding="utf-8") as f:
                    records = json.load(f)
            except (ValueError, OSError):
                continue
            for rec in records:
                j = rec.get("job", {})
                haystack = f"{j.get('company', '')} {j.get('title', '')}".lower()
                if q in haystack:
                    matches.append({"company": j.get("company", ""),
                                    "title": j.get("title", ""),
                                    "score": rec.get("score"),
                                    "decision": rec.get("decision")})
            if len(matches) >= 5:
                break
        return matches[:5]

    def record_decision(score, decision, rationale, concerns=None,
                        hard_blockers=None, language_requirement="none"):
        holder["payload"] = {"score": score, "decision": decision,
                             "rationale": rationale,
                             "concerns": concerns or [],
                             "hard_blockers": hard_blockers or [],
                             "language_requirement": language_requirement}
        return {"ok": True}

    no_args = {"type": "object", "properties": {}}
    return [
        Tool("get_posting_text",
             "The posting text (the same head+tail excerpt window the pipeline "
             "scores from), its TRUE character count, and whether the source "
             "truncated it mid-sentence. Call this first.",
             no_args, get_posting_text),
        Tool("check_language_requirement",
             "Deterministic scan of the FULL posting text for language "
             "requirements beyond English: tier none|soft|intermediate|hard "
             "with the matched lines as evidence, plus the candidate's own "
             "level. A 'hard' tier is disqualifying -- it belongs in "
             "hard_blockers.",
             no_args, check_language_requirement),
        Tool("get_candidate_profile",
             "Who the candidate is: current role, target role, summary, "
             "skills, and language levels.",
             no_args, get_candidate_profile),
        Tool("get_outcome_calibration",
             "Real outcomes of past recommendations (applications sent, "
             "responses, interviews by score band). Calibrate: if high scores "
             "keep earning silence, be stricter.",
             no_args, get_outcome_calibration),
        Tool("search_past_evaluations",
             "How similar jobs scored before: case-insensitive substring "
             "match over committed evaluation history (company/title), up to "
             "5 most recent matches with score and decision.",
             {"type": "object",
              "properties": {"query": {"type": "string"}},
              "required": ["query"]},
             search_past_evaluations),
        Tool("record_decision",
             "TERMINAL: records your final decision. You MUST call this "
             "exactly once, when the investigation is done -- a run without "
             "it is an evaluation ERROR. score is 0-100; decision is "
             "APPLY|REVIEW|SKIP; hard_blockers lists ONLY true hard "
             "eligibility blockers (empty when none).",
             {"type": "object",
              "properties": {
                  "score": {"type": "integer", "minimum": 0, "maximum": 100},
                  "decision": {"type": "string", "enum": ["APPLY", "REVIEW", "SKIP"]},
                  "rationale": {"type": "string"},
                  "concerns": {"type": "array", "items": {"type": "string"}},
                  "hard_blockers": {"type": "array", "items": {"type": "string"}},
                  "language_requirement": {"type": "string",
                                           "enum": ["none", "soft", "intermediate", "hard"]}},
              "required": ["score", "decision", "rationale"]},
             record_decision),
    ]


def _agent_error_record(job, err_msg, trace=None):
    """An agent failure is an ERROR like any other: no invented score, the
    reason in the record, the trace kept for diagnosis."""
    rec = je._error_record(job, err_msg)
    rec["agent_rationale"] = None
    rec["agent_decision"] = None
    rec["agent_trace"] = trace or []
    return rec


def _finalize_nudge(client, result, tools, holder, trace):
    """One reserved call when the investigation starved the terminal call.

    The five informational tools can fill the whole iteration cap before
    record_decision gets a turn -- measured 2026-08-25 on the first agent
    run: three capped evaluations, every trace the same five calls in the
    same order. Rather than erroring a job the agent already understood,
    append an explicit order to finalize and give it exactly one more call.
    Any other tool call in the answer is logged in the trace and ignored:
    the budget is spent either way."""
    schemas = [{"type": "function",
                "function": {"name": t.name, "description": t.description,
                             "parameters": t.parameters}}
               for t in tools]
    nudge = {"role": "user", "content": (
        "Investigation budget exhausted. Call record_decision NOW with your "
        "best judgement from the evidence already gathered. Do NOT call any "
        "other tool.")}
    try:
        resp = client.chat_completion((result.get("messages") or []) + [nudge],
                                      max_tokens=1000, tools=schemas or None,
                                      tool_choice="auto" if schemas else None)
    except Exception:
        return None
    for call in resp.get("tool_calls") or []:
        function = call.get("function") or {}
        name = function.get("name", "")
        raw = function.get("arguments") or ""
        try:
            arguments = json.loads(raw) if raw.strip() else {}
        except ValueError:
            arguments = {}
        trace.append({"name": name, "arguments": arguments})
        if name == "record_decision":
            try:
                tools_by_name = {t.name: t for t in tools}
                tools_by_name[name].function(**arguments)
            except Exception:
                return None
            return holder.get("payload")
    return None


def evaluate_job(job):
    """Agent-mode twin of job_evaluator.evaluate_job: same record shape (plus
    agent_rationale / agent_decision / agent_trace), the decision reached by
    a tool-using agent instead of a single JSON call."""
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    location = job.get("location", "Unknown")
    desc_full = job.get("description", "") or ""

    # Same honesty rule as the deterministic evaluator: below
    # MIN_DESCRIPTION_CHARS there is no number at all -- and no API call.
    if len(desc_full.strip()) < MIN_DESCRIPTION_CHARS:
        print(f"NOT EVALUATED -> no posting text ({len(desc_full.strip())} chars); "
              f"no score invented, no API call spent")
        return je._no_text_record(job, len(desc_full.strip()))

    holder = {}
    tools = _build_tools(job, holder)
    # Today's date grounds timeline reasoning (notice period vs start date),
    # same as the deterministic prompt.
    user = (f"Today's date: {datetime.now(timezone.utc).date().isoformat()}\n"
            f"Job: {title} at {company}\nLocation: {location}\n"
            f"URL: {job.get('url', '')}\n"
            "Investigate this posting with your tools, then finalize by "
            "calling record_decision.")

    try:
        client = KimiClient()
        result = run_agent(client, _agent_system(), user, tools,
                           max_iterations=agent_max_iterations(), max_tokens=2000)
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        print(f"AGENT ERROR -> decision ERROR (no fake score) | {err_msg[:200]}")
        je.log_error(f"{title} @ {company}: {err_msg}")
        return _agent_error_record(job, f"API error: {err_msg}")

    trace = result.get("tool_calls_made", [])
    payload = holder.get("payload")
    if payload is None and result.get("stopped_reason") == "iteration_cap":
        payload = _finalize_nudge(client, result, tools, holder, trace)
    if payload is None:
        reason = result.get("stopped_reason")
        if reason == "error":
            msg = "Agent run failed at the API level"
        elif reason == "iteration_cap":
            msg = (f"Agent never called record_decision "
                   f"({agent_max_iterations()}-iteration cap and finalization "
                   "nudge both spent)")
        else:
            msg = "Agent ended without calling record_decision"
        print(f"AGENT ERROR -> {msg}")
        je.log_error(f"{title} @ {company}: {msg}")
        return _agent_error_record(job, f"Evaluation error: {msg}", trace=trace)

    score = je._sanitize_score(payload.get("score"))
    if score is None:
        # A missing/unparseable score is an evaluation failure, NOT a silent
        # 50/SKIP -- the same no-fake-scores rule as the deterministic path.
        msg = f"Agent returned no usable score: {payload.get('score')!r}"
        print(f"EVALUATION ERROR -> {msg}")
        je.log_error(f"{title} @ {company}: {msg}")
        return _agent_error_record(job, f"Evaluation error: {msg}", trace=trace)

    agent_decision = str(payload.get("decision") or "").strip().upper()
    agent_rationale = str(payload.get("rationale") or "")

    raw_concerns = payload.get("concerns") or []
    if not isinstance(raw_concerns, list):
        raw_concerns = [raw_concerns]
    concerns = [str(c) for c in raw_concerns]
    soft_concerns = [c for c in concerns if not c.startswith("Blocker:")]

    model_blockers = payload.get("hard_blockers")
    if model_blockers is None:
        model_blockers = [c[len("Blocker:"):].strip() for c in concerns
                          if c.startswith("Blocker:")]
    if not isinstance(model_blockers, list):
        model_blockers = [model_blockers]
    real_blockers = [b for b in (str(x).strip() for x in model_blockers)
                     if b and not is_spurious_blocker(b)]

    # Too short to judge, OR long enough to look complete while actually
    # being a cut-off teaser -- identical definition to the evaluator.
    insufficient_info = (len(desc_full.strip()) < MIN_DESCRIPTION_CHARS
                         or is_truncated_description(desc_full))

    # Defence in depth, deterministic over the FULL text: a hard language
    # requirement the agent missed (or chose to ignore) still locks the job.
    tier = je.detect_language_requirement_tier(desc_full)
    lang_evidence = je.detect_hard_language_requirement(desc_full)

    lang_req = str(payload.get("language_requirement", "") or "").strip().lower()
    if lang_req in ("none", "soft", "intermediate", "hard"):
        language_gap_intermediate = lang_req == "intermediate"
    else:
        # Field absent/invalid: deterministic fallback, same as the evaluator.
        language_gap_intermediate = tier == "intermediate"
        if language_gap_intermediate:
            soft_concerns.append(
                f"Intermediate language requirement detected (working proficiency/"
                f"{je._INTERMEDIATE_LABEL}): above his {je._LEVEL_LABEL}, below fluent")
    if not real_blockers and (lang_req == "hard" or tier == "hard"):
        real_blockers = [lang_evidence or "Hard language requirement flagged by the agent"]

    red_flags = [f"Blocker: {b}" for b in real_blockers] + soft_concerns
    if insufficient_info:
        if is_truncated_description(desc_full):
            red_flags.append(
                "Low confidence: the posting text is CUT OFF (the source returns only "
                "the opening pitch). The requirements section was never seen, so any "
                "disqualifier in it is invisible -- open the original before trusting "
                "this score")
        else:
            red_flags.append("Low confidence: posting text under "
                             f"{MIN_DESCRIPTION_CHARS} chars -- score is title-based")
    if not red_flags and score < THRESHOLD_REVIEW:
        red_flags = ["Score below threshold"]

    key_match_points = [agent_rationale] if agent_rationale and score >= THRESHOLD_REVIEW else []

    record = {
        "score": score,
        "hard_blockers": real_blockers,
        "insufficient_info": insufficient_info,
        "language_gap_intermediate": language_gap_intermediate,
        "key_match_points": key_match_points,
        "red_flags": red_flags,
        "job": je._job_block(job),
        "technical_fit": agent_rationale,
        "contextual_fit": "",
        "salary_estimate": "Not disclosed",
        "culture_fit": "",
        "concerns": concerns,
        "agent_rationale": agent_rationale,
        "agent_decision": agent_decision,
        "agent_trace": trace,
    }

    # Decision is ALWAYS derived locally, never trusted verbatim from the
    # agent: thresholds on the score + the hard-blocker lock (business rule,
    # no exception) + the low-confidence cap. See utils.effective_decision.
    decision = effective_decision(record)
    if agent_decision and agent_decision != decision:
        print(f"  Note: agent proposed decision={agent_decision} but local rules map to "
              f"{decision} (score={score}, blockers={len(real_blockers)}, "
              f"insufficient={insufficient_info}); using {decision}.")

    record["recommendation"] = decision
    record["decision"] = decision
    record["materials_needed"] = ["cv"] if decision == "APPLY" else []
    return record


def main():
    if evaluation_mode() == "rules":
        # The deterministic evaluator, completely unchanged.
        return je.main()
    return _agent_main()


def _agent_main():
    """Same flow as job_evaluator.main() in agent mode."""
    if je.PROFILE_IS_FALLBACK:
        # Scoring the whole run against a generic profile would silently
        # distort every score -- fail loud instead.
        print("FATAL: config/candidate_profile.json missing/invalid. "
              "Refusing to evaluate with the generic fallback profile.")
        sys.exit(1)

    os.makedirs("digests", exist_ok=True)

    def _no_jobs():
        # Same quiet-day contract as the deterministic main: "latest" must
        # mean THIS run, or the heartbeat and the doc generator disagree.
        print("No jobs to evaluate.")
        with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as fh:
            json.dump([], fh)

    try:
        with open("digests/new_jobs_latest.json", "r", encoding="utf-8") as f:
            jobs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _no_jobs(); return
    if not jobs:
        _no_jobs(); return

    cap = max_evaluations_per_run()
    if len(jobs) > cap:
        print(f"Cost guard: {len(jobs)} jobs found, capping at {cap} "
              f"(set MAX_EVALUATIONS_PER_RUN to change).")
        jobs = jobs[:cap]

    print(f"Loaded {len(jobs)} jobs. Agent mode, 1 by 1 with 2s delay...\n")
    evaluations = []
    for i, job in enumerate(jobs, 1):
        title = job.get("title", "Unknown")[:50]
        print(f"[{i}/{len(jobs)}] {title}...", end=" ", flush=True)
        ev = evaluate_job(job)
        evaluations.append(ev)
        mismatch = ""
        proposed = ev.get("agent_decision")
        if proposed and proposed != ev.get("decision"):
            mismatch = f" [agent proposed {proposed} -> effective {ev.get('decision')}]"
        print(f"score={ev.get('score', '?')} ({ev.get('decision', '?')}) "
              f"mode=agent{mismatch}")
        if i < len(jobs):
            time.sleep(2)

    scored = [e for e in evaluations if e.get("score") is not None]
    errors = [e for e in evaluations if e.get("decision") == "ERROR"]
    apply_ = [e for e in scored if e["score"] >= THRESHOLD_APPLY]
    review = [e for e in scored if THRESHOLD_REVIEW <= e["score"] < THRESHOLD_APPLY]
    skip = [e for e in scored if e["score"] < THRESHOLD_REVIEW]

    blind = [e for e in evaluations if e.get("insufficient_info")]

    print(f"\n{'=' * 50}")
    print(f"DONE: {len(evaluations)} jobs | APPLY: {len(apply_)} | REVIEW: {len(review)} | "
          f"SKIP: {len(skip)} | ERROR: {len(errors)}")
    if blind:
        print(f"Scored on partial text (short or truncated): {len(blind)}/{len(evaluations)} "
              f"-- these are capped at REVIEW by design.")
    print(f"{'=' * 50}")
    with open("digests/job_evaluations_latest.json", "w", encoding="utf-8") as f:
        json.dump(evaluations, f, ensure_ascii=False, indent=2)

    je.append_history(evaluations)

    # Close the score -> outcome loop, exactly like the deterministic main.
    recommended = [e for e in evaluations if e.get("decision") == "APPLY"]
    if recommended:
        try:
            import tracker_updater
            recorded = 0
            for e in recommended:
                j = e.get("job", {})
                if tracker_updater.record_recommendation(
                        j.get("company", "Unknown"), j.get("title", "Unknown"),
                        j.get("url", ""), e.get("score")):
                    recorded += 1
            print(f"Tracker: {recorded}/{len(recommended)} APPLY job(s) recorded as 'recommended'.")
        except Exception as exc:
            # Tracker bookkeeping must never fail a scoring run.
            print(f"WARNING: could not record recommendations: {exc}")

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
