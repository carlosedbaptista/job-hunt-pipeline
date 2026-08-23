#!/usr/bin/env python3
"""
description_enricher.py -- Fills in missing job descriptions from Adzuna.

Why this exists
---------------
Jobs that arrive through the Gmail alert channel (LinkedIn, Glassdoor, XING,
jobs.ch) are parsed out of an HTML e-mail card: title, company, location, a
tracking URL, and nothing else. There is no description in the e-mail at all.

The consequence is measurable in `data/history/`: 169 of the first 190
evaluations carry `insufficient_info: true`, i.e. Kimi scored them from the
job title alone, and `utils.effective_decision` (correctly) caps such a job at
REVIEW forever. Only Adzuna-sourced jobs -- the ones that do ship a
description -- ever produced an APPLY.

This step closes that gap without scraping anything: for each job with no
usable description it asks the Adzuna API, which is already integrated and
whose free quota is only ~a quarter used, whether it knows the same posting.
When a confident match comes back, the real description is attached and the
job is scored on its actual content instead of six words of title.

Safety properties (this step must never damage a run):
  * a wrong description is far worse than no description, so matching is
    deliberately conservative -- see `_match_score`;
  * it is budget-capped (`ENRICH_MAX_LOOKUPS`) so it cannot eat the Adzuna
    daily quota the ingestor depends on;
  * no credentials, no network, no match, any exception: the job is left
    exactly as it was and the pipeline continues.

Usage: python agents/description_enricher.py
       (reads and rewrites digests/new_jobs_latest.json)
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from adzuna_ingestor import fetch_adzuna, normalize_job
from deduplicator import normalize, normalize_company
from utils import (MIN_DESCRIPTION_CHARS, is_truncated_description,
                   load_json, save_json)
from posting_resolver import resolve as resolve_posting

JOBS_FILE = os.path.join("digests", "new_jobs_latest.json")

# Cost guard, mirroring MAX_EVALUATIONS_PER_RUN. The daily ingestor already
# spends up to ADZUNA_MAX_HITS (35) calls per run, twice a day; Adzuna's free
# tier allows 100/day, so the enricher gets a small, explicit slice.
ENRICH_MAX_LOOKUPS = int(os.environ.get("ENRICH_MAX_LOOKUPS", "12"))

# How far back Adzuna may look for the same posting. Alert e-mails lag the
# original posting by a few days, so this is wider than the ingestor's 7.
ENRICH_MAX_DAYS_OLD = int(os.environ.get("ENRICH_MAX_DAYS_OLD", "30"))
# How many truncated postings to chase on the employers' ATS boards per run.
# Costs no Adzuna quota (different hosts entirely), only runner time, and the
# per-company cache means repeated employers are nearly free.
RESOLVE_MAX_JOBS = int(os.environ.get("RESOLVE_MAX_JOBS", "30"))

# Match thresholds. Title similarity is Jaccard over normalized word sets.
# With a confirmed company match a partial title match is enough ("Working
# Student Data Analyst 60-80%" vs "Working Student Data Analyst"); without
# one, only an exact normalized title is accepted.
TITLE_SIMILARITY_WITH_COMPANY = 0.6

# Noise that job boards put in titles and Adzuna's free-text search does not
# handle well ("(f/m/d)", "60-80%", "100%", "m/w/d").
_TITLE_NOISE_RE = re.compile(
    r"\(\s*[fmwdhx](?:\s*[/|]\s*[fmwdhx])+\s*\)|\b\d{1,3}\s*[-–]\s*\d{1,3}\s*%|\b\d{1,3}\s*%",
    re.IGNORECASE,
)


def search_terms(title: str) -> str:
    """The title reduced to plain words Adzuna can search on."""
    cleaned = _TITLE_NOISE_RE.sub(" ", title or "")
    cleaned = re.sub(r"[^\w\s&+-]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Very long titles ("... - Paid Media, Content & KI") return nothing;
    # the first words carry the role.
    return " ".join(cleaned.split()[:8])


def _title_similarity(a: str, b: str) -> float:
    """Jaccard over normalized word sets. 1.0 means the same title."""
    wa, wb = set(normalize(a).split()), set(normalize(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def _match_score(job, candidate):
    """How confident we are that `candidate` (an Adzuna posting) is the same
    job as `job` (an e-mail card). Returns None when it is not a match.

    Conservative by design: attaching the description of a *different* job
    would silently corrupt a score, which is worse than the blind score this
    step is trying to fix."""
    job_company = normalize_company(job.get("company", ""))
    cand_company = normalize_company(candidate.get("company", ""))
    similarity = _title_similarity(job.get("title", ""), candidate.get("title", ""))

    company_known = job_company not in ("", "unknown")
    if company_known:
        # One may carry a suffix the other drops ("Randstad" / "Randstad
        # Digital"), so accept a containment match on the token sequence.
        same_company = (
            job_company == cand_company
            or job_company in cand_company
            or cand_company in job_company
        )
        if not same_company:
            return None
        return similarity if similarity >= TITLE_SIMILARITY_WITH_COMPANY else None

    # No company to corroborate with: only an exact title match is trusted.
    return similarity if similarity >= 1.0 else None


def find_description(job, fetch=fetch_adzuna):
    """Looks the job up on Adzuna and returns the best-matching normalized
    posting, or None. `fetch` is injectable for tests."""
    terms = search_terms(job.get("title", ""))
    if len(terms) < 5:
        return None

    where = job.get("location") or "Zurich"
    if str(where).strip().lower() in ("unknown", ""):
        where = "Zurich"
    # Adzuna's `where` wants a locality, not "Zurich, Switzerland (Hybrid)".
    where = re.split(r"[,(]", str(where))[0].strip() or "Zurich"

    try:
        results = fetch(terms, where=where, max_days_old=ENRICH_MAX_DAYS_OLD)
    except Exception as e:  # network/HTTP problems must never break the run
        print(f"  [enrich] lookup failed for {job.get('title', '')[:40]}: "
              f"{type(e).__name__}: {str(e)[:90]}")
        return None

    best, best_score = None, 0.0
    for raw in results or []:
        candidate = normalize_job(raw)
        if len((candidate.get("description") or "").strip()) < MIN_DESCRIPTION_CHARS:
            continue
        score = _match_score(job, candidate)
        if score is not None and score > best_score:
            best, best_score = candidate, score
    return best


def needs_description(job) -> bool:
    return len((job.get("description") or "").strip()) < MIN_DESCRIPTION_CHARS


def needs_full_text(job) -> bool:
    """A description that exists but stops mid-sentence.

    Distinct from needs_description on purpose: these two failures have
    different cures. A missing description is fixed by an Adzuna lookup; a
    TRUNCATED one cannot be, because Adzuna is what truncated it -- every one
    of its descriptions is exactly 500 characters. Only the employer's own
    board has the rest."""
    return is_truncated_description(job.get("description"))


def resolve_full_texts(jobs, budget=None, resolver=resolve_posting):
    """Replaces truncated descriptions with the full posting from the
    employer's ATS. Returns (replaced, attempted).

    A miss is the common case and is not a failure: the job keeps its teaser
    and stays flagged insufficient_info, so it can be seen but never
    auto-APPLYed."""
    budget = RESOLVE_MAX_JOBS if budget is None else budget
    attempted = replaced = 0
    for job in jobs:
        if attempted >= budget:
            break
        if not needs_full_text(job):
            continue
        company, title = job.get("company", ""), job.get("title", "")
        if not company or not title or company.strip().lower() in _NOT_EMPLOYERS:
            continue
        attempted += 1
        try:
            hit = resolver(company, title)
        except Exception as e:
            print(f"  [resolver] {company}: {type(e).__name__}: {str(e)[:80]}")
            continue
        if not hit:
            continue
        job["description"] = hit["text"]
        job["description_source"] = hit["provider"]
        replaced += 1
        print(f"  [resolver] {title[:40]} @ {company[:24]} -> {hit['provider']}, "
              f"{len(hit['text'])} chars (was truncated at 500)")
    return replaced, attempted


# Adzuna puts the SOURCE BOARD in the company field for aggregated listings,
# so "Job-Room" is not an employer and no ATS board will ever match it.
# Skipping them keeps the budget for postings that can actually resolve.
_NOT_EMPLOYERS = {"job-room", "jobroom", "indeed", "linkedin", "glassdoor",
                  "jobs.ch", "jobscout24", "adzuna"}


def enrich_jobs(jobs, fetch=fetch_adzuna, budget=None):
    """Attaches real descriptions in place. Returns (enriched, attempted)."""
    budget = ENRICH_MAX_LOOKUPS if budget is None else budget
    enriched = attempted = 0

    for job in jobs:
        if attempted >= budget or not needs_description(job):
            continue
        attempted += 1
        match = find_description(job, fetch=fetch)
        if not match:
            continue

        job["description"] = match["description"]
        # Provenance: the score for this job was based on a posting matched
        # from another source, not on the text of the original alert.
        job["description_source"] = "adzuna_enrichment"
        job["enriched_from_url"] = match.get("url", "")
        for field in ("company", "location", "url"):
            if str(job.get(field, "Unknown")).strip() in ("Unknown", "", "None"):
                if match.get(field):
                    job[field] = match[field]
        enriched += 1
        print(f"  [enrich] {job['title'][:45]:45} <- {match['company'][:28]} "
              f"({len(match['description'])} chars)")

    return enriched, attempted


def main():
    jobs = load_json(JOBS_FILE, default=None)
    if not isinstance(jobs, list) or not jobs:
        print("Description enricher: no jobs to enrich.")
        return

    # Stage 2 first in the report, because it is the one that matters most:
    # a truncated description is the normal case, not the exception.
    truncated = [j for j in jobs if needs_full_text(j)]
    print(f"Description enricher: {len(truncated)}/{len(jobs)} descriptions are "
          f"TRUNCATED (the board ships only the first 500 chars, so the "
          f"requirements section is missing).")
    if truncated:
        try:
            replaced, attempted = resolve_full_texts(jobs)
            print(f"  Recovered the full posting for {replaced}/{attempted} from the "
                  f"employers' own job boards. The rest keep the teaser and stay "
                  f"capped at REVIEW.")
            if replaced:
                save_json(JOBS_FILE, jobs)
        except Exception as e:
            # Same contract as the Adzuna stage: an optimisation that fails
            # must leave the run exactly as good as it was without it.
            print(f"  Full-text resolution aborted ({type(e).__name__}: "
                  f"{str(e)[:120]}) -- jobs left unchanged.")

    blind = [j for j in jobs if needs_description(j)]
    print(f"Description enricher: {len(blind)}/{len(jobs)} jobs have no usable "
          f"description at all (would be scored on the title alone).")
    if not blind:
        return

    if not os.environ.get("ADZUNA_APP_ID") or not os.environ.get("ADZUNA_APP_KEY"):
        print("  Adzuna credentials not configured -- skipping enrichment.")
        return

    try:
        enriched, attempted = enrich_jobs(jobs)
    except Exception as e:
        # Enrichment is an optimisation: a failure here must leave the run
        # exactly as good as it was before this step existed.
        print(f"  Enrichment aborted ({type(e).__name__}: {str(e)[:120]}) -- "
              f"jobs left unchanged.")
        return

    print(f"  Enriched {enriched}/{attempted} looked up "
          f"({len(blind) - attempted} left blind by the {ENRICH_MAX_LOOKUPS}-lookup budget).")
    if enriched:
        save_json(JOBS_FILE, jobs)


if __name__ == "__main__":
    main()
