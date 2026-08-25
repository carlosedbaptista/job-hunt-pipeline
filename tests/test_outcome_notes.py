"""
test_outcome_notes.py -- private outcome signals (dismissals + motivations).

Covers: missing/corrupt file handling, category validation, replace
semantics (a change of mind updates, never duplicates), the scorer-ready
aggregate summary, normalized motivation lookup, the exact on-disk schema,
and the CLI. Everything runs against tmp_path -- the suite must never touch
the real tracker/outcome_notes.json.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

import outcome_notes


@pytest.fixture
def notes_path(tmp_path):
    return str(tmp_path / "outcome_notes.json")


class _FakeDatetime:
    """Drop-in for the module's `datetime` name: now() hands back queued
    instants, so 'the date moves when an entry is replaced' is deterministic
    (no sleeps, no wall-clock races)."""

    def __init__(self, *instants):
        self._instants = list(instants)

    def now(self, tz=None):
        return self._instants.pop(0)


# ─── load_notes ───────────────────────────────────────────────────────────────

class TestLoadNotes:
    def test_missing_file_returns_empty_lists(self, tmp_path):
        assert outcome_notes.load_notes(str(tmp_path / "nope.json")) == {
            "dismissals": [], "motivations": [],
        }

    def test_corrupt_file_returns_empty_lists(self, notes_path):
        with open(notes_path, "w", encoding="utf-8") as f:
            f.write("{ definitely not json")
        assert outcome_notes.load_notes(notes_path) == {
            "dismissals": [], "motivations": [],
        }

    def test_non_dict_json_returns_empty_lists(self, notes_path):
        with open(notes_path, "w", encoding="utf-8") as f:
            json.dump(["dismissed", "everything"], f)
        assert outcome_notes.load_notes(notes_path) == {
            "dismissals": [], "motivations": [],
        }


# ─── record_dismissal ─────────────────────────────────────────────────────────

class TestRecordDismissal:
    def test_invalid_category_raises_and_lists_valid_ones(self, notes_path):
        with pytest.raises(ValueError) as excinfo:
            outcome_notes.record_dismissal("Acme", "AI Engineer", "vibes", path=notes_path)
        message = str(excinfo.value)
        assert "vibes" in message
        for category in outcome_notes.DISMISSAL_CATEGORIES:
            assert category in message
        # Validation happens before any write: no file is created.
        assert not os.path.exists(notes_path)

    def test_records_full_entry(self, notes_path):
        entry = outcome_notes.record_dismissal(
            "Acme", "AI Engineer", "salary",
            note="band too low", url="https://x/1", path=notes_path,
        )
        assert entry["company"] == "Acme"
        assert entry["title"] == "AI Engineer"
        assert entry["category"] == "salary"
        assert entry["note"] == "band too low"
        assert entry["url"] == "https://x/1"
        datetime.fromisoformat(entry["date"])  # parses = real ISO timestamp

    def test_redismissal_replaces_and_moves_date(self, notes_path, monkeypatch):
        monkeypatch.setattr(outcome_notes, "datetime", _FakeDatetime(
            datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        ))
        first = outcome_notes.record_dismissal("Acme", "AI Engineer", "salary", path=notes_path)
        # Same job spelled differently (casing + legal suffix): an update,
        # not a new entry.
        second = outcome_notes.record_dismissal(
            "ACME Ltd", "ai engineer", "seniority", note="too junior", path=notes_path,
        )
        dismissals = outcome_notes.load_notes(notes_path)["dismissals"]
        assert len(dismissals) == 1
        assert dismissals[0]["category"] == "seniority"
        assert dismissals[0]["note"] == "too junior"
        assert second["date"] != first["date"]
        assert dismissals[0]["date"] == second["date"]


# ─── record_motivation ────────────────────────────────────────────────────────

class TestRecordMotivation:
    def test_one_current_motivation_per_job(self, notes_path, monkeypatch):
        monkeypatch.setattr(outcome_notes, "datetime", _FakeDatetime(
            datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        ))
        first = outcome_notes.record_motivation(
            "Acme", "AI Engineer", "sounded interesting", path=notes_path,
        )
        second = outcome_notes.record_motivation(
            "acme", "AI  Engineer", "real-time inference team", path=notes_path,
        )
        motivations = outcome_notes.load_notes(notes_path)["motivations"]
        assert len(motivations) == 1
        assert motivations[0]["note"] == "real-time inference team"
        assert second["date"] != first["date"]
        assert motivations[0]["date"] == second["date"]


# ─── dismissal_summary ────────────────────────────────────────────────────────

class TestDismissalSummary:
    def test_empty_without_dismissals(self, notes_path):
        assert outcome_notes.dismissal_summary(notes_path) == ""

    def test_counts_per_category_with_companies(self, notes_path):
        outcome_notes.record_dismissal("Acme", "AI Engineer", "salary", path=notes_path)
        outcome_notes.record_dismissal("Globex", "Backend Dev", "salary", path=notes_path)
        outcome_notes.record_dismissal("Initech", "QA Engineer", "tech_mismatch", path=notes_path)
        assert outcome_notes.dismissal_summary(notes_path) == (
            "Candidate dismissal signals (from his private notes): 3 dismissed -- "
            "salary: 2 (Acme, Globex); tech_mismatch: 1 (Initech). "
            "Treat these as strong negative signals for similar roles."
        )


# ─── motivation_for ───────────────────────────────────────────────────────────

class TestMotivationFor:
    def test_matches_despite_casing_and_accents(self, notes_path):
        outcome_notes.record_motivation(
            "Müller AG", "Ingénieur ML", "Zurich team, great stack", path=notes_path,
        )
        assert outcome_notes.motivation_for("muller", "ingenieur ml", path=notes_path) == \
            "Zurich team, great stack"
        assert outcome_notes.motivation_for("MÜLLER", "INGÉNIEUR ML", path=notes_path) == \
            "Zurich team, great stack"

    def test_unknown_job_returns_empty(self, notes_path):
        outcome_notes.record_motivation("Acme", "AI Engineer", "yes", path=notes_path)
        assert outcome_notes.motivation_for("Globex", "AI Engineer", path=notes_path) == ""
        assert outcome_notes.motivation_for("Acme", "Backend Dev", path=notes_path) == ""


# ─── on-disk schema ───────────────────────────────────────────────────────────

class TestOnDiskSchema:
    def test_no_fields_beyond_the_spec(self, notes_path):
        outcome_notes.record_dismissal("Acme", "AI Engineer", "salary",
                                       note="low", url="https://x/1", path=notes_path)
        outcome_notes.record_motivation("Globex", "Data Engineer", "great stack", path=notes_path)
        with open(notes_path, encoding="utf-8") as f:
            data = json.load(f)
        assert set(data) == {"dismissals", "motivations"}
        assert set(data["dismissals"][0]) == {
            "company", "title", "url", "category", "note", "date",
        }
        assert set(data["motivations"][0]) == {
            "company", "title", "url", "note", "date",
        }


# ─── CLI ──────────────────────────────────────────────────────────────────────

class TestCLI:
    def test_dismiss_then_summary_prints_aggregate(self, notes_path, monkeypatch, capsys):
        monkeypatch.setattr(outcome_notes, "NOTES_PATH", notes_path)

        monkeypatch.setattr(sys, "argv", [
            "outcome_notes.py", "dismiss", "Acme", "AI Engineer",
            "--category", "salary", "--note", "band too low",
        ])
        outcome_notes.main()

        monkeypatch.setattr(sys, "argv", ["outcome_notes.py", "summary"])
        outcome_notes.main()

        out = capsys.readouterr().out
        assert "OUTCOME_NOTES_B64" in out  # privacy reminder after dismiss
        assert "1 dismissed -- salary: 1 (Acme)" in out
        # The CLI wrote to the tmp_path file, not the real one.
        assert os.path.exists(notes_path)
