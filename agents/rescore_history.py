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

# Job titles are scraped from third-party boards and some carry emoji. On a
# Windows console (cp1252) printing one raises UnicodeEncodeError, which on
# 2026-08-23 killed this tool after 96 successful re-scores -- a print
# statement destroying an hour of LLM calls. Replace what cannot be encoded
# rather than letting the terminal decide whether the run survives.
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except (AttributeError, OSError):
    pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import (MIN_DESCRIPTION_CHARS, effective_decision,
                   is_truncated_description, load_json, save_json)
from posting_resolver import resolve as resolve_posting
from posting_resolver import resolve_from_url

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


def dedupe_pass(apply_changes: bool):
    """Collapses repeated evaluations of the same posting within one day.

    Re-running the pipeline with `reevaluate` scores jobs that are already in
    the day's file, appending a second and third record for the same posting.
    That is a testing artefact, not history: it inflates the counts, and the
    dashboard then shows the same job several times.

    Same day, same posting, keep the LAST -- it was scored under the newest
    rules. Records from DIFFERENT days are left alone: a job legitimately
    re-evaluated a week later is real history worth keeping.
    """
    from deduplicator import make_hash

    removed_total = 0
    for path in iter_files():
        data = load_json(path, default=None)
        if not isinstance(data, list):
            continue
        last_position = {}
        for position, record in enumerate(data):
            job = record.get("job") or {}
            key = make_hash(job.get("company", ""), job.get("title", ""),
                            job.get("location", ""))
            last_position[key] = position
        keep = set(last_position.values())
        if len(keep) == len(data):
            continue
        removed = len(data) - len(keep)
        removed_total += removed
        print(f"  {path}: {len(data)} -> {len(keep)} ({removed} duplicate(s) dropped)")
        if apply_changes:
            save_json(path, [r for i, r in enumerate(data) if i in keep])

    print(f"Duplicate pass: {removed_total} repeated evaluation(s) "
          f"{'removed' if apply_changes else 'would be removed'}.")
    return 0


def recover_pass(limit: int, apply_changes: bool):
    """Turns NOT_EVALUATED records into real scores where the posting can
    still be found.

    These are jobs whose alert card carried no description, so no number was
    ever produced. Most cannot be helped -- their company field was mangled
    by the parser bug fixed on 2026-08-23, and the resolver looks a posting
    up by company. The ones that still carry a usable employer name can be
    read from that employer's own board and scored properly.

    A miss leaves the record exactly as it was: not evaluated, and honest
    about it.
    """
    import job_evaluator
    from email_parser_local import _looks_like_a_role

    if job_evaluator.PROFILE_IS_FALLBACK:
        print("FATAL: config/candidate_profile.json is missing or invalid.")
        return 1

    targets = []
    for path in iter_files():
        data = load_json(path, default=None)
        if not isinstance(data, list):
            continue
        for position, record in enumerate(data):
            if not isinstance(record, dict) or record.get("decision") != "NOT_EVALUATED":
                continue
            job = record.get("job") or {}
            company = str(job.get("company") or "")
            usable_company = (company and company != "Unknown" and len(company) <= 45
                              and not company.lower().startswith("unknown")
                              and not _looks_like_a_role(company))
            # A URL is worth trying even when the company field is garbage:
            # the LinkedIn guest endpoint returns the employer name too, so
            # the record repairs itself. That covers the 108 records whose
            # company was mangled by the parser bug.
            usable_url = str(job.get("url") or "").startswith(("http://", "https://"))
            if usable_company or usable_url:
                targets.append((path, position, record))

    print(f"Recovery: {len(targets)} not-evaluated records carry a usable employer "
          f"name (of the rest, the company field itself is unusable).")
    targets = targets[:limit]
    if not apply_changes:
        print(f"(dry run -- would attempt {len(targets)})")
        return 0

    recovered = 0
    by_file = {}
    for n, (path, position, record) in enumerate(targets, 1):
        job = dict(record.get("job") or {})
        title, company = job.get("title", "?"), job.get("company", "")
        print(f"[{n}/{len(targets)}] {title[:44]} @ {company[:22]}...", end=" ", flush=True)
        # The aggregator link first: it is the posting itself rather than a
        # guess at which board the employer uses, and it repairs the company
        # field on the way. The ATS boards are the fallback.
        hit = None
        try:
            hit = resolve_from_url(job.get("url", ""))
        except Exception:
            hit = None
        if not hit and company and company != "Unknown":
            try:
                hit = resolve_posting(company, title)
            except Exception as e:
                print(f"resolver error ({type(e).__name__})")
                continue
        if not hit:
            print("unreachable (aggregator blocks, and no public board)")
            continue
        job["description"] = hit["text"]
        job["description_source"] = hit["provider"]
        # The posting page is authoritative for the title and employer too.
        # Taking them repairs records the parser mangled, and stops a
        # navigation card ("Jobs similar to ...") from keeping its own title
        # while wearing a real posting's text -- which is exactly what the
        # first recovery pass produced, at 87/APPLY.
        if hit.get("matched_title"):
            job["title"] = hit["matched_title"]
        if hit.get("company"):
            job["company"] = hit["company"]
        fresh = job_evaluator.evaluate_job(job)
        if fresh.get("decision") in ("ERROR", "NOT_EVALUATED"):
            print("still not evaluable")
            continue
        fresh["evaluated_at"] = record.get("evaluated_at")
        fresh["recovered"] = True
        by_file.setdefault(path, load_json(path, default=[]))
        by_file[path][position] = fresh
        save_json(path, by_file[path])
        recovered += 1
        print(f"{len(hit['text'])} chars -> {fresh.get('score')} ({fresh.get('decision')})")

    print(f"Recovered {recovered} of {len(targets)} into real scores.")
    return 0


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
    resolved_count = 0
    for n, i in enumerate(order, 1):
        record = records[i]
        job = dict(record.get("job") or {})
        title = job.get("title", "?")
        print(f"[{n}/{len(order)}] {title[:50]}...", end=" ", flush=True)

        # Recover the real posting BEFORE spending the LLM call. Without this
        # the pass re-scores the same 500-character teaser it scored the first
        # time and changes nothing that matters: every Adzuna description ever
        # stored was truncated, so the requirements the score should turn on
        # were never in the record. Costs no API quota, only time, and a miss
        # is fine -- the job keeps its teaser and stays capped at REVIEW.
        text = str(job.get("description") or "")
        if is_truncated_description(text) or len(text.strip()) < MIN_DESCRIPTION_CHARS:
            try:
                hit = resolve_posting(job.get("company", ""), title)
            except Exception:
                hit = None
            if hit:
                job["description"] = hit["text"]
                job["description_source"] = hit["provider"]
                resolved_count += 1
                print(f"[+{len(hit['text'])} chars from {hit['provider']}]",
                      end=" ", flush=True)

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
        # Written NOW, not at the end. This pass costs one LLM call per job
        # and takes an hour; batching the writes meant a single unexpected
        # exception threw away everything already paid for. It did exactly
        # that once.
        save_json(path, by_file[path])
        print(f"{old_score} -> {fresh.get('score')} ({fresh.get('decision')})")

    print(f"Recovered the full posting for {resolved_count} of {len(order)} "
          f"from the employers' own job boards; the rest kept their teaser.")
    for path in by_file:
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
    parser.add_argument("--recover", action="store_true",
                        help="find postings for NOT_EVALUATED records on the "
                             "employer's board and score them properly")
    parser.add_argument("--dedupe", action="store_true",
                        help="collapse repeated evaluations of the same posting "
                             "within one day (testing artefacts)")
    parser.add_argument("--reset-seen", action="store_true",
                        help="clear unapplied rows from seen_jobs so those jobs "
                             "re-enter the pipeline")
    args = parser.parse_args()

    print("=" * 70)
    print("RESCORE HISTORY" + ("" if args.apply else "  (DRY RUN)"))
    print("=" * 70)

    # Duplicates first: no point spending an LLM call re-scoring a record
    # that is about to be dropped as a testing artefact.
    if args.dedupe:
        dedupe_pass(args.apply)
        print()

    deterministic_pass(args.apply)

    if args.recover:
        print()
        recover_pass(args.limit, args.apply)

    if args.full:
        print()
        full_pass(args.limit, args.apply)

    if args.reset_seen:
        print()
        reset_seen(21, args.apply)


if __name__ == "__main__":
    main()
