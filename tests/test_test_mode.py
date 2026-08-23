"""
test_test_mode.py -- Pins the REEVALUATE_ALL escape hatch.

The pipeline is hard to exercise on demand: Adzuna's free tier is 100 calls a
day and a full run spends 18, so on a day of active testing there is simply no
budget left to run it again. Worse, cross-run dedup means a second run finds
nothing new to score even if the quota allowed it.

So the manual workflow gained two inputs: `skip_ingestion` (reuse the batch
already fetched, touch no external API) and `reevaluate` (score jobs already
marked as seen). Together they make the whole pipeline runnable any number of
times for the cost of the LLM calls alone.

The risk this pins down is that the escape hatch leaks into the scheduled
runs, where it would re-score the same jobs twice a day forever, quietly
multiplying the Kimi bill and refilling the digest with jobs already judged.
It must be opt-in, explicit, and off for anything but a truthy value.
"""
import json

import pytest

import unified_ingestor as ui


@pytest.fixture
def two_jobs():
    return [
        {"title": "AI Engineer", "company": "Acme", "location": "Zurich",
         "description": "x" * 300},
        {"title": "Data Engineer", "company": "Beta", "location": "Zug",
         "description": "y" * 300},
    ]


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "jobs.db")


def _written(tmp_path, monkeypatch, jobs, db_path):
    """Runs save_evaluator_input with its output redirected into tmp_path."""
    monkeypatch.chdir(tmp_path)
    ui.save_evaluator_input(jobs, db_path=db_path)
    with open("digests/new_jobs_latest.json", encoding="utf-8") as f:
        return json.load(f)


class TestDefaultBehaviour:
    def test_seen_jobs_are_filtered_on_a_second_run(self, tmp_path, monkeypatch, two_jobs, db):
        monkeypatch.delenv("REEVALUATE_ALL", raising=False)
        assert len(_written(tmp_path, monkeypatch, two_jobs, db)) == 2
        assert _written(tmp_path, monkeypatch, two_jobs, db) == []

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
    def test_only_a_truthy_value_enables_it(self, tmp_path, monkeypatch, two_jobs, db, value):
        """A scheduled run passes an empty string for an unset boolean input.
        Anything but an explicit yes must behave like the default."""
        monkeypatch.setenv("REEVALUATE_ALL", value)
        assert len(_written(tmp_path, monkeypatch, two_jobs, db)) == 2
        assert _written(tmp_path, monkeypatch, two_jobs, db) == []


class TestEscapeHatch:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes"])
    def test_seen_jobs_come_back(self, tmp_path, monkeypatch, two_jobs, db, value):
        monkeypatch.delenv("REEVALUATE_ALL", raising=False)
        assert len(_written(tmp_path, monkeypatch, two_jobs, db)) == 2
        monkeypatch.setenv("REEVALUATE_ALL", value)
        assert len(_written(tmp_path, monkeypatch, two_jobs, db)) == 2

    def test_the_cost_cap_still_applies(self, tmp_path, monkeypatch, db):
        """Bypassing dedup must not also bypass the spend guard: that is how
        a test run turns into an unbounded Kimi bill."""
        monkeypatch.setenv("REEVALUATE_ALL", "1")
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "3")
        jobs = [{"title": f"Job {i}", "company": f"Co{i}", "location": "Zurich",
                 "description": "z" * 300} for i in range(10)]
        assert len(_written(tmp_path, monkeypatch, jobs, db)) == 3


class TestEvaluationCapInput:
    """A blank workflow input arrives as an empty string, not as "unset"."""

    def test_blank_falls_back_to_the_default(self, monkeypatch):
        from utils import DEFAULT_MAX_EVALUATIONS_PER_RUN, max_evaluations_per_run
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "")
        assert max_evaluations_per_run() == DEFAULT_MAX_EVALUATIONS_PER_RUN

    def test_a_typo_does_not_abort_the_run(self, monkeypatch):
        from utils import DEFAULT_MAX_EVALUATIONS_PER_RUN, max_evaluations_per_run
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "thirty")
        assert max_evaluations_per_run() == DEFAULT_MAX_EVALUATIONS_PER_RUN

    def test_zero_would_evaluate_nothing_so_it_is_refused(self, monkeypatch):
        from utils import DEFAULT_MAX_EVALUATIONS_PER_RUN, max_evaluations_per_run
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "0")
        assert max_evaluations_per_run() == DEFAULT_MAX_EVALUATIONS_PER_RUN

    def test_an_explicit_low_cap_is_honoured(self, monkeypatch):
        from utils import max_evaluations_per_run
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "3")
        assert max_evaluations_per_run() == 3
