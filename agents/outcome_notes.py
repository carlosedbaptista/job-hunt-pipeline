"""
outcome_notes.py  —  Private outcome signals: dismissal reasons and
application motivations, deliberately kept OUT of tracker/jobs.db.

Why not in jobs.db? jobs.db is committed to a public repo -- it backs the
tracker and the dashboard. Why the candidate dismissed a recommended job
("too junior", "band too low") and why he applied to another one ("they do
real-time inference, I want in") is personal job-hunt strategy: in a
committed artefact it would hand companies and recruiters his negotiation
position. These signals live in tracker/outcome_notes.json instead, which
is gitignored and reaches CI only as a base64 secret (OUTCOME_NOTES_B64,
restored at workflow time). The only thing that ever leaves the file is
aggregated prompt text for the scorer at runtime -- never raw notes.
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from deduplicator import normalize, normalize_company

NOTES_PATH = "tracker/outcome_notes.json"

DISMISSAL_CATEGORIES = [
    "salary",
    "tech_mismatch",
    "company_culture",
    "location",
    "seniority",
    "language",
    "other",
]

PRIVACY_REMINDER = (
    "PRIVATE: this note lives only in tracker/outcome_notes.json (local, "
    "gitignored) -- never in jobs.db, the dashboard, or any committed artefact.\n"
    "Sync it to CI with: base64 -w0 tracker/outcome_notes.json | gh secret set OUTCOME_NOTES_B64"
)


def _empty_notes() -> dict:
    return {"dismissals": [], "motivations": []}


def _key(company: str, title: str) -> tuple:
    """Job identity for these notes: the same normalisation the deduplicator
    uses, so 'BLP Digital AG' recorded from a digest and 'blp digital' typed
    from memory are the same job."""
    return (normalize_company(company), normalize(title))


def load_notes(path: str = NOTES_PATH) -> dict:
    """Returns {'dismissals': [...], 'motivations': [...]}. A missing or
    corrupt file means 'no signals recorded yet', not an error -- callers
    (the scorer above all) must never crash on it."""
    if not os.path.exists(path):
        return _empty_notes()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):  # ValueError covers json.JSONDecodeError
        return _empty_notes()
    if not isinstance(data, dict):
        return _empty_notes()
    return {
        section: data.get(section) if isinstance(data.get(section), list) else []
        for section in ("dismissals", "motivations")
    }


def _save_notes(notes: dict, path: str) -> None:
    """Atomic write (temp file in the same directory + rename): a crash
    mid-write must never leave a truncated file that load_notes would then
    silently read as 'no signals'."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record_dismissal(
    company: str, title: str, category: str,
    note: str = "", url: str = "", path: str = NOTES_PATH,
) -> dict:
    """Records why the candidate dismissed a recommended job. Re-dismissing
    the same (normalized) company+title REPLACES the previous entry -- a
    change of mind is an update, not a duplicate."""
    if category not in DISMISSAL_CATEGORIES:
        raise ValueError(
            f"Unknown dismissal category {category!r}. "
            f"Valid categories: {', '.join(DISMISSAL_CATEGORIES)}"
        )
    notes = load_notes(path)
    key = _key(company, title)
    notes["dismissals"] = [
        d for d in notes["dismissals"]
        if _key(d.get("company", ""), d.get("title", "")) != key
    ]
    entry = {
        "company": company,
        "title": title,
        "url": url,
        "category": category,
        "note": note,
        "date": datetime.now(timezone.utc).isoformat(),
    }
    notes["dismissals"].append(entry)
    _save_notes(notes, path)
    return entry


def record_motivation(
    company: str, title: str, note: str,
    url: str = "", path: str = NOTES_PATH,
) -> dict:
    """Records why the candidate wants to apply to a job. Same replace
    semantics as dismissals: one current motivation per job."""
    notes = load_notes(path)
    key = _key(company, title)
    notes["motivations"] = [
        m for m in notes["motivations"]
        if _key(m.get("company", ""), m.get("title", "")) != key
    ]
    entry = {
        "company": company,
        "title": title,
        "url": url,
        "note": note,
        "date": datetime.now(timezone.utc).isoformat(),
    }
    notes["motivations"].append(entry)
    _save_notes(notes, path)
    return entry


def dismissal_summary(path: str = NOTES_PATH) -> str:
    """Prompt-ready aggregate for the scorer: counts per category with the
    companies in parentheses. Counts only what the file actually holds --
    never inflated. '' when there are no dismissals, so the scorer's prompt
    simply omits the block."""
    dismissals = load_notes(path)["dismissals"]
    if not dismissals:
        return ""
    by_category = {}
    for d in dismissals:
        by_category.setdefault(d.get("category", "other"), []).append(d.get("company", ""))
    # Known categories first, in DISMISSAL_CATEGORIES order (deterministic
    # prompt text); anything hand-edited into the file still gets reported.
    ordered = [c for c in DISMISSAL_CATEGORIES if c in by_category]
    ordered += [c for c in by_category if c not in DISMISSAL_CATEGORIES]
    parts = [
        f"{category}: {len(by_category[category])} ({', '.join(by_category[category])})"
        for category in ordered
    ]
    return (
        "Candidate dismissal signals (from his private notes): "
        f"{len(dismissals)} dismissed -- "
        + "; ".join(parts)
        + ". Treat these as strong negative signals for similar roles."
    )


def motivation_for(company: str, title: str, path: str = NOTES_PATH) -> str:
    """The candidate's stated reason for applying to that job, '' when none.
    Matches on normalized company+title, same as the deduplicator."""
    key = _key(company, title)
    for m in load_notes(path)["motivations"]:
        if _key(m.get("company", ""), m.get("title", "")) == key:
            return m.get("note", "")
    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Record private outcome signals (dismissals, motivations). "
                    "Stored in tracker/outcome_notes.json -- gitignored, never committed."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_dismiss = sub.add_parser("dismiss", help="Record why you dismissed a recommended job.")
    p_dismiss.add_argument("company")
    p_dismiss.add_argument("title")
    p_dismiss.add_argument("--category", required=True, choices=DISMISSAL_CATEGORIES)
    p_dismiss.add_argument("--note", default="")
    p_dismiss.add_argument("--url", default="")

    p_motivate = sub.add_parser("motivate", help="Record why you want to apply to a job.")
    p_motivate.add_argument("company")
    p_motivate.add_argument("title")
    p_motivate.add_argument("--note", required=True)
    p_motivate.add_argument("--url", default="")

    sub.add_parser("list", help="Print all dismissals and motivations.")
    sub.add_parser("summary", help="Print the scorer-ready dismissal summary.")

    args = parser.parse_args()

    # NOTES_PATH is passed explicitly (read from the module namespace at call
    # time, not a def-time default) so tests can point the CLI at tmp_path.
    if args.command == "dismiss":
        record_dismissal(args.company, args.title, args.category,
                         note=args.note, url=args.url, path=NOTES_PATH)
        print(f"OK: dismissal recorded ({args.category}): {args.company} — {args.title}")
        print(PRIVACY_REMINDER)
    elif args.command == "motivate":
        record_motivation(args.company, args.title, args.note,
                          url=args.url, path=NOTES_PATH)
        print(f"OK: motivation recorded: {args.company} — {args.title}")
        print(PRIVACY_REMINDER)
    elif args.command == "list":
        notes = load_notes(path=NOTES_PATH)
        print(f"Dismissals ({len(notes['dismissals'])}):")
        for d in notes["dismissals"]:
            line = f"  - {d.get('company', '')} — {d.get('title', '')} [{d.get('category', '')}]"
            if d.get("note"):
                line += f" -- {d['note']}"
            print(line)
        print(f"Motivations ({len(notes['motivations'])}):")
        for m in notes["motivations"]:
            print(f"  - {m.get('company', '')} — {m.get('title', '')}: {m.get('note', '')}")
    elif args.command == "summary":
        print(dismissal_summary(path=NOTES_PATH))


if __name__ == "__main__":
    main()
