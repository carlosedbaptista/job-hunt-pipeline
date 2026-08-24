"""
test_feedback_loop.py -- the score -> outcome loop (2026-08-24).

Covers: APPLY-tier jobs recorded as 'recommended' (never 'sent'), promotion
to 'sent' only by the user's manual action, follow-ups never firing on
recommendations, and outcome evidence flowing back into the scorer's prompt.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

import tracker_updater
import agents.tracker_updater as agents_tracker_updater
import followup_sender
import job_evaluator


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh tracker DB for every module object that holds the path.
    followup_sender does `from agents.tracker_updater import ...`, and
    agents.tracker_updater is a DISTINCT module object from the top-level
    tracker_updater (dual sys.path entries), so both must be patched --
    missing one breaks any run whose cwd is not the repo root."""
    path = str(tmp_path / "jobs.db")
    monkeypatch.setattr(tracker_updater, "DB_PATH", path)
    monkeypatch.setattr(agents_tracker_updater, "DB_PATH", path)
    monkeypatch.setattr(followup_sender, "DB_PATH", path)
    return path


# ─── record_recommendation ───────────────────────────────────────────────────

class TestRecordRecommendation:
    def test_records_as_recommended_never_sent(self, db):
        assert tracker_updater.record_recommendation("ACME", "AI Engineer", "https://x/1", 88) is True
        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1
        assert apps[0]["status"] == "recommended"
        assert apps[0]["score"] == 88
        assert apps[0]["date_applied"] is None  # NULL on purpose: no follow-up without application

    def test_re_recommendation_updates_score_no_duplicate(self, db):
        tracker_updater.record_recommendation("ACME", "AI Engineer", "https://x/1", 85)
        tracker_updater.record_recommendation("ACME", "AI Engineer", "https://x/1", 91)
        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1
        assert apps[0]["score"] == 91

    def test_never_demotes_a_real_application(self, db):
        tracker_updater.record_application("ACME", "AI Engineer", "https://x/1")
        assert tracker_updater.record_recommendation("ACME", "AI Engineer", "https://x/1", 60) is False
        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1
        assert apps[0]["status"] == "sent"
        assert apps[0]["date_applied"] is not None


# ─── promotion: recommended -> sent closes the loop ─────────────────────────

class TestPromotion:
    def test_record_application_promotes_recommended(self, db):
        tracker_updater.record_recommendation("ACME", "AI Engineer", "https://x/1", 88)
        assert tracker_updater.record_application("ACME", "AI Engineer", "https://x/1") is True
        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1
        assert apps[0]["status"] == "sent"
        assert apps[0]["score"] == 88  # the score that drove the recommendation survives
        assert apps[0]["date_applied"] is not None

    def test_record_application_fresh_insert_still_works(self, db):
        assert tracker_updater.record_application("Beta Corp", "Data Engineer", "https://x/2") is True
        assert tracker_updater.record_application("Beta Corp", "Data Engineer", "https://x/2") is False
        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1
        assert apps[0]["status"] == "sent"


# ─── follow-ups never fire on recommendations ────────────────────────────────

class TestFollowupExcludesRecommended:
    def test_recommended_never_gets_followup(self, db):
        tracker_updater.record_recommendation("ACME", "AI Engineer", "https://x/1", 88)
        # Age it artificially beyond the threshold -- even an old
        # recommendation must not trigger a follow-up draft.
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute("UPDATE applications SET date_recommended = ?, last_update = ?", (old, old))
        conn.commit(); conn.close()

        assert followup_sender.get_stale_applications(days_threshold=7) == []

    def test_sent_without_response_does_get_followup(self, db):
        tracker_updater.record_application("ACME", "AI Engineer", "https://x/1")
        old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute("UPDATE applications SET date_applied = ?", (old,))
        conn.commit(); conn.close()

        stale = followup_sender.get_stale_applications(days_threshold=7)
        assert len(stale) == 1
        assert stale[0]["company"] == "ACME"


# ─── outcome summary feeds the scorer ───────────────────────────────────────

class TestOutcomeCalibration:
    def test_summary_counts_only_sent(self, db):
        tracker_updater.record_recommendation("Rec Corp", "ML Intern", "https://x/1", 95)
        tracker_updater.record_application("Real Corp", "AI Engineer", "https://x/2")
        tracker_updater.record_recommendation("Promo Corp", "Data Engineer", "https://x/3", 84)
        tracker_updater.record_application("Promo Corp", "Data Engineer", "https://x/3")
        tracker_updater.record_response("Promo Corp", "Data Engineer", "interview_invite")

        s = tracker_updater.get_outcome_summary()
        assert s["total_applied"] == 2          # recommended-only row is excluded
        assert s["responded"] == 1
        assert s["apply_tier"]["applied"] == 1  # Promo Corp (score 84)
        assert s["apply_tier"]["interviews"] == 1

    def test_calibration_text_reaches_the_prompt(self, db, monkeypatch):
        tracker_updater.record_application("Real Corp", "AI Engineer", "https://x/2")
        monkeypatch.setattr(job_evaluator, "SYSTEM_WITH_OUTCOMES",
                            job_evaluator.PROFILE + "\n" + job_evaluator.SYSTEM_PROMPT
                            + "\n" + job_evaluator.load_outcome_calibration())

        captured = {}
        def spy(prompt, system=None, max_tokens=4096):
            captured["system"] = system
            return {"score": 85, "concerns": [], "hard_blockers": [], "language_requirement": "none"}

        monkeypatch.setattr(job_evaluator, "call_kimi_json", spy)
        job_evaluator.evaluate_job({"company": "ACME", "title": "AI Engineer",
                                    "location": "Zurich",
                                    "description": "Build agentic systems. " * 20,
                                    "url": "https://x/9", "portal": "test"})
        assert "Outcome calibration" in captured["system"]
        assert "Real Corp" in captured["system"]

    def test_no_outcomes_means_no_calibration_line(self, db):
        assert job_evaluator.load_outcome_calibration() == ""


# ─── end-to-end: a daily APPLY is recorded as recommended ───────────────────

class TestMainRecordsRecommendations:
    def test_apply_jobs_become_recommended(self, db, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        os.makedirs("digests", exist_ok=True)
        jobs = [{"company": "ACME", "title": "AI Platform Engineer", "location": "Zurich",
                 "description": "Own LLM workflows end to end. " * 20,
                 "url": "https://x/1", "portal": "test"}]
        with open("digests/new_jobs_latest.json", "w", encoding="utf-8") as f:
            json.dump(jobs, f)

        monkeypatch.setattr(job_evaluator, "call_kimi_json", lambda *a, **k: {
            "score": 90, "concerns": [], "hard_blockers": [], "language_requirement": "none"})
        monkeypatch.setattr(job_evaluator.time, "sleep", lambda s: None)
        # The profile guard must not depend on whether the (gitignored)
        # profile happens to exist on this machine -- in CI no secrets are
        # restored, so the import-time fallback flag is True there (same
        # trick as test_decision_agent.py).
        monkeypatch.setattr(job_evaluator, "PROFILE_IS_FALLBACK", False)

        job_evaluator.main()

        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1
        assert apps[0]["status"] == "recommended"
        assert apps[0]["score"] == 90
        assert apps[0]["date_applied"] is None
