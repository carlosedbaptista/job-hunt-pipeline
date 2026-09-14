"""
test_usage_accounting.py -- Pins token accounting and the refusal to guess.

The pipeline had a cost CAP (max_evaluations_per_run) but no cost ACCOUNTING:
tokens were persisted for the orchestrator, one call per run, and not for the
evaluations, up to thirty. Estimating a run's spend meant measuring prompt
strings by hand.

The rule these tests exist to protect: an unpriced model yields None, never a
number. A fabricated price would be charted and believed.
"""
import json

import kimi_client
import pricing
import pytest


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(kimi_client, "SESSION_USAGE",
                        {"calls": 0, "prompt_tokens": 0,
                         "completion_tokens": 0, "model": ""})
    pricing._cache = None
    yield
    pricing._cache = None


def _table(tmp_path, models):
    p = tmp_path / "pricing.json"
    p.write_text(json.dumps({"models": models}), encoding="utf-8")
    return str(p)


class TestRefusesToGuess:
    def test_unknown_model_is_unpriced(self, tmp_path):
        path = _table(tmp_path, {})
        assert pricing.cost_usd("kimi-k2.6", 1000, 100, path=path) is None

    def test_null_price_is_unpriced(self, tmp_path):
        """The shipped config has every price null; that must not read as free."""
        path = _table(tmp_path, {"kimi-k2.6": {"input_per_1m_usd": None,
                                               "output_per_1m_usd": None}})
        assert pricing.cost_usd("kimi-k2.6", 1000, 100, path=path) is None

    def test_half_a_price_is_no_price(self, tmp_path):
        """Charging input while treating output as free understates every run."""
        path = _table(tmp_path, {"m": {"input_per_1m_usd": 2.0,
                                       "output_per_1m_usd": None}})
        assert pricing.cost_usd("m", 1000, 100, path=path) is None

    def test_missing_file_does_not_raise(self, tmp_path):
        assert pricing.cost_usd("m", 10, 10, path=str(tmp_path / "nope.json")) is None

    def test_shipped_config_prices_nothing_yet(self):
        """Guards against someone pasting a plausible-looking price in."""
        assert pricing.cost_usd("kimi-k2.6", 1_000_000, 1_000_000) is None


class TestArithmetic:
    def test_both_directions_are_charged(self, tmp_path):
        path = _table(tmp_path, {"m": {"input_per_1m_usd": 2.0,
                                       "output_per_1m_usd": 10.0}})
        # 1M in at $2 + 0.5M out at $10 = 2 + 5
        assert pricing.cost_usd("m", 1_000_000, 500_000, path=path) == pytest.approx(7.0)


class TestSessionCounters:
    def test_usage_since_measures_the_delta(self):
        before = kimi_client.usage_snapshot()
        kimi_client._record_usage({"prompt_tokens": 100, "completion_tokens": 20}, "kimi-k2.6")
        kimi_client._record_usage({"prompt_tokens": 50, "completion_tokens": 5}, "kimi-k2.6")
        u = kimi_client.usage_since(before)
        assert u["calls"] == 2
        assert u["prompt_tokens"] == 150
        assert u["completion_tokens"] == 25
        assert u["model"] == "kimi-k2.6"

    def test_no_call_records_nothing(self):
        """A mocked evaluation must not leave a row of zeros behind: that
        would read as a measured free call."""
        before = kimi_client.usage_snapshot()
        assert kimi_client.usage_since(before) is None

    def test_only_the_new_calls_are_charged(self):
        kimi_client._record_usage({"prompt_tokens": 999, "completion_tokens": 999}, "m")
        before = kimi_client.usage_snapshot()
        kimi_client._record_usage({"prompt_tokens": 10, "completion_tokens": 1}, "m")
        assert kimi_client.usage_since(before)["prompt_tokens"] == 10


class TestSummary:
    def test_unknown_share_reports_what_could_not_be_priced(self):
        s = pricing.summarise([
            {"calls": 1, "prompt_tokens": 10, "completion_tokens": 1, "cost_usd": 0.5},
            {"calls": 3, "prompt_tokens": 30, "completion_tokens": 3, "cost_usd": None},
        ])
        assert s["calls"] == 4
        assert s["known_usd"] == pytest.approx(0.5)
        assert s["unpriced_calls"] == 3
        assert s["unknown_share"] == pytest.approx(0.75)

    def test_empty_summary_is_not_a_division_by_zero(self):
        assert pricing.summarise([])["unknown_share"] == 0.0

    def test_none_entries_are_skipped(self):
        """Evaluations that spent nothing store usage=None."""
        assert pricing.summarise([None, {"calls": 1, "cost_usd": None}])["calls"] == 1
