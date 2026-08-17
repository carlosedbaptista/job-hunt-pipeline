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


def decision_from_score(score) -> str:
    """Maps a numeric score to a decision. None (API error) maps to ERROR."""
    if score is None:
        return "ERROR"
    if score >= THRESHOLD_APPLY:
        return "APPLY"
    if score >= THRESHOLD_REVIEW:
        return "REVIEW"
    return "SKIP"


def max_evaluations_per_run() -> int:
    """Per-run LLM call cap (cost guard). Read dynamically so tests and CI
    can override via env without re-importing modules."""
    return int(os.environ.get("MAX_EVALUATIONS_PER_RUN", "30"))


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
    """Remove duplicate jobs based on company + title + location."""
    seen = set()
    unique = []
    for job in jobs:
        company = (job.get("company") or job.get("company", "")).lower().strip()
        title = (job.get("title") or job.get("title", "")).lower().strip()
        location = (job.get("location") or job.get("location", "")).lower().strip()
        key = (company, title, location)
        if key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


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
