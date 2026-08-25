"""
test_outcome_notes_integration.py -- private outcome signals reaching the
agents (2026-08-24).

Covers: the dismissal aggregate appended to the scorer's calibration text,
the byte-identical degradation when the notes file is absent, the failure
contract (a raising outcome_notes changes nothing), and the motivation line
in the follow-up prompt. The notes file itself is gitignored; every test
here works on tmp_path copies and never touches the real one.
"""
import sys

import pytest

import tracker_updater
import agents.tracker_updater as agents_tracker_updater
import outcome_notes
import job_evaluator
import followup_writer


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh tracker DB (same dual-module patch as test_feedback_loop:
    agents.tracker_updater is a distinct module object from the top-level
    tracker_updater, so both must be pointed at tmp_path)."""
    path = str(tmp_path / "jobs.db")
    monkeypatch.setattr(tracker_updater, "DB_PATH", path)
    monkeypatch.setattr(agents_tracker_updater, "DB_PATH", path)
    return path


@pytest.fixture
def notes_file(tmp_path, monkeypatch):
    """A real notes file under a tmp cwd, recorded through outcome_notes'
    own API (so the schema is always the real one). Two redirect mechanisms
    because dismissal_summary() binds its default path at def time: the
    module attribute covers a dynamic read, the chdir makes the def-time
    relative default resolve under tmp_path."""
    monkeypatch.chdir(tmp_path)
    path = str(tmp_path / "tracker" / "outcome_notes.json")
    monkeypatch.setattr(outcome_notes, "NOTES_PATH", path)
    outcome_notes.record_dismissal("Acme", "AI Engineer", "salary",
                                   note="band too low", path=path)
    outcome_notes.record_dismissal("Globex", "Backend Dev", "tech_mismatch", path=path)
    return path


def _baseline_calibration(monkeypatch) -> str:
    """Today's text, obtained by making `import outcome_notes` fail -- the
    exact pre-change code path."""
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "outcome_notes", None)
        return job_evaluator.load_outcome_calibration()


# ─── dismissal aggregate reaches the scorer ──────────────────────────────────

class TestCalibrationAppend:
    def test_dismissal_aggregate_is_appended(self, db, notes_file, monkeypatch):
        tracker_updater.record_application("Real Corp", "AI Engineer", "https://x/2")
        baseline = _baseline_calibration(monkeypatch)
        assert baseline  # the comparison below must be meaningful

        aggregate = outcome_notes.dismissal_summary()
        assert aggregate  # the notes file produced real signals

        text = job_evaluator.load_outcome_calibration()
        assert aggregate in text
        # New paragraph after the existing outcome summary, nothing else.
        assert text == baseline + "\n" + aggregate + "\n"

    def test_missing_notes_file_is_byte_identical(self, db, tmp_path, monkeypatch):
        tracker_updater.record_application("Real Corp", "AI Engineer", "https://x/2")
        baseline = _baseline_calibration(monkeypatch)
        assert baseline

        # No notes anywhere: an empty cwd, and the module attribute pointing
        # at a file that does not exist.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(outcome_notes, "NOTES_PATH",
                            str(tmp_path / "tracker" / "outcome_notes.json"))
        assert job_evaluator.load_outcome_calibration() == baseline

    def test_raising_notes_module_changes_nothing(self, db, notes_file, monkeypatch):
        tracker_updater.record_application("Real Corp", "AI Engineer", "https://x/2")
        baseline = _baseline_calibration(monkeypatch)
        assert baseline

        def boom(path=outcome_notes.NOTES_PATH):
            raise RuntimeError("private notes corrupted")

        monkeypatch.setattr(outcome_notes, "dismissal_summary", boom)
        assert job_evaluator.load_outcome_calibration() == baseline


# ─── motivation line reaches the follow-up prompt ────────────────────────────

FOLLOWUP_ARGS = ("DreamCo", "AI Platform Engineer", 9, "2026-08-15")


class TestFollowupMotivationLine:
    def test_motivation_adds_one_line(self, monkeypatch):
        monkeypatch.setattr(
            outcome_notes, "motivation_for",
            lambda company, title, path=None: "real-time inference team, I want in")
        prompt = followup_writer.build_followup_prompt(*FOLLOWUP_ARGS)
        assert "real-time inference team, I want in" in prompt
        assert "CANDIDATE'S OWN REASON FOR APPLYING" in prompt

    def test_no_motivation_prompt_unchanged(self, monkeypatch):
        with monkeypatch.context() as m:
            m.setitem(sys.modules, "outcome_notes", None)
            baseline = followup_writer.build_followup_prompt(*FOLLOWUP_ARGS)

        monkeypatch.setattr(outcome_notes, "motivation_for",
                            lambda company, title, path=None: "")
        prompt = followup_writer.build_followup_prompt(*FOLLOWUP_ARGS)
        assert prompt == baseline
        assert "CANDIDATE'S OWN REASON" not in prompt
