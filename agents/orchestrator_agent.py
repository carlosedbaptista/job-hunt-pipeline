"""
orchestrator_agent.py -- the run-level judgement layer of the daily pipeline.

Replaces the three fixed post-evaluation workflow steps (doc_generator,
high_score_alert, followup_sender) behind a flag, and adds two abilities the
fixed chain never had: re-evaluation of stale REVIEW-band jobs on quiet days,
and an automatic fallback to the legacy chain when the agent itself fails.

Mode is chosen at run time (ORCHESTRATION_MODE, read dynamically like
decision_agent.evaluation_mode):

  rules (default) -> runs the three legacy scripts in the current workflow
                     order, each continue-on-error exactly like the workflow
                     steps it stands in for;
  agent           -> ONE tool-using agent looks at the run state and decides
                     what the run still needs: documents for APPLY jobs,
                     high-score alerts, follow-up drafts, and possibly
                     re-evaluation of borderline jobs. The model proposes;
                     the code disposes: the doc-generation freshness rail and
                     the re-evaluation cap are enforced here, never delegated
                     to the model. The run MUST end in a finish_run call --
                     without it the orchestrator degrades to the legacy chain,
                     so a bad orchestrator day is exactly the old behavior.

Whatever happens in agent mode, main() returns 0 and writes a run log to
digests/orchestrator_log_<YYYYMMDD_HHMM>.json: the pipeline's commit step
must never be blocked by the orchestrator.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_runtime import Tool, run_agent
from kimi_client import KimiClient
from deduplicator import make_hash
from utils import (THRESHOLD_APPLY, THRESHOLD_REVIEW, effective_decision,
                   load_json, now_iso, now_str, save_json)

import decision_agent
import doc_generator
import followup_sender
import high_score_alert
import job_evaluator as je
import tracker_updater

EVALUATIONS_FILE = os.path.join("digests", "job_evaluations_latest.json")
ERROR_LOG = os.path.join("digests", "evaluation_errors.txt")

# The fixed pre-agent pipeline, in the workflow's step order.
LEGACY_CHAIN = ["agents/doc_generator.py",
                "agents/high_score_alert.py",
                "agents/followup_sender.py"]

DEFAULT_ORCHESTRATOR_MAX_ITERATIONS = 8
DEFAULT_ORCHESTRATOR_MAX_REEVALUATIONS = 5

# REVIEW-band jobs from history files this many days back are eligible for
# re-evaluation (most recent first).
REEVALUATION_WINDOW_DAYS = 14


def orchestration_mode():
    """'rules' (default) or 'agent'. Read dynamically -- never a module-level
    constant -- so tests and CI can switch via env without re-importing. An
    invalid or blank value warns and falls back to 'rules': a typo in a
    workflow input must never silently change how the run is orchestrated."""
    raw = os.environ.get("ORCHESTRATION_MODE")
    if raw is None:
        return "rules"
    value = raw.strip().lower()
    if value in ("rules", "agent"):
        return value
    print(f"WARNING: ORCHESTRATION_MODE={raw!r} is not 'rules' or 'agent' -- "
          "falling back to 'rules'.")
    return "rules"


def _int_env(name, default):
    """Same dynamic pattern (and failure philosophy) as
    utils.max_evaluations_per_run: blank or invalid falls back to the default
    with a printed warning instead of aborting the run."""
    raw = (os.environ.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        if raw:
            print(f"  {name}={raw!r} is not a number -- using {default}.")
        return default
    return value if value > 0 else default


def orchestrator_max_iterations():
    """Tool-loop budget for the whole run."""
    return _int_env("ORCHESTRATOR_MAX_ITERATIONS", DEFAULT_ORCHESTRATOR_MAX_ITERATIONS)


def orchestrator_max_reevaluations():
    """Hard cap on re-scored borderline jobs per run (cost guard). Enforced
    in CODE inside reevaluate_borderline -- never delegated to the model."""
    return _int_env("ORCHESTRATOR_MAX_REEVALUATIONS", DEFAULT_ORCHESTRATOR_MAX_REEVALUATIONS)


# ─── rules mode: the legacy chain, unchanged ─────────────────────────────────

def _run_legacy_chain(prefix=""):
    """The three post-evaluation stages in workflow order. Each is tolerant
    of failure -- a nonzero exit is printed and the chain continues, which
    mirrors the workflow's continue-on-error on these steps."""
    for script in LEGACY_CHAIN:
        print(f"{prefix}[orchestrator] stage: {script}")
        try:
            completed = subprocess.run([sys.executable, script])
        except Exception as e:
            print(f"{prefix}[orchestrator] {script} failed to launch: "
                  f"{type(e).__name__}: {e} -- continuing")
            continue
        if completed.returncode:
            print(f"{prefix}[orchestrator] {script} exited "
                  f"{completed.returncode} -- continuing (continue-on-error)")


# ─── run state ───────────────────────────────────────────────────────────────

def _read_evaluations():
    """Today's evaluation records; missing or not-a-list means zeros."""
    data = load_json(EVALUATIONS_FILE)
    return data if isinstance(data, list) else []


def _evaluations_fresh(records):
    """True iff the evaluations file exists AND was produced today. The
    embedded evaluated_at stamps decide when any record carries one (a file
    left over from a failed run keeps yesterday's dates even if something
    touched it since); the file mtime is the fallback for records without
    timestamps. The pipeline's clock is UTC -- the cron fires at 05:00/12:00
    UTC and the evaluator stamps evaluated_at in UTC -- so 'today' here must
    be the UTC date, or a runner at UTC+2 refuses its own fresh file for the
    two hours after local midnight."""
    if not os.path.exists(EVALUATIONS_FILE):
        return False
    today = datetime.now(timezone.utc).date().isoformat()
    embedded = [str(ev.get("evaluated_at") or "")[:10]
                for ev in records if isinstance(ev, dict) and ev.get("evaluated_at")]
    if embedded:
        return max(embedded) == today
    mtime = datetime.fromtimestamp(os.path.getmtime(EVALUATIONS_FILE), timezone.utc).date().isoformat()
    return mtime == today


def _stale_application_count():
    """Applications gone quiet: status='sent', no response, applied more
    than 7 days ago. A small SQL read -- tracker_updater has no such query
    (followup_sender's own query additionally filters on the re-draft
    window, which is a different number)."""
    try:
        tracker_updater.init_applications_table()
        conn = sqlite3.connect(tracker_updater.DB_PATH)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        n = conn.execute(
            "SELECT COUNT(*) FROM applications "
            "WHERE status = 'sent' AND response_type IS NULL AND date_applied < ?",
            (cutoff,)).fetchone()[0]
        conn.close()
        return n
    except Exception as e:
        print(f"  [orchestrator] could not count stale applications: "
              f"{type(e).__name__}: {e}")
        return 0


def get_run_state():
    """What today's run produced. Pure read -- no LLM in here."""
    records = _read_evaluations()
    counts = {"APPLY": 0, "REVIEW": 0, "SKIP": 0, "ERROR": 0}
    apply_jobs = []
    for ev in records:
        if not isinstance(ev, dict):
            continue
        decision = effective_decision(ev)
        counts[decision] = counts.get(decision, 0) + 1
        if decision == "APPLY":
            j = ev.get("job") or {}
            apply_jobs.append({"company": j.get("company", ""),
                               "title": j.get("title", ""),
                               "score": ev.get("score")})
    errors_tail = []
    if os.path.exists(ERROR_LOG):
        try:
            with open(ERROR_LOG, encoding="utf-8") as f:
                errors_tail = f.read().splitlines()[-10:]
        except OSError:
            errors_tail = []
    return {"mode": "agent",
            "fresh": _evaluations_fresh(records),
            "evaluations": len(records),
            "decisions": counts,
            "apply_jobs": apply_jobs,
            "recent_errors": errors_tail,
            "stale_applications": _stale_application_count()}


# ─── stage tools (each wraps EXISTING code -- import, never copy) ────────────

def generate_docs():
    """Tailored CV/CL for today's APPLY jobs. Hard rail: refuses when the
    evaluations are stale. The old workflow achieved the same by not running
    the step after a failed evaluator -- a failed run leaves yesterday's file
    in place, and doc generation would burn Kimi calls regenerating CVs that
    already exist."""
    if not get_run_state()["fresh"]:
        print("[orchestrator] generate_docs REFUSED: evaluations are stale")
        return {"error": "stale evaluations - refusing to spend on yesterday's jobs"}
    print("[orchestrator] generating documents for today's APPLY jobs")
    doc_generator.main()
    manifest = load_json(doc_generator.DOCS_MANIFEST) or {}
    docs = manifest.get("documents") or []
    return {"documents_generated": len(docs),
            "companies": [d.get("company", "?") for d in docs]}


def send_high_score_alerts():
    """Immediate e-mail alert for the top matches. The signal is the diff of
    digests/alerted_jobs.json: a job is recorded there only after its alert
    actually went out, and each job alerts once, ever."""
    print("[orchestrator] sending high-score alerts")
    before = high_score_alert.load_alerted()
    high_score_alert.main()
    after = high_score_alert.load_alerted()
    return {"alerts_sent": len(after - before)}


def draft_followups():
    """Follow-up drafts for applications gone quiet (emailed to the
    candidate, never to the recruiter). The signal is how many applications
    left the eligible set -- a draft that went out is stamped and leaves the
    query, a failed send stays eligible."""
    print("[orchestrator] drafting follow-ups for stale applications")
    before = len(followup_sender.get_stale_applications(days_threshold=7))
    followup_sender.draft_followups()
    after = len(followup_sender.get_stale_applications(days_threshold=7))
    return {"drafts": max(0, before - after), "still_eligible": after}


# ─── re-evaluation of borderline jobs ────────────────────────────────────────

def _hash_of(rec):
    j = rec.get("job") or {}
    return make_hash(j.get("company", ""), j.get("title", ""), j.get("location", ""))


def _hashes_scored_today():
    """Jobs today's run already scored must not be scored twice: anything in
    today's history file or in the latest evaluations is off-limits for
    re-evaluation."""
    hashes = set()
    today_file = os.path.join(
        je.HISTORY_DIR, f"evaluations_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json")
    for source in (today_file, EVALUATIONS_FILE):
        for rec in load_json(source) or []:
            if isinstance(rec, dict):
                hashes.add(_hash_of(rec))
    return hashes


def _history_files_last(days):
    """data/history/evaluations_YYYYMMDD.json files within the window,
    newest first. File names carry UTC dates (the evaluator stamps them
    so), so the window boundary must use the UTC date as well."""
    if not os.path.isdir(je.HISTORY_DIR):
        return []
    today = datetime.now(timezone.utc).date()
    picked = []
    for fname in os.listdir(je.HISTORY_DIR):
        m = re.fullmatch(r"evaluations_(\d{8})\.json", fname)
        if not m:
            continue
        try:
            fdate = datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if 0 <= (today - fdate).days <= days:
            picked.append((fdate, os.path.join(je.HISTORY_DIR, fname)))
    picked.sort(reverse=True)
    return [path for _, path in picked]


def _review_candidates():
    """REVIEW-band records from the last REEVALUATION_WINDOW_DAYS days, most
    recent first, each job once, skipping anything already scored today."""
    skip = _hashes_scored_today()
    seen = set()
    candidates = []
    for path in _history_files_last(REEVALUATION_WINDOW_DAYS):
        records = load_json(path)
        if not isinstance(records, list):
            continue
        for rec in reversed(records):  # appended chronologically: tail is newest
            if not isinstance(rec, dict):
                continue
            h = _hash_of(rec)
            if h in seen or h in skip:
                continue
            seen.add(h)
            score = rec.get("score")
            if score is None or not (THRESHOLD_REVIEW <= score < THRESHOLD_APPLY):
                continue
            if effective_decision(rec) != "REVIEW":
                continue
            candidates.append(rec)
    return candidates


def reevaluate_borderline(max_jobs):
    """Re-scores a few recent REVIEW-band jobs through the decision agent.
    The cap is enforced HERE, in code: the model can ask for 50 and still
    gets at most ORCHESTRATOR_MAX_REEVALUATIONS."""
    try:
        requested = int(max_jobs)
    except (TypeError, ValueError):
        return {"error": f"max_jobs must be an integer, got {max_jobs!r}"}
    n = min(requested, orchestrator_max_reevaluations())
    if n <= 0:
        return {"reevaluated": [], "note": "re-evaluation cap is 0"}
    candidates = _review_candidates()[:n]
    if not candidates:
        return {"reevaluated": [],
                "note": "no eligible REVIEW-band jobs in the last "
                        f"{REEVALUATION_WINDOW_DAYS} days"}

    print(f"[orchestrator] re-evaluating {len(candidates)} borderline job(s) "
          f"(asked for {requested}, cap {orchestrator_max_reevaluations()})")
    run_ts = datetime.now(timezone.utc).isoformat()
    results, new_records = [], []
    for rec in candidates:
        job = dict(rec.get("job") or {})
        old_score = rec.get("score")
        old_decision = effective_decision(rec)
        print(f"[orchestrator]   {job.get('title', '?')} @ {job.get('company', '?')} "
              f"(was {old_score}/{old_decision})")
        entry = {"company": job.get("company", ""), "title": job.get("title", ""),
                 "old_score": old_score, "old_decision": old_decision}
        try:
            new_rec = decision_agent.evaluate_job(job)
        except Exception as e:
            entry.update(new_score=None, new_decision="ERROR",
                         error=f"{type(e).__name__}: {e}")
            results.append(entry)
            continue
        new_rec.setdefault("evaluated_at", run_ts)
        new_records.append(new_rec)
        new_decision = effective_decision(new_rec)
        entry.update(new_score=new_rec.get("score"), new_decision=new_decision)
        results.append(entry)
        if new_decision == "APPLY":
            try:
                j = new_rec.get("job", {})
                tracker_updater.record_recommendation(
                    j.get("company", "Unknown"), j.get("title", "Unknown"),
                    j.get("url", ""), new_rec.get("score"))
            except Exception as exc:
                # Tracker bookkeeping must never fail the run.
                print(f"WARNING: could not record recommendation: {exc}")

    if new_records:
        latest = _read_evaluations()
        latest.extend(new_records)
        save_json(EVALUATIONS_FILE, latest)
        je.append_history(new_records)
    return {"reevaluated": results, "cap": n}


# ─── the agent's toolbox + prompts ───────────────────────────────────────────

ORCHESTRATOR_SYSTEM_PROMPT = (
    "You are the orchestrator of today's job-hunt run. The run's jobs are "
    "already fetched and scored; you decide what the run still needs and do "
    "it through the tools. Start with get_run_state: it reports what today "
    "produced (decision counts, the APPLY jobs, recent evaluation errors, "
    "applications gone quiet) and whether the evaluations are FRESH, meaning "
    "written by today's run. Then act, in the order that fits the state:\n"
    "- generate_docs writes tailored CV/cover letters for today's APPLY jobs. "
    "It hard-refuses when the evaluations are stale: never spend on "
    "yesterday's jobs.\n"
    "- send_high_score_alerts e-mails an immediate alert for the top matches "
    "(each job alerts once, ever).\n"
    "- draft_followups prepares follow-up drafts for applications with no "
    "response after 7+ days; drafts go to the candidate, never to the "
    "recruiter.\n"
    "- reevaluate_borderline re-scores a few recent REVIEW-band jobs through "
    "the decision agent. Reach for it when the day was quiet or budget "
    "remains, and ask for a small number -- it is capped in code.\n"
    "Rules: never generate documents for stale evaluations. Respect the "
    "budgets -- every stage spends LLM calls. Report only what the tools "
    "return: never invent counts, companies or outcomes. When the run is "
    "complete you MUST finalize by calling finish_run with a short summary "
    "of what was done and the rationale behind it. A run that ends without "
    "finish_run is treated as a failure, and the pipeline falls back to the "
    "fixed legacy chain."
)


def _build_tools(holder):
    """One toolbox for the whole run. Every tool wraps existing code; the
    finish_run payload lands in `holder` so the log is written in code, not
    from the model's freeform text."""

    def finish_run(summary, rationale=""):
        holder["payload"] = {"summary": str(summary), "rationale": str(rationale)}
        return {"ok": True}

    no_args = {"type": "object", "properties": {}}
    return [
        Tool("get_run_state",
             "What today's run produced: decision counts by effective "
             "decision, the APPLY jobs (company/title/score), the tail of "
             "the evaluation error log, how many sent applications went "
             "quiet (>7 days, no response), and `fresh` -- true only when "
             "the evaluations were written today. Call this first.",
             no_args, get_run_state),
        Tool("generate_docs",
             "Generate tailored CV/cover letters for today's APPLY jobs "
             "(wraps doc_generator.main). HARD RAIL: refuses with an error "
             "when the run state is stale -- yesterday's jobs never get new "
             "documents.",
             no_args, generate_docs),
        Tool("send_high_score_alerts",
             "E-mail an immediate alert for today's top matches (wraps "
             "high_score_alert.main). Returns how many NEW alerts went out; "
             "already-alerted jobs are skipped by the underlying step.",
             no_args, send_high_score_alerts),
        Tool("draft_followups",
             "Draft follow-up e-mails for sent applications with no response "
             "after 7+ days (wraps followup_sender.draft_followups). Drafts "
             "go to the candidate for review, never to the recruiter.",
             no_args, draft_followups),
        Tool("reevaluate_borderline",
             "Re-score recent REVIEW-band jobs (last "
             f"{REEVALUATION_WINDOW_DAYS} days, not already scored today) "
             "through the decision agent and append the new records to "
             "today's evaluations. For quiet days or leftover budget. "
             "max_jobs is capped in code by "
             "ORCHESTRATOR_MAX_REEVALUATIONS.",
             {"type": "object",
              "properties": {"max_jobs": {"type": "integer", "minimum": 1}},
              "required": ["max_jobs"]},
             reevaluate_borderline),
        Tool("finish_run",
             "TERMINAL: closes the run. You MUST call this exactly once when "
             "everything the run needed is done -- a run without it falls "
             "back to the legacy chain. summary: what was done; rationale: "
             "why.",
             {"type": "object",
              "properties": {"summary": {"type": "string"},
                             "rationale": {"type": "string"}},
              "required": ["summary"]},
             finish_run),
    ]


# ─── run log ─────────────────────────────────────────────────────────────────

def _tool_results_summary(messages):
    """One compact line per tool result, content truncated -- the full
    payloads stay in the conversation, the log keeps the shape."""
    out = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content")
        out.append({"name": m.get("name"),
                    "result": str(content)[:300] if content is not None else None})
    return out


def _write_log(result, fallback_used, agent_summary, agent_rationale):
    os.makedirs("digests", exist_ok=True)
    path = os.path.join("digests", f"orchestrator_log_{now_str()}.json")
    save_json(path, {
        "ts": now_iso(),
        "mode": "agent",
        "stopped_reason": result.get("stopped_reason"),
        "iterations": result.get("iterations"),
        "usage": result.get("usage"),
        "tool_calls_made": result.get("tool_calls_made") or [],
        "tool_results_summary": _tool_results_summary(result.get("messages") or []),
        "fallback_used": fallback_used,
        "agent_summary": agent_summary,
        "agent_rationale": agent_rationale,
    })
    return path


# ─── entry points ────────────────────────────────────────────────────────────

def _agent_main():
    print("=" * 50)
    print("ORCHESTRATOR (agent mode)")
    print("=" * 50)

    holder = {}
    tools = _build_tools(holder)
    user = (f"Today's date: {datetime.now(timezone.utc).date().isoformat()}\n"
            "The daily run has finished fetching and scoring jobs. Look at "
            "the run state, do what this run needs with the tools, and "
            "finalize with finish_run.")

    try:
        client = KimiClient()
        result = run_agent(client, ORCHESTRATOR_SYSTEM_PROMPT, user, tools,
                           max_iterations=orchestrator_max_iterations(),
                           max_tokens=2000)
    except Exception as e:
        # KimiClient() itself raising (no API key) lands here; an API outage
        # mid-run is reported by run_agent as stopped_reason='error'. Both
        # degrade to the legacy chain below.
        print(f"WARNING: orchestrator agent could not run: "
              f"{type(e).__name__}: {e}")
        result = {"final": None, "messages": [], "tool_calls_made": [],
                  "iterations": 0, "stopped_reason": "error", "usage": {}}

    payload = holder.get("payload")
    fallback_used = payload is None
    if fallback_used:
        print(f"WARNING: orchestrator ended without finish_run "
              f"(stopped_reason={result.get('stopped_reason')}).")
        print("[fallback] running the legacy three-stage chain -- a bad "
              "orchestrator day degrades to exactly the old behavior.")
        _run_legacy_chain(prefix="[fallback] ")
        agent_summary = agent_rationale = None
    else:
        agent_summary = payload.get("summary")
        agent_rationale = payload.get("rationale")

    log_path = _write_log(result, fallback_used, agent_summary, agent_rationale)

    calls = result.get("tool_calls_made") or []
    print(f"\n{'=' * 50}")
    print(f"ORCHESTRATOR DONE: {len(calls)} tool call(s) in "
          f"{result.get('iterations')} iteration(s) | "
          f"stopped={result.get('stopped_reason')} | fallback={fallback_used}")
    if agent_summary:
        print(f"Summary: {agent_summary}")
    print(f"Log: {log_path}")
    print(f"{'=' * 50}")
    # The commit step must never be blocked by the orchestrator.
    return 0


def main():
    if orchestration_mode() == "rules":
        print("=" * 50)
        print("ORCHESTRATOR (rules mode: fixed legacy chain)")
        print("=" * 50)
        _run_legacy_chain()
        return 0
    return _agent_main()


if __name__ == "__main__":
    sys.exit(main())
