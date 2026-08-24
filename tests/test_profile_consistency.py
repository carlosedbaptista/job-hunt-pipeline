"""
test_profile_consistency.py -- Pins the guard against a stale profile.

config/candidate_profile.json is gitignored: it lives on one laptop and in
one GitHub secret, and neither is reviewable in a diff. On 2026-08-24 the job
title changed, the profile was updated, and the local
CANDIDATE_PROFILE_B64.txt was not -- so whether CI scored the candidate under
the right role came down to which of the two files someone happened to pipe
into `gh secret set`. Nothing complained either way.

That silence is expensive. The role is injected into every scoring prompt as
"Candidate, currently: X", and printed at the top of every generated CV that
goes to an employer.

The same class of drift has already bitten once, with languages: the prompt
said his German was B1 while the CV said A2, so a "German B1 required"
posting read as a soft mention when it was a real gap.
"""
import pytest

from check_profile import check


def profile(**overrides):
    base = {
        "name": "Test Candidate",
        "role": "AI Software Engineer Intern",
        "languages": "Portuguese (Native) | English (C1) | German (A2, studying towards B1)",
        "language_levels": {"german": "A2"},
        "skills": {"technical_default": ["Python"]},
        "education": [{"degree": "BSc"}],
        "experience": [{"title": "AI Software Engineer Intern", "company": "netzdenker"}],
    }
    base.update(overrides)
    return base


CV = """Carlos Baptista
AI Software Engineer Intern, netzdenker, Wallisellen, Switzerland
Languages: Portuguese (native), English (C1), German (A2, studying towards B1).
"""


class TestConsistentProfile:
    def test_a_matching_profile_passes(self):
        assert check(profile(), CV) == []

    def test_line_wrapping_in_the_cv_does_not_matter(self):
        """A CV wraps its lines; the title is still the same title."""
        wrapped = CV.replace("AI Software Engineer Intern,",
                             "AI Software Engineer\nIntern,")
        assert check(profile(), wrapped) == []

    def test_a_missing_cv_reference_is_not_a_failure(self):
        """CV_MODEL_B64 is optional; its absence skips one check, no more."""
        assert check(profile(), "") == []


class TestTheDriftThatHappened:
    def test_a_stale_role_is_caught_against_the_cv(self):
        problems = check(profile(role="AI & Automation Developer Intern"), CV)
        assert any("does not appear in the CV" in p for p in problems)

    def test_it_is_caught_even_without_the_cv(self):
        """The profile contradicts ITSELF: the header and its own first job
        would disagree. This fires with no CV available at all."""
        problems = check(profile(role="AI & Automation Developer Intern"), "")
        assert any("most recent experience" in p for p in problems)


class TestLanguageDrift:
    def test_a_level_that_disagrees_with_the_prose_is_caught(self):
        problems = check(
            profile(language_levels={"german": "B1"}), CV)
        assert any("language_levels says German is B1" in p for p in problems)

    def test_agreeing_levels_pass(self):
        assert check(profile(language_levels={"german": "A2"}), CV) == []

    def test_an_unset_level_is_not_a_contradiction(self):
        """Unset means unknown, and utils already treats that as the weakest
        level, which over-reports gaps rather than hiding them."""
        assert check(profile(language_levels={"german": ""}), CV) == []


class TestRequiredFields:
    @pytest.mark.parametrize("field", ["name", "role", "experience", "skills", "languages"])
    def test_a_missing_field_is_reported(self, field):
        problems = check(profile(**{field: ""}), CV)
        assert any("missing required field" in p for p in problems)

    def test_missing_fields_short_circuit_the_rest(self):
        """Nothing below can be trusted, so only one problem is reported."""
        assert len(check(profile(role=""), CV)) == 1


class TestQuietDayIsVisible:
    """A run with nothing to score must leave the pipeline saying so.

    On 2026-08-24 a run found zero new jobs and still e-mailed the PREVIOUS
    run's top five, stamped with the new timestamp. The quiet-day heartbeat,
    added that same day for exactly this case, never fired: it triggers on
    total_evaluated == 0, and the digest read a stale
    job_evaluations_latest.json that still held 10 records.

    "Latest" has to mean this run's. Otherwise a quiet day is
    indistinguishable from a busy one -- and the document generator, which
    reads the same file, would re-generate and re-announce materials for
    yesterday's APPLY jobs.
    """

    @pytest.fixture(autouse=True)
    def _profile_guard_off(self, monkeypatch):
        """The profile guard must not depend on whether the (gitignored)
        profile happens to exist on this machine -- in CI no secrets are
        restored, so the import-time fallback flag is True there and main()
        would refuse to run (same trick as test_decision_agent.py)."""
        import job_evaluator as je
        monkeypatch.setattr(je, "PROFILE_IS_FALLBACK", False)

    def _run_evaluator_with_no_jobs(self, tmp_path, monkeypatch):
        import json
        import job_evaluator as je

        monkeypatch.chdir(tmp_path)
        (tmp_path / "digests").mkdir()
        (tmp_path / "digests" / "new_jobs_latest.json").write_text("[]", encoding="utf-8")
        # Stale leftovers from an earlier run, as they really were.
        (tmp_path / "digests" / "job_evaluations_latest.json").write_text(
            json.dumps([{"score": 55, "decision": "SKIP", "job": {"title": "Old"}}]),
            encoding="utf-8")
        je.main()
        return json.loads(
            (tmp_path / "digests" / "job_evaluations_latest.json").read_text(encoding="utf-8"))

    def test_the_previous_runs_evaluations_are_cleared(self, tmp_path, monkeypatch):
        assert self._run_evaluator_with_no_jobs(tmp_path, monkeypatch) == []

    def test_a_missing_input_file_clears_it_too(self, tmp_path, monkeypatch):
        """Same reasoning: no input is still a quiet day, not a busy one."""
        import json
        import job_evaluator as je

        monkeypatch.chdir(tmp_path)
        (tmp_path / "digests").mkdir()
        (tmp_path / "digests" / "job_evaluations_latest.json").write_text(
            json.dumps([{"score": 90, "decision": "APPLY", "job": {"title": "Old"}}]),
            encoding="utf-8")
        je.main()
        assert json.loads(
            (tmp_path / "digests" / "job_evaluations_latest.json").read_text(encoding="utf-8")) == []
