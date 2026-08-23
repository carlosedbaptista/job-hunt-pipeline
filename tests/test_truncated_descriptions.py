"""
test_truncated_descriptions.py -- Pins the "the posting was cut off" guard.

The failure this exists to prevent, in full, because it is the worst one the
pipeline has produced:

The Avaloq "AI Software Engineer" posting scored 82/APPLY and the system
generated a tailored CV and cover letter for it. The posting requires at
least 5 years of full-stack development, 3 years of applied ML, 2 years with
LLMs and Agents, a proven track record of production AI, and a B.Sc. in
Computer Science. The candidate is an intern with roughly two years in tech
and a Law background. He is not eligible, and it is not close.

The model never saw any of that. Measured on 2026-08-23 across every Adzuna
record ever stored: 917 of 917 descriptions were EXACTLY 500 characters and
every one ended mid-sentence. The search API truncates, always. What survives
the cut is the opening pitch ("join our AI innovation lab, bring agentic
solutions from ideation to production") which reads as a perfect match. What
is lost is the requirements list, which is where disqualifiers live.

Re-scored with the full text, the same model returned 58/SKIP and named every
gap. The model was never the problem. It was handed 12% of the posting.

MIN_DESCRIPTION_CHARS=200 did not catch it: 500 characters looks like a real
description. So truncation is now its own signal, it feeds insufficient_info,
and insufficient_info caps the decision at REVIEW -- which also means no CV
or cover letter is ever generated off a teaser again.
"""
import pytest

from utils import effective_decision, is_truncated_description


# ─── 1. Detecting the cut ────────────────────────────────────────────────────

class TestDetection:
    ADZUNA_REAL = (
        "Job Description We are seeking a highly skilled, fast learner and well "
        "rounded, AI Software Engineer to join our AI innovation lab team. The ideal "
        "candidate will lead AI experiments and bring cutting-edge AI Agentic "
        "solutions from ideation to production. The mission of Avaloq AI Lab is to "
        "improve operational efficiency and augment Back-to-Front Office user "
        "experiences, through the application of state-of-the-art AI technology. We "
        "work collaboratively with industry leaders to deliver responsible�"
    )

    def test_the_real_adzuna_payload_is_flagged(self):
        assert is_truncated_description(self.ADZUNA_REAL)

    def test_a_complete_posting_is_not_flagged(self):
        """The full Avaloq text ends on a full stop and must score normally."""
        text = ("A bit about the role. " * 40) + "Founded and headquartered in Switzerland."
        assert not is_truncated_description(text)

    def test_explicit_ellipsis_is_flagged(self):
        assert is_truncated_description("Some long posting body. " * 30 + "and then...")

    def test_short_text_is_not_this_problem(self):
        """A bare title is already covered by MIN_DESCRIPTION_CHARS; flagging it
        here too would blur two different failures in the concern text."""
        assert not is_truncated_description("Data Engineer Intern")

    def test_empty_and_none_are_safe(self):
        assert not is_truncated_description("")
        assert not is_truncated_description(None)

    @pytest.mark.parametrize("ending", [".", "!", "?", ")", ":", ";", '"'])
    def test_sentence_endings_are_respected(self, ending):
        assert not is_truncated_description("Long posting body text. " * 30 + "Apply now" + ending)


# ─── 2. What it costs the job ────────────────────────────────────────────────

class TestDecisionCap:
    def test_a_truncated_apply_becomes_review(self):
        """The exact Avaloq shape: a high score off a teaser must not be APPLY,
        and must therefore never trigger CV/CL generation."""
        assert effective_decision({"score": 92, "insufficient_info": True}) == "REVIEW"

    def test_a_complete_apply_stays_apply(self):
        assert effective_decision({"score": 92, "insufficient_info": False}) == "APPLY"

    def test_review_and_skip_are_untouched(self):
        """The cap only removes automatic APPLY. It must not push a job down
        into SKIP, which would hide it from the candidate entirely."""
        assert effective_decision({"score": 75, "insufficient_info": True}) == "REVIEW"
        assert effective_decision({"score": 40, "insufficient_info": True}) == "SKIP"

    def test_a_hard_blocker_still_wins(self):
        assert effective_decision({"score": 92, "insufficient_info": True,
                                   "hard_blockers": ["Native German required"]}) == "SKIP"
