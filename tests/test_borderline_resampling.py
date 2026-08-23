"""
test_borderline_resampling.py -- Pins the second opinion on borderline scores.

Measured on 2026-08-23, five identical calls per condition on one posting:

    truncated text: 65, 68, 68, 65, 65   (spread 3)
    full text:      55, 55, 55, 35, 45   (spread 20)

The score wanders by up to 20 points between calls with byte-identical input.
That cannot be tuned away: kimi-k2.6 rejects every temperature setting with
"invalid temperature: only 1 is allowed for this model".

It usually does not matter -- all ten samples above still agreed the job was a
SKIP, and a job that is really a 45 does not care whether it prints 40 or 50.
It matters enormously in one place: on a threshold. At THRESHOLD_APPLY=80 a
job whose true score is 80 becomes APPLY or REVIEW depending on which sample
happened to arrive, and APPLY is what generates a CV and tells the candidate
to go for it.

So the second opinion is bought exactly there and nowhere else: within one
standard deviation of a boundary, score three times, keep the median. Around
90% of jobs stay at one call.
"""
import pytest

import job_evaluator as je
from utils import THRESHOLD_APPLY, THRESHOLD_REVIEW


@pytest.fixture
def sampling_on(monkeypatch):
    """conftest disables re-sampling suite-wide; these tests want it."""
    monkeypatch.setenv("BORDERLINE_SAMPLES", "2")
    monkeypatch.setenv("BORDERLINE_BAND", "8")
    monkeypatch.setattr(je.time, "sleep", lambda *_: None)


class TestWhenItTriggers:
    @pytest.mark.parametrize("score", [THRESHOLD_APPLY, THRESHOLD_APPLY - 8,
                                       THRESHOLD_APPLY + 8, THRESHOLD_REVIEW,
                                       THRESHOLD_REVIEW - 8, THRESHOLD_REVIEW + 8])
    def test_scores_near_a_threshold_are_resampled(self, sampling_on, score):
        assert je._is_borderline(score)

    @pytest.mark.parametrize("score", [0, 20, 45, 95, 100])
    def test_scores_far_from_any_threshold_are_not(self, sampling_on, score):
        """The other ~90% of jobs must stay at one call each."""
        assert not je._is_borderline(score)

    def test_the_mechanism_can_be_switched_off(self, monkeypatch):
        monkeypatch.setenv("BORDERLINE_SAMPLES", "0")
        assert not je._is_borderline(THRESHOLD_APPLY)

    def test_a_bad_env_value_does_not_crash_scoring(self, monkeypatch):
        monkeypatch.setenv("BORDERLINE_SAMPLES", "two")
        monkeypatch.setenv("BORDERLINE_BAND", "wide")
        assert je._borderline_samples() == je.DEFAULT_BORDERLINE_SAMPLES
        assert je._borderline_band() == je.DEFAULT_BORDERLINE_BAND


class TestMedian:
    def _samples(self, monkeypatch, scores):
        """Feeds the given scores to the re-sampler, in order."""
        remaining = list(scores[1:])

        def fake(prompt, system=None, max_tokens=1000):
            return {"score": remaining.pop(0), "technical_fit": f"sample {remaining}"}

        monkeypatch.setattr(je, "call_kimi_json", fake)
        return je._median_of_three(
            "prompt", {"score": scores[0], "technical_fit": "first"}, scores[0], "T", "C")

    def test_the_median_wins_not_the_first_sample(self, sampling_on, monkeypatch):
        _, score = self._samples(monkeypatch, [85, 70, 78])
        assert score == 78

    def test_an_outlier_first_sample_is_outvoted(self, sampling_on, monkeypatch):
        """The exact failure mode: one lucky 85 turning a REVIEW into APPLY."""
        _, score = self._samples(monkeypatch, [85, 72, 74])
        assert score == 74

    def test_the_kept_reasoning_belongs_to_the_kept_score(self, sampling_on, monkeypatch):
        """Showing the median number beside the first sample's reasoning would
        be its own quiet lie."""
        ev, score = self._samples(monkeypatch, [90, 60, 75])
        assert score == 75
        assert ev["score"] == 75

    def test_a_failed_resample_keeps_the_first_score(self, sampling_on, monkeypatch):
        def boom(prompt, system=None, max_tokens=1000):
            raise RuntimeError("API down")

        monkeypatch.setattr(je, "call_kimi_json", boom)
        ev, score = je._median_of_three("prompt", {"score": 81}, 81, "T", "C")
        assert score == 81

    def test_an_unusable_resample_is_ignored_not_counted(self, sampling_on, monkeypatch):
        """A sample with no usable score must not become a vote."""
        remaining = [{"score": None}, {"score": 60}]

        def fake(prompt, system=None, max_tokens=1000):
            return remaining.pop(0)

        monkeypatch.setattr(je, "call_kimi_json", fake)
        _, score = je._median_of_three("prompt", {"score": 80}, 80, "T", "C")
        assert score in (60, 80)  # two valid samples, either may be the median
