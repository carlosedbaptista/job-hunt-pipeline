#!/usr/bin/env python3
"""
rescore_history.py -- Brings already-stored evaluations up to date with the
current rules, so the dashboard and the digest stop reflecting a version of
the pipeline that no longer exists.

Why this is needed
------------------
Records in `data/history/` were written under older rules. Two changes since
then alter what they should say, and neither is retroactive on its own:

  * the language band is now derived from the candidate's real CEFR level
    (`language_levels` in the profile). Under the old fixed band a "German B1
    required" posting was a soft mention; at A2 it is an intermediate gap,
    which caps the job at REVIEW;
  * `utils.effective_decision` is now the single source of the decision, so
    any record whose stored `decision` disagrees with it is stale.

Two passes, and the distinction matters:

  DETERMINISTIC (default, free, no API calls)
    Re-derives `language_gap_intermediate`, `insufficient_info` and the final
    decision from the text already stored on each record. This fixes
    everything the deterministic rules own. It cannot change a *score* --
    only the model can do that.

  FULL (--full, costs one LLM call per job)
    Re-runs agents/job_evaluator.evaluate_job on each record, so the score
    itself reflects the new prompt (target role, corrected language level).
    Capped by --limit, and it asks before spending.

Usage:
  python agents/rescore_history.py                 # dry run, deterministic
  python agents/rescore_history.py --apply         # write the changes
  python agents/rescore_history.py --full --limit 20 --apply
  python agents/rescore_history.py --reset-seen    # let jobs re-enter the pipeline
"""
import argparse
import glob
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import MIN_DESCRIPTION_CHARS, effective_decision, load_json, save_json

HISTORY_GLOB = os.path.join("data", "history", "evaluations_*.json")
LATEST = os.path.join("digests", "job_evaluations_latest.json")
MANUAL = os.path.join("digests", "manual_evaluations.json")
DB_PATH = os.environ.get("JOBS_DB_PATH", os.path.join("tracker", "jobs.db"))


def _record_text(record) -> str:
    """The posting text stored on the record. `job.description` holds the same
    excerpt the score was based on."""
    job = record.get("job") or {}
    return str(job.get("description") or "")


def redecide(record, tier_fn):
    """Re-derives the deterministic fields of one record under today's rules.
    Returns (changed, before_decision, after_decision)."""
    if record.get("decision") == "ERROR" or record.get("score") is None:
        return False, record.get("decision"), record.get("decision")

    before = record.get("decision")
    text = _record_text(record)

    # insufficient_info: recomputed, because the enricher may have attached a
    # real description to a record that was previously title-only.
    record["insufficient_info"] = len(text.strip()) < MIN_DESCRIPTION_CHARS

    # The intermediate-language cap, under the CURRENT band. Only ever set
    # here, never cleared blindly: a record the model itself flagged as
    # intermediate stays flagged.
    if tier_fn(text) == "intermediate":
        record["language_gap_intermediate"] = True

    after = effective_decision(record)
    record["decision"] = after
    record["recommendation"] = after
    record["materials_needed"] = ["cv"] if after == "APPLY" else []
    return (after != before), before, after


def iter_files():
    for path in sorted(glob.glob(HISTORY_GLOB)):
        yield path
    for path in (LATEST, MANUAL):
        if os.path.exists(path):
            yield path


def deterministic_pass(apply_changes: bool):
    from job_evaluator import detect_language_requirement_tier as tier_fn

    total = changed = 0
    transitions = {}
    for path in iter_files():
        records = load_json(path, default=None)
        if not isinstance(records, list):
            continue
        file_changed = False
        for record in records:
            if not isinstance(record, dict):
                continue
            total += 1
            did, before, after = redecide(record, tier_fn)
            if did:
                changed += 1
                file_changed = True
                key = f"{before} -> {after}"
                transitions[key] = transitions.get(key, 0) + 1
        if file_changed and apply_changes:
            save_json(path, records)
            print(f"  updated {path}")

    print(f"\nDeterministic pass: {changed}/{total} records change decision "
          f"under today's rules.")
    for key, count in sorted(transitions.items(), key=lambda kv: -kv[1]):
        print(f"  {key:22} {count}")
    if not apply_changes:
        print("\n(dry run -- re-run with --apply to write)")
    return changed


def full_pass(limit: int, apply_changes: bool):
    """Re-scores with the LLM. Costs one API call per job."""
    import job_evaluator

    if job_evaluator.PROFILE_IS_FALLBACK:
        print("FATAL: config/candidate_profile.json is missing or invalid. "
              "Re-scoring against the generic profile would corrupt the history.")
        return 1

    records, index = [], []
    for path in iter_files():
        data = load_json(path, default=None)
        if not isinstance(data, list):
            continue
        for position, record in enumerate(data):
            if isinstance(record, dict) and record.get("score") is not None:
                records.append(record)
                index.append((path, position))

    # Newest first: if the budget runs out, the freshest jobs are the ones
    # worth having correct.
    order = sorted(range(len(records)),
                   key=lambda i: str(records[i].get("evaluated_at") or ""),
                   reverse=True)[:limit]

    print(f"Full re-score: {len(order)} of {len(records)} scored records "
          f"(limit {limit}). One LLM call each.")
    if not apply_changes:
        print("(dry run -- re-run with --apply to actually call the API and write)")
        return 0

    by_file = {}
    for n, i in enumerate(order, 1):
        record = records[i]
        job = dict(record.get("job") or {})
        title = job.get("title", "?")
        print(f"[{n}/{len(order)}] {title[:50]}...", end=" ", flush=True)
        fresh = job_evaluator.evaluate_job(job)
        if fresh.get("decision") == "ERROR":
            print("ERROR (kept the old record)")
            continue
        old_score = record.get("score")
        fresh["evaluated_at"] = record.get("evaluated_at")
        fresh["rescored"] = True
        path, position = index[i]
        by_file.setdefault(path, load_json(path, default=[]))
        by_file[path][position] = fresh
        print(f"{old_score} -> {fresh.get('score')} ({fresh.get('decision')})")

    for path, data in by_file.items():
        save_json(path, data)
        print(f"  updated {path}")
    return 0


def reset_seen(days: int, apply_changes: bool):
    """Clears rows from seen_jobs so those postings re-enter the pipeline and
    get scored under the new rules, with a real description this time.

    Only rows with status 'new' are touched: anything you actually applied to
    is left alone."""
    if not os.path.exists(DB_PATH):
        print(f"No database at {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM seen_jobs WHERE status = 'new'").fetchone()[0]
    print(f"seen_jobs rows with status 'new': {count}")
    if apply_changes:
        conn.execute("DELETE FROM seen_jobs WHERE status = 'new'")
        conn.commit()
        print(f"Deleted {count} rows -- those postings come back on the next run "
              f"and are re-ingested, re-enriched and re-scored.")
    else:
        print("(dry run -- re-run with --apply to delete)")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="write the changes (default is a dry run)")
    parser.add_argument("--full", action="store_true",
                        help="also re-score with the LLM (costs one call per job)")
    parser.add_argument("--limit", type=int, default=30,
                        help="max jobs to re-score in --full mode (default 30)")
    parser.add_argument("--reset-seen", action="store_true",
                        help="clear unapplied rows from seen_jobs so those jobs "
                             "re-enter the pipeline")
    args = parser.parse_args()

    print("=" * 70)
    print("RESCORE HISTORY" + ("" if args.apply else "  (DRY RUN)"))
    print("=" * 70)

    deterministic_pass(args.apply)

    if args.full:
        print()
        full_pass(args.limit, args.apply)

    if args.reset_seen:
        print()
        reset_seen(21, args.apply)


if __name__ == "__main__":
    main()
