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


class TestBudgetPriority:
    """The cost cap slices the first n, so the ORDER decides what gets scored.

    Sources arrive e-mail-first, and an alert card carries no description at
    all: it can only produce a title-based score, capped at REVIEW by
    insufficient_info. An Adzuna teaser can be expanded to the full posting.
    Spending the budget on the former first is backwards.
    """

    def test_jobs_with_more_text_are_scored_first(self, tmp_path, monkeypatch, db):
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "2")
        jobs = [
            {"title": "From an alert", "company": "A", "location": "Zurich", "description": ""},
            {"title": "Also an alert", "company": "B", "location": "Zurich", "description": ""},
            {"title": "From Adzuna", "company": "C", "location": "Zurich", "description": "x" * 500},
            {"title": "Also Adzuna", "company": "D", "location": "Zurich", "description": "y" * 500},
        ]
        picked = [j["title"] for j in _written(tmp_path, monkeypatch, jobs, db)]
        assert picked == ["From Adzuna", "Also Adzuna"]

    def test_order_within_a_group_is_preserved(self, tmp_path, monkeypatch, db):
        """A stable sort: only the quality line moves jobs, not their rank."""
        monkeypatch.delenv("MAX_EVALUATIONS_PER_RUN", raising=False)
        jobs = [{"title": f"Job {i}", "company": f"Co{i}", "location": "Zurich",
                 "description": "x" * 500} for i in range(4)]
        picked = [j["title"] for j in _written(tmp_path, monkeypatch, jobs, db)]
        assert picked == ["Job 0", "Job 1", "Job 2", "Job 3"]


class TestModelFamilyGuard:
    """Kimi models think by default, and reasoning tokens come out of the same
    max_tokens budget as the answer, so the content arrives empty or cut and
    the JSON parse fails. The payload therefore disables thinking.

    The guard used to be startswith("kimi-k2"), which silently excluded every
    newer model. Measured on 2026-08-23 while evaluating a switch to kimi-k3:
    8 of 9 scoring calls failed with "Expecting value: line 1 column 1" or
    "Unterminated string" -- the model was fine, it was the only one still
    thinking into a 1000-token budget. Whoever changes KIMI_MODEL next should
    not have to rediscover that.
    """

    def _payload(self, model):
        import kimi_client
        captured = {}

        class FakeClient(kimi_client.KimiClient):
            def __init__(self):
                self.api_key = "k"
                self.base_urls = ["http://example"]

            def _post(self, endpoint, payload, timeout_sec=60):
                captured.update(payload)
                return {"choices": [{"message": {"content": "{}"}}]}

        FakeClient()._try_model(model, [{"role": "user", "content": "x"}], 1000, None)
        return captured

    def test_thinking_is_disabled_for_the_current_model(self):
        assert self._payload("kimi-k2.6")["thinking"] == {"type": "disabled"}

    def test_and_for_a_newer_one(self):
        assert self._payload("kimi-k3")["thinking"] == {"type": "disabled"}

    def test_and_for_a_model_that_does_not_exist_yet(self):
        assert self._payload("kimi-k4.2")["thinking"] == {"type": "disabled"}

    def test_non_kimi_models_are_left_alone(self):
        """moonshot-v1-* does not take the parameter."""
        assert "thinking" not in self._payload("moonshot-v1-128k")
