"""Shared utility functions for the job hunt pipeline."""
import json
import os
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
