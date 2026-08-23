"""
test_cv_summary.py -- Pins the CV's Profile Summary against renaming the man.

The candidate caught this: his CV header reads "AI & Automation Developer
Intern", and the summary printed directly beneath it opened with "Automation
developer with hands-on experience...". The model had quietly dropped both
"AI &" and "Intern". His words: a summary describing him as a Software
Developer for a software role contradicts the line above it.

He is right, and it is the worse kind of wrong: a document that disagrees
with itself reads as a template nobody checked.

Two causes, both fixed and both pinned here. The prompt never told the model
the title was already on the page, and it was starved of material -- it got
job TITLES with no bullets, which is why it produced keyword soup ("Skilled
in Python, SQL, REST APIs") instead of a summary that knew anything. Same
starvation that made the cover letter invent a mechanism.

The model's prose cannot be asserted deterministically, so what is pinned is
the contract handed to it.
"""
import pytest

import doc_generator as dg


PROFILE = {
    "name": "Test Candidate",
    "role": "AI & Automation Developer Intern",
    "target_role": "internship in agentic systems",
    "summary": "I didn't start in tech.",
    "skills": {"technical_default": ["Python", "SQL"]},
    "experience": [
        {"title": "Automation Intern", "company": "Acme",
         "bullets": ["Cut manual entry by 40%", "Shipped a pipeline"]},
    ],
}


@pytest.fixture
def prompt(monkeypatch):
    seen = {}

    class FakeClient:
        def chat(self, messages, **kw):
            seen["prompt"] = messages[0]["content"]
            return "a summary"

    dg._generate_summary(FakeClient(), PROFILE, "Software Engineer", "Acme AG",
                         "A long job description. " * 200)
    return seen["prompt"]


class TestRoleProtection:
    def test_the_exact_title_is_given_to_the_model(self, prompt):
        assert PROFILE["role"] in prompt

    def test_the_model_is_told_the_title_is_already_on_the_page(self, prompt):
        assert "printed directly" in prompt and "above this summary" in prompt

    def test_renaming_is_forbidden_by_example(self, prompt):
        """The two shapes he actually feared, named explicitly."""
        assert "Software Developer" in prompt and "Data Engineer" in prompt


class TestMaterial:
    def test_experience_bullets_reach_the_model(self, prompt):
        """Titles alone produced keyword soup."""
        assert "Cut manual entry by 40%" in prompt

    def test_his_own_words_reach_the_model(self, prompt):
        assert "I didn't start in tech." in prompt

    def test_the_job_is_named(self, prompt):
        assert "Software Engineer" in prompt and "Acme AG" in prompt

    def test_a_long_posting_is_clipped_not_dropped(self, prompt):
        """Clipped, so the summary still sees what the job asks for."""
        assert "A long job description." in prompt
        assert len(prompt) < 6000


class TestVoice:
    def test_keyword_lists_and_filler_are_banned(self, prompt):
        for banned in ("keyword lists", "proven track record", "passionate"):
            assert banned in prompt

    def test_invention_is_still_forbidden(self, prompt):
        assert "invent nothing" in prompt
