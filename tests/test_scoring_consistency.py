"""
test_scoring_consistency.py -- Consistency suite for the scoring "brain".

Covers the deterministic parts of the pipeline (thresholds, decision
derivation, hard-blocker lock, language-requirement detector, digest
rendering, dedup hashing, cost-cap queueing) with a mocked LLM.

Born from the 2026-08-17 audit: every scenario here either pins intended
behaviour or reproduces a bug that was found (and fixed) that day -- the
commit history and docstrings tell which is which.

Nothing here calls the Kimi API. The real-model behaviour probe lives in
scripts/smoke_kimi_brain.py (gitignored, costs API calls).
"""
import os

import pytest

import job_evaluator
import digest_generator
import deduplicator
import unified_ingestor
import add_job
from utils import (THRESHOLD_APPLY, THRESHOLD_REVIEW, decision_from_score,
                   effective_decision, hard_blockers_of, has_hard_blocker,
                   is_spurious_blocker)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_job(**over):
    job = {
        "company": "ACME AG",
        "title": "AI Platform Engineer Intern",
        "location": "Zurich",
        "description": "Build LLM workflows with us. Python, SQL, ownership from day one. " * 5,
        "url": "https://example.com/job/1",
        "portal": "adzuna",
    }
    job.update(over)
    return job


def fake_kimi(payload):
    """Returns a callable that mimics call_kimi_json with a fixed payload."""
    def _fake(prompt, system=None, max_tokens=4096):
        return payload
    return _fake


def eval_with(payload, job=None):
    mp = pytest.MonkeyPatch()
    mp.setattr(job_evaluator, "call_kimi_json", fake_kimi(payload))
    return job_evaluator.evaluate_job(job or make_job())


# ─── 1. decision_from_score: thresholds stay the base truth ──────────────────

class TestDecisionFromScore:
    def test_boundaries(self):
        assert decision_from_score(THRESHOLD_APPLY) == "APPLY"
        assert decision_from_score(THRESHOLD_APPLY - 1) == "REVIEW"
        assert decision_from_score(THRESHOLD_REVIEW) == "REVIEW"
        assert decision_from_score(THRESHOLD_REVIEW - 1) == "SKIP"

    def test_none_is_error(self):
        assert decision_from_score(None) == "ERROR"

    def test_float_boundaries(self):
        assert decision_from_score(79.9) == "REVIEW"
        assert decision_from_score(80.0) == "APPLY"


# ─── 2. effective_decision: thresholds + blocker lock + low-confidence cap ───

class TestEffectiveDecision:
    def test_plain_score_mapping(self):
        assert effective_decision({"score": 85, "hard_blockers": []}) == "APPLY"
        assert effective_decision({"score": 75, "hard_blockers": []}) == "REVIEW"
        assert effective_decision({"score": 40, "hard_blockers": []}) == "SKIP"

    def test_blocker_lock_forces_skip_regardless_of_score(self):
        """Business rule: an unmet hard eligibility requirement is SKIP, no
        exception -- even at score 98, and it must not trigger CV/CL."""
        ev = {"score": 98, "hard_blockers": ["Role requires fluent German (C1)"]}
        assert effective_decision(ev) == "SKIP"

    def test_blocker_fallback_for_legacy_records(self):
        """Records written before the structured field existed carry blockers
        as 'Blocker: '-prefixed red_flags -- the lock must still hold."""
        ev = {"score": 96, "red_flags": ["Blocker: Requires fluent German (C1)"]}
        assert has_hard_blocker(ev) is True
        assert effective_decision(ev) == "SKIP"

    def test_spurious_blocker_does_not_trigger_lock(self):
        """The model uses the prefix to say there is NO blocker -- taking it
        literally would SKIP the best jobs (smoke scenario 1: 'Blocker: None
        -- English working language explicitly stated')."""
        ev = {"score": 98, "hard_blockers": ["None -- English working language explicitly stated, no German requirement"]}
        assert effective_decision(ev) == "APPLY"

    def test_insufficient_info_caps_at_review(self):
        ev = {"score": 95, "hard_blockers": [], "insufficient_info": True}
        assert effective_decision(ev) == "REVIEW"

    def test_none_score_is_error(self):
        assert effective_decision({"score": None}) == "ERROR"
        assert effective_decision({"score": None, "decision": "ERROR"}) == "ERROR"


class TestSpuriousBlockerFilter:
    @pytest.mark.parametrize("text", [
        "None -- English working language explicitly stated",
        "none",
        "No German requirement",
        "N/A",
        "Keine",
        "German not required",
        "No language requirement",
    ])
    def test_spurious(self, text):
        assert is_spurious_blocker(text) is True

    @pytest.mark.parametrize("text", [
        "Role requires fluent German (C1)",
        "verhandlungssicheres Deutsch zwingend erforderlich",
        "Native French speaker required",
        "Must hold Swiss work permit -- sponsorship not offered",
    ])
    def test_real(self, text):
        assert is_spurious_blocker(text) is False


# ─── 3. Deterministic language-requirement detector ──────────────────────────

class TestLanguageDetector:
    @pytest.mark.parametrize("text", [
        "Requirements: fluent written and spoken German (at least C1) is required.",
        "Anforderungen: verhandlungssicheres Deutsch (mindestens C1) zwingend.",
        "You must be a native German speaker.",
        "Deutsch: Muttersprache oder C1-Niveau",
        "French C2 level mandatory for this position",
    ])
    def test_matches_hard_requirements(self, text):
        assert job_evaluator.detect_hard_language_requirement(text) is not None

    @pytest.mark.parametrize("text", [
        "German is a plus; English is our working language.",
        "B1/B2 German acceptable.",
        "Fluent English required.",
        "Our working language is English.",
        "",
    ])
    def test_ignores_soft_mentions_and_english(self, text):
        assert job_evaluator.detect_hard_language_requirement(text) is None

    def test_evidence_snippet_injected_into_prompt(self):
        """The requirement may sit past the excerpt window; the prompt must
        carry the pipeline note with the evidence either way."""
        captured = {}

        def spy(prompt, system=None, max_tokens=4096):
            captured["prompt"] = prompt
            return {"score": 40, "concerns": [], "hard_blockers": []}

        long_desc = ("Great role. " * 200) + " verhandlungssicheres Deutsch (C1) zwingend erforderlich."
        mp = pytest.MonkeyPatch()
        mp.setattr(job_evaluator, "call_kimi_json", spy)
        job_evaluator.evaluate_job(make_job(description=long_desc))
        assert "Pipeline note" in captured["prompt"]
        assert "verhandlungssicher" in captured["prompt"]


# ─── 4. evaluate_job robustness (mocked LLM) ─────────────────────────────────

class TestEvaluateJobRobustness:
    def test_model_decision_drift_local_rules_win(self):
        ev = eval_with({"score": 85, "decision": "SKIP", "concerns": [], "hard_blockers": []})
        assert ev["score"] == 85
        assert ev["decision"] == "APPLY"
        assert ev["materials_needed"] == ["cv"]

    def test_concerns_surface_on_apply_tier(self):
        ev = eval_with({"score": 88, "concerns": ["Docker depth unclear"], "hard_blockers": []})
        assert "Docker depth unclear" in ev["red_flags"]

    def test_skip_tier_gets_visible_reason(self):
        """Fixed in the audit: the old dict.get default only fired when the
        key was omitted -- an explicit empty list (what the model returns)
        suppressed it, so SKIPs showed no reason."""
        ev = eval_with({"score": 60, "concerns": [], "hard_blockers": []})
        assert ev["red_flags"] == ["Score below threshold"]

    def test_detected_fields_backfilled(self):
        ev = eval_with({"score": 85, "concerns": [], "hard_blockers": [],
                        "detected_company": "Real Corp", "detected_location": "Zug"},
                       job=make_job(company="Unknown", location="Unknown"))
        assert ev["job"]["company"] == "Real Corp"
        assert ev["job"]["location"] == "Zug"

    def test_api_error_never_fabricates_score(self):
        def boom(prompt, system=None, max_tokens=4096):
            raise RuntimeError("connection reset")
        mp = pytest.MonkeyPatch()
        mp.setattr(job_evaluator, "call_kimi_json", boom)
        ev = job_evaluator.evaluate_job(make_job())
        assert ev["score"] is None
        assert ev["decision"] == "ERROR"
        assert any("API error" in str(f) for f in ev["red_flags"])

    def test_missing_score_is_error_not_fake_50(self):
        """Fixed in the audit: a missing score used to silently become 50 --
        a fabricated score, against the pipeline's own no-fake-scores rule."""
        ev = eval_with({"technical_fit": "ok", "concerns": []})
        assert ev["score"] is None
        assert ev["decision"] == "ERROR"

    def test_string_score_is_coerced(self):
        """Fixed in the audit: 'score': '85' used to crash the comparison
        (TypeError) and turn a good evaluation into ERROR."""
        ev = eval_with({"score": "85", "concerns": [], "hard_blockers": []})
        assert ev["score"] == 85
        assert ev["decision"] == "APPLY"

    def test_score_out_of_range_is_clamped(self):
        """Fixed in the audit: 120 used to pass straight through as APPLY."""
        ev = eval_with({"score": 120, "concerns": [], "hard_blockers": []})
        assert ev["score"] == 100
        ev2 = eval_with({"score": -5, "concerns": [], "hard_blockers": []})
        assert ev2["score"] == 0

    def test_null_concerns_become_empty_list(self):
        """Fixed in the audit: 'concerns': null propagated None into
        red_flags and crashed the whole digest run (TypeError)."""
        ev = eval_with({"score": 85, "concerns": None, "hard_blockers": []})
        assert ev["red_flags"] == []
        assert ev["concerns"] == []

    def test_blocker_lock_skips_and_blocks_materials(self):
        """The core business rule, now enforced in code (it used to live
        only in the prompt): score 90 with a hard blocker must not APPLY
        and must not generate CV/CL."""
        ev = eval_with({"score": 90, "hard_blockers": ["Role requires fluent German (C1)"],
                        "concerns": []})
        assert ev["decision"] == "SKIP"
        assert ev["materials_needed"] == []
        assert ev["red_flags"] == ["Blocker: Role requires fluent German (C1)"]

    def test_legacy_prefixed_concern_still_locks(self):
        ev = eval_with({"score": 90, "concerns": ["Blocker: Requires native French"]})
        assert ev["decision"] == "SKIP"
        assert ev["hard_blockers"] == ["Requires native French"]

    def test_spurious_blocker_filtered_out_of_display(self):
        ev = eval_with({"score": 98, "concerns": [],
                        "hard_blockers": ["None -- English working language explicitly stated"]})
        assert ev["decision"] == "APPLY"
        assert ev["hard_blockers"] == []
        assert not any(str(f).startswith("Blocker:") for f in ev["red_flags"])

    def test_insufficient_info_caps_apply_to_review(self):
        """A bare title scored 78 with 'Technical fit: Strong' in the audit
        -- the model fabricates confidence without text. Cap at REVIEW and
        never auto-generate materials."""
        ev = eval_with({"score": 95, "concerns": [], "hard_blockers": []},
                       job=make_job(description=""))
        assert ev["insufficient_info"] is True
        assert ev["decision"] == "REVIEW"
        assert ev["materials_needed"] == []
        assert any("Low confidence" in str(f) for f in ev["red_flags"])

    def test_todays_date_in_prompt(self):
        captured = {}

        def spy(prompt, system=None, max_tokens=4096):
            captured["prompt"] = prompt
            return {"score": 50, "concerns": [], "hard_blockers": []}

        mp = pytest.MonkeyPatch()
        mp.setattr(job_evaluator, "call_kimi_json", spy)
        job_evaluator.evaluate_job(make_job())
        assert "Today's date:" in captured["prompt"]


# ─── 5. Digest rendering ─────────────────────────────────────────────────────

def digest_eval(score, **over):
    ev = {
        "score": score,
        "hard_blockers": [],
        "insufficient_info": False,
        "key_match_points": [],
        "red_flags": [],
        "job": make_job(),
    }
    ev.update(over)
    ev["decision"] = effective_decision(ev)
    ev["recommendation"] = ev["decision"]
    return ev


class TestDigestRendering:
    def _format(self, evals):
        scored = [e for e in evals if e.get("score") is not None and e.get("decision") != "ERROR"]
        digest = {"generated_at": "2026-08-17T12:00:00", "total_evaluated": len(scored),
                  "evaluation_errors": len(evals) - len(scored)}
        return digest_generator.format_digest_text(digest, scored)

    def test_decision_rederived_not_stored_field(self):
        ev = digest_eval(85, recommendation="SKIP", decision="SKIP")
        assert "Status: APPLY" in self._format([ev])

    def test_blocker_lock_shows_skip_despite_high_score(self):
        ev = digest_eval(96, hard_blockers=["Role requires fluent German (C1)"],
                         red_flags=["Blocker: Role requires fluent German (C1)"])
        text = self._format([ev])
        assert "Status: SKIP" in text
        assert "⛔ Blocker: Role requires fluent German (C1)" in text

    def test_blockers_rendered_separate_from_notes(self):
        ev = digest_eval(72, red_flags=["Blocker: Requires fluent German (C1)",
                                        "Docker depth unclear"])
        text = self._format([ev])
        blocker_line = [ln for ln in text.splitlines() if "⛔" in ln][0]
        assert "Docker" not in blocker_line
        assert "Note: Docker depth unclear" in text

    def test_error_entries_excluded_from_ranking(self):
        ok = digest_eval(85)
        err = digest_eval(None, decision="ERROR", recommendation="ERROR")
        assert "85/100" in self._format([ok, err])

    def test_digest_tolerates_null_red_flags(self):
        """Fixed in the audit: one evaluation with red_flags=None crashed
        format_digest_text (TypeError) and killed the whole digest run."""
        ev = digest_eval(85)
        ev["red_flags"] = None
        assert "85/100" in self._format([ev])

    def test_next_steps_point_to_real_workflows(self):
        """Fixed in the audit: the digest used to send the user to
        src/approval_handler.py -- dead legacy code."""
        text = self._format([digest_eval(85)])
        assert "approval_handler" not in text
        assert "Track Application" in text


# ─── 6. Deduplication & hashing ──────────────────────────────────────────────

class TestDedupHashing:
    def test_accent_transliteration(self):
        assert deduplicator.make_hash("ACME", "Engineer", "Zürich") == \
               deduplicator.make_hash("ACME", "Engineer", "Zurich")

    def test_legal_suffix_stripped(self):
        assert deduplicator.make_hash("BLP Digital AG", "Engineer", "Zurich") == \
               deduplicator.make_hash("BLP Digital", "Engineer", "Zurich")

    def test_remote_prefix_defeats_location_matching(self):
        """Documented gap: normalize_location keeps only the first token, so
        'Remote - Zurich' hashes as 'remote' and never matches the same job
        listed as 'Zurich'. Cross-source reconciliation remains imperfect."""
        assert deduplicator.make_hash("ACME", "Eng", "Remote - Zurich") != \
               deduplicator.make_hash("ACME", "Eng", "Zurich")

    def test_unknown_location_never_matches_real_location(self):
        """Documented gap: a manually-added job (location 'Unknown') and the
        same posting later ingested from Adzuna ('Zurich') hash differently
        -> double evaluation. The model's detected_location backfill reduces
        but does not eliminate this."""
        assert deduplicator.make_hash("ACME", "Eng", "Unknown") != \
               deduplicator.make_hash("ACME", "Eng", "Zurich")

    def test_cross_run_filter(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        jobs = [{"company": "ACME", "title": "Eng", "location": "Zurich",
                 "url": "https://x/1", "portal": "adzuna"}]
        assert len(deduplicator.filter_new_jobs(jobs, db_path=db)) == 1
        assert len(deduplicator.filter_new_jobs(jobs, db_path=db)) == 0

    def test_mark_seen_false_filters_without_marking(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        jobs = [{"company": "ACME", "title": "Eng", "location": "Zurich",
                 "url": "https://x/1", "portal": "adzuna"}]
        assert len(deduplicator.filter_new_jobs(jobs, db_path=db, mark_seen=False)) == 1
        # Not marked: still new on the next pass.
        assert len(deduplicator.filter_new_jobs(jobs, db_path=db, mark_seen=False)) == 1
        assert len(deduplicator.filter_new_jobs(jobs, db_path=db, mark_seen=True)) == 1
        assert len(deduplicator.filter_new_jobs(jobs, db_path=db)) == 0


class TestCostCapQueueing:
    def test_cap_does_not_swallow_unevaluated_jobs(self, tmp_path, monkeypatch):
        """Fixed in the audit (critical): the cap used to run AFTER dedup had
        marked every job as seen -- jobs 31+ were never evaluated AND never
        resurfaced. Now they stay unseen and come back next run."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "30")
        db = str(tmp_path / "jobs.db")
        jobs = [{"company": f"Comp{i}", "title": f"Title{i}", "location": "Zurich",
                 "url": f"https://x/{i}", "portal": "adzuna"} for i in range(35)]

        unified_ingestor.save_evaluator_input(jobs, db_path=db)
        import json, os
        with open(os.path.join("digests", "new_jobs_latest.json"), encoding="utf-8") as f:
            first_run = json.load(f)
        assert len(first_run) == 30

        unified_ingestor.save_evaluator_input(jobs, db_path=db)
        with open(os.path.join("digests", "new_jobs_latest.json"), encoding="utf-8") as f:
            second_run = json.load(f)
        assert {j["url"] for j in second_run} == {f"https://x/{i}" for i in range(30, 35)}


# ─── 7. Manual re-evaluation semantics ───────────────────────────────────────

class TestManualSameJob:
    def test_same_job_matches_on_company_and_title(self):
        a = {"job": {"company": "Novartis AG", "title": "Data Engineer", "location": "Zurich"}}
        b = {"job": {"company": "Novartis", "title": "Data Engineer", "location": "Basel"}}
        assert add_job._same_job(a, b) is True

    def test_same_job_ignores_location_but_hash_does_not(self):
        """Documented divergence: manual replacement matches company+title,
        while the dedup hash also includes location. Same company/title in
        Zurich vs Zug collapses into one manual record but stays two rows in
        the tracker."""
        a = {"job": {"company": "ACME", "title": "Eng", "location": "Zurich"}}
        b = {"job": {"company": "ACME", "title": "Eng", "location": "Zug"}}
        assert add_job._same_job(a, b) is True
        assert deduplicator.make_hash("ACME", "Eng", "Zurich") != \
               deduplicator.make_hash("ACME", "Eng", "Zug")


# ─── 8. Ingestion normalisation & excerpt window ─────────────────────────────

class TestDashboardSmoke:
    def test_collect_and_generate_dashboard(self, tmp_path, monkeypatch):
        """Regression for the 2026-08-17 CI failure: collect_jobs referenced
        has_hard_blocker without importing it (NameError broke the dashboard
        step). The suite had zero dashboard coverage -- this exercises
        collect_jobs and generate_dashboard end to end on seeded inputs."""
        import json
        import src.dashboard as dashboard

        monkeypatch.chdir(tmp_path)
        os.makedirs("digests", exist_ok=True)
        os.makedirs("data/history", exist_ok=True)
        blocked = digest_eval(96, hard_blockers=["Role requires fluent German (C1)"],
                              red_flags=["Blocker: Role requires fluent German (C1)"])
        clean = digest_eval(85, job=make_job(company="Other Corp", title="Data Engineer"))
        with open("digests/manual_evaluations.json", "w", encoding="utf-8") as f:
            json.dump([blocked, clean], f)

        jobs = dashboard.collect_jobs(days=30)
        assert len(jobs) == 2
        by_score = {j["score"]: j for j in jobs}
        assert by_score[96]["_has_blocker"] is True
        assert by_score[85]["_has_blocker"] is False

        path, count = dashboard.generate_dashboard()
        assert count == 2
        with open(path, encoding="utf-8") as f:
            html = f.read()
        assert "const JOBS = " in html  # page renders with the seeded jobs


# ─── 9. Ingestion normalisation & excerpt window ─────────────────────────────

class TestIngestionNormalisation:
    def test_defaults(self):
        j = unified_ingestor.normalize_job_fields({})
        assert j["company"] == "Unknown"
        assert j["title"] == "Unknown"
        assert j["location"] == "Unknown"
        assert j["description"] == ""
        assert j["portal"] == "unknown"
        assert j["language"] == "en"
        assert j["posted_at"]

    def test_excerpt_window_matches_adzuna_storage(self):
        """The model sees description[:4000] -- the same 4000 Adzuna keeps --
        so a requirement block at the end of a long posting is visible.
        (Was 1500 before the audit: a C1-German clause past char 1500 scored
        96/APPLY instead of auto-SKIP.)"""
        captured = {}

        def spy(prompt, system=None, max_tokens=4096):
            captured["prompt"] = prompt
            return {"score": 50, "concerns": [], "hard_blockers": []}

        mp = pytest.MonkeyPatch()
        mp.setattr(job_evaluator, "call_kimi_json", spy)
        job_evaluator.evaluate_job(make_job(description="x" * 5000))
        assert "x" * 4000 in captured["prompt"]
        assert "x" * 4001 not in captured["prompt"]
