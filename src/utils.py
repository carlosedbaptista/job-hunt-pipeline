"""Shared utility functions for the job hunt pipeline."""
import json
import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Any

# Single source of truth for scoring thresholds. Evaluator, digest, dashboard,
# email notifier and alerts must all read from here (overridable via env).
THRESHOLD_APPLY = int(os.environ.get("THRESHOLD_APPLY", "80"))
THRESHOLD_REVIEW = int(os.environ.get("THRESHOLD_REVIEW", "70"))

# Below this much real posting text there is not enough signal for a
# confident evaluation: the evaluator marks such a job `insufficient_info`
# and effective_decision() caps it at REVIEW. It lives here (not only in
# job_evaluator) because agents/description_enricher.py uses the same
# definition of "no usable description" to decide what to look up, and the
# two must never drift apart.
MIN_DESCRIPTION_CHARS = int(os.environ.get("MIN_DESCRIPTION_CHARS", "200"))


def is_truncated_description(text) -> bool:
    """True when the posting text is a cut-off teaser rather than the posting.

    Measured on 2026-08-23 over every Adzuna record ever stored: 917 of 917
    had a description of EXACTLY 500 characters, all ending mid-sentence. The
    search API truncates, and it is not a setting -- the full text is only on
    the employer's own page, which Adzuna hides behind JavaScript and which
    answers 403 to a runner.

    This mattered far more than the length suggests. What survives the cut is
    the opening pitch; what is lost is the requirements list, which is where
    the disqualifiers live. The Avaloq AI Software Engineer posting scored
    82/APPLY on its first 500 characters and 58/SKIP on the full text, which
    demands 5 years of full-stack, 3 years of applied ML and a B.Sc. None of
    that was visible. The 200-char floor did not catch it: 500 looks like a
    real description and is not one.

    So a truncated description counts as insufficient information, which caps
    the decision at REVIEW. The system cannot see the requirements, so it must
    not claim the job is a match -- it hands the judgement to the candidate
    instead, and never auto-generates a CV for it.
    """
    t = str(text or "").rstrip()
    if len(t) < 400:
        return False
    # An explicit marker beats any heuristic.
    if t.endswith(("...", "…", "�")):
        return True
    # Otherwise: long, and stops without finishing a sentence.
    return not t.endswith((".", "!", "?", '"', ")", ":", ";"))


# CEFR ladder, weakest first. Used to work out which language levels sit
# ABOVE the candidate's own -- the intermediate zone is not a fixed set of
# levels, it depends on where he currently is. Never hardcode a level in
# job_evaluator.py: it must come from config/candidate_profile.json.
CEFR_LEVELS = ["a1", "a2", "b1", "b2", "c1", "c2"]

# At or above this level a requirement is a hard eligibility blocker, whatever
# the candidate's own level: 'fluent/native/C1' is not a gap he closes in a
# notice period.
HARD_LEVEL_FLOOR = "c1"


def candidate_language_level(profile, language: str = "german") -> str:
    """The candidate's CEFR level in `language`, read from the profile's
    `language_levels` map (e.g. {"german": "A2"}). Returns "" when unknown,
    which callers treat as 'assume the weakest level' -- being conservative
    about a language gap is the safe direction."""
    levels = (profile or {}).get("language_levels") or {}
    raw = str(levels.get(language, "") or "").strip().lower()
    return raw if raw in CEFR_LEVELS else ""


def levels_above(level: str) -> list:
    """CEFR levels strictly above `level` and strictly below HARD_LEVEL_FLOOR:
    the 'intermediate zone' -- above what he has today, but not so far above
    that it is a hard blocker. For A2 that is B1 and B2; for B1, only B2."""
    floor = CEFR_LEVELS.index(HARD_LEVEL_FLOOR)
    start = CEFR_LEVELS.index(level) + 1 if level in CEFR_LEVELS else 0
    return CEFR_LEVELS[start:floor]


def decision_from_score(score) -> str:
    """Maps a numeric score to a decision. None (API error) maps to ERROR."""
    if score is None:
        return "ERROR"
    if score >= THRESHOLD_APPLY:
        return "APPLY"
    if score >= THRESHOLD_REVIEW:
        return "REVIEW"
    return "SKIP"


DEFAULT_MAX_EVALUATIONS_PER_RUN = 30


def max_evaluations_per_run() -> int:
    """Per-run LLM call cap (cost guard). Read dynamically so tests and CI
    can override via env without re-importing modules.

    An unset OR EMPTY value falls back to the default. The empty case is not
    hypothetical: a blank `workflow_dispatch` input arrives as an empty
    string, and os.environ.get then returns "" rather than the default, so
    int("") would abort the whole run. Same for a non-numeric typo: the cost
    guard failing closed on a bad value would stop the pipeline entirely,
    which is a worse outcome than using the default."""
    raw = (os.environ.get("MAX_EVALUATIONS_PER_RUN") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        if raw:
            print(f"  MAX_EVALUATIONS_PER_RUN={raw!r} is not a number -- "
                  f"using {DEFAULT_MAX_EVALUATIONS_PER_RUN}.")
        return DEFAULT_MAX_EVALUATIONS_PER_RUN
    return value if value > 0 else DEFAULT_MAX_EVALUATIONS_PER_RUN


# A 'blocker' that actually says there is NO blocker ("None", "none --
# German not required", "N/A"): the model emits these to sound thorough,
# and treating the 'Blocker:' prefix alone as authoritative would SKIP the
# best jobs (2026-08-17 smoke test: the single highest-scoring posting came
# back with "Blocker: None -- English working language explicitly stated").
_SPURIOUS_BLOCKER_RE = re.compile(
    r"^\s*(?:none\b|no\b|n[ /]?a\b|keine\w*\b|not\b)"
    r"|\b(?:not required|no german|no language requirement|none required|not needed|not mandatory)\b",
    re.IGNORECASE,
)


def is_spurious_blocker(text: str) -> bool:
    return bool(_SPURIOUS_BLOCKER_RE.search(str(text)))


def hard_blockers_of(ev) -> list:
    """Real hard-eligibility blockers of an evaluation record. Reads the
    structured `hard_blockers` field; for records written before it existed,
    falls back to 'Blocker: '-prefixed entries in red_flags/concerns.
    Spurious ('None'-style) entries are filtered either way."""
    raw = ev.get("hard_blockers")
    if raw is None:
        raw = [str(c)[len("Blocker:"):].strip()
               for c in (ev.get("red_flags") or ev.get("concerns") or [])
               if str(c).startswith("Blocker:")]
    if not isinstance(raw, list):
        raw = [raw]
    return [b for b in (str(x).strip() for x in raw)
            if b and not is_spurious_blocker(b)]


def has_hard_blocker(ev) -> bool:
    return bool(hard_blockers_of(ev))


def effective_decision(ev) -> str:
    """The single place that turns an evaluation record into a decision:
    thresholds on the score, then the hard-blocker lock (business rule: an
    unmet hard eligibility requirement is an automatic SKIP no matter how
    high the score -- the score stays visible, the decision is capped),
    then the low-confidence cap (a posting with too little text to evaluate
    never earns automatic APPLY / CV-CL generation)."""
    score = ev.get("score")
    # A posting whose text was never captured is NOT_EVALUATED, which is not
    # the same as ERROR: nothing failed, there was simply nothing to read. It
    # carries no score, so it cannot be ranked or compared, and it can never
    # appear as a high number attached to a cautious decision.
    if ev.get("no_posting_text") or ev.get("decision") == "NOT_EVALUATED":
        return "NOT_EVALUATED"
    if score is None or ev.get("decision") == "ERROR":
        return "ERROR"
    if has_hard_blocker(ev):
        return "SKIP"
    decision = decision_from_score(score)
    # Low-confidence caps: never auto-APPLY (nor auto-generate CV/CL) on a
    # bare title, and never on an intermediate language gap (working
    # proficiency / B2 required is above the candidate's B1 but below
    # fluent -- his call, case by case; 2026-08-17 product decision).
    if decision == "APPLY" and (ev.get("insufficient_info") or ev.get("language_gap_intermediate")):
        return "REVIEW"
    return decision


def deduplicate_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate jobs, keeping the most informative copy of each.

    The key is the same normalization the cross-run SQLite dedup uses
    (`deduplicator.make_hash`: accents transliterated, punctuation dropped,
    legal suffixes like AG/GmbH stripped, location reduced to its locality).
    It used to be a plain `.lower().strip()` on the raw fields, which is
    strictly weaker than the hash applied one step later: "Zurich" vs
    "Zürich, Switzerland", or "BLP Digital" vs "BLP Digital AG", slipped
    through here and cost a full LLM evaluation each.

    When two records collide, the one with the longer description wins
    (sources differ: an e-mail alert card carries no description at all,
    while the same posting from Adzuna carries 4000 chars, and whichever
    happened to be ingested first used to win). Missing fields on the
    winner are backfilled from the loser."""
    from deduplicator import normalize, normalize_company, normalize_location

    winners: Dict[Any, Dict[str, Any]] = {}
    order: List[Any] = []
    for job in jobs:
        key = (normalize_company(job.get("company") or ""),
               normalize(job.get("title") or ""),
               normalize_location(job.get("location") or ""))
        current = winners.get(key)
        if current is None:
            winners[key] = job
            order.append(key)
            continue
        richer, poorer = (job, current) if _description_length(job) > _description_length(current) else (current, job)
        for field, value in poorer.items():
            if str(richer.get(field, "")).strip() in ("", "Unknown", "None"):
                if str(value).strip() not in ("", "Unknown", "None"):
                    richer[field] = value
        winners[key] = richer
    return [winners[k] for k in order]


def _description_length(job: Dict[str, Any]) -> int:
    return len((job.get("description") or "").strip())


def load_json(filepath: str, default: Any = None) -> Any:
    """Load JSON from file, return default if file missing or invalid.
    ValueError covers JSONDecodeError AND UnicodeDecodeError (a corrupt
    secret-restored file once crashed doc_generator with the latter)."""
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return default


def save_json(filepath: str, data: Any, indent: int = 2) -> None:
    """Save data as JSON to file, creating parent dirs if needed."""
    os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def now_str(fmt: str = "%Y%m%d_%H%M") -> str:
    """Return current UTC time as formatted string."""
    return datetime.now(timezone.utc).strftime(fmt)


def ensure_dir(path: str) -> str:
    """Create directory if it doesn't exist, return path."""
    os.makedirs(path, exist_ok=True)
    return path


# ─── Cheap relevance gate ────────────────────────────────────────────────────
# Broadening the Adzuna queries on 2026-08-23 multiplied the intake by 7.7 and
# brought consultancy, marketing and M&A roles with it: 49 of 56 titles in
# that day's run did not match the target shape at all. The scorer rejected
# every one of them correctly -- and each rejection cost an LLM call first,
# out of a cap of 30 that good jobs then could not reach.
#
# The obvious fix, a list of low-scoring keywords, was measured and REJECTED.
# Ranked by mean score, the worst offenders in the history were "praktikum"
# (19 jobs, max 45) and "werkstudent" (6, max 45) -- the German words for
# internship and working student, which are the core of what he is looking
# for. They score low because those particular postings did not fit, not
# because the word signals noise. Filtering them would have deleted his entire
# German-language funnel. "science" was on the list too, as in Data Science.
#
# So the gate is a CONJUNCTION: reject only when the title names a clearly
# non-technical FUNCTION and contains no technical term at all. Validated
# against all 278 scored titles in the history: it rejects 13% of them and the
# highest score among everything it rejects is 35, far below the SKIP
# threshold. "AI Engineer - Marketing Analytics" and "Data Scientist, Wealth
# Management" both survive, which is the point.
_NON_TECHNICAL_ROLE = re.compile(
    r"\b(marketing|videographer|content creator|copywriter|"
    r"account executive|sales|seller|recruit\w*|talent (acquisition|specialist|partner)|"
    r"wealth manage\w*|private banking|tax|audit\w*|legal counsel|"
    r"m&a|mergers|actuar\w*|underwrit\w*|customer success|"
    r"brand|social media|community manager|office manager|"
    r"receptionist|hr business partner)\b", re.I)

_TECHNICAL_TERM = re.compile(
    r"\b(engineer\w*|developer|software|data|ai|ml|machine learning|"
    r"analyst|analytics|scientist|automation|devops|sre|platform|"
    r"backend|frontend|fullstack|full.stack|cloud|python|informatik|"
    r"entwickler|agentic|llm|mlops)\b", re.I)


def is_off_target_title(title) -> bool:
    """True when the title is a non-technical role with no technical element.

    Deliberately narrow. A false positive here is invisible -- the posting is
    dropped before anyone sees it -- so the gate errs heavily towards letting
    things through and paying for the evaluation.
    """
    text = str(title or "")
    if not text.strip():
        return False
    return bool(_NON_TECHNICAL_ROLE.search(text)) and not _TECHNICAL_TERM.search(text)
