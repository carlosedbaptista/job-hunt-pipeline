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


class TestSkillOrdering:
    """The CV leads with the stack the posting names.

    Reordering only. It is the one part of the CV besides the summary that can
    be adapted without risking a claim he would have to defend in an interview
    -- unlike rewriting experience bullets, which is exactly where the model
    invented a mechanism on 2026-08-23.
    """

    SKILLS = ["Python", "Power BI", "Docker", "GitHub Actions",
              "Oracle NetSuite", "TypeScript"]

    def test_skills_named_in_the_posting_come_first(self):
        ordered = dg._order_skills_for_job(
            self.SKILLS, "We build with TypeScript and Docker containers.")
        assert ordered[:2] == ["Docker", "TypeScript"]

    def test_nothing_is_added_or_lost(self):
        """A reordering that drops a skill would silently shrink his CV."""
        ordered = dg._order_skills_for_job(self.SKILLS, "TypeScript and Docker.")
        assert sorted(ordered) == sorted(self.SKILLS)

    def test_relative_order_is_kept_within_each_group(self):
        ordered = dg._order_skills_for_job(self.SKILLS, "Python, Docker.")
        assert ordered == ["Python", "Docker", "Power BI", "GitHub Actions",
                           "Oracle NetSuite", "TypeScript"]

    def test_no_description_leaves_the_order_untouched(self):
        assert dg._order_skills_for_job(self.SKILLS, "") == self.SKILLS
        assert dg._order_skills_for_job(self.SKILLS, None) == self.SKILLS

    def test_a_one_character_skill_cannot_match_everything(self):
        """"R" or "C" would otherwise be "named" by almost any posting."""
        ordered = dg._order_skills_for_job(["R", "Docker"], "We use Docker.")
        assert ordered == ["Docker", "R"]

    def test_matching_ignores_case(self):
        ordered = dg._order_skills_for_job(["Docker"], "we use DOCKER daily")
        assert ordered == ["Docker"]


class TestSummaryIsReusable:
    """The CV summary must not read like a cover letter.

    A generated summary ended with "Seeking the BLP Digital internship to
    apply...". The candidate caught it. Naming the employer makes the
    document single-use, and in a Drive with one folder per job the wrong
    attachment eventually goes out -- telling a reader he wants to work
    somewhere else. The letter already argues for the specific job.

    The same summary also rewrote one of his metrics: the profile says
    "reducing manual data entry by ~40%", the summary said "automated 40% of
    manual data entry". Those are different claims, and he is the one who has
    to defend the number in an interview.

    Model prose cannot be asserted deterministically, so what is pinned is
    the contract handed to it.
    """

    def test_the_target_employer_is_forbidden_by_name(self, prompt):
        assert "NEVER name the employer" in prompt
        assert "Acme AG" in prompt  # the actual value is interpolated

    def test_metrics_must_be_quoted_not_paraphrased(self, prompt):
        assert "Quote his metrics exactly" in prompt
        assert "including any hedge" in prompt

    def test_the_exact_distortion_is_named(self, prompt):
        """Naming the real failure beats a general rule the model can read
        past."""
        assert "automated 40% of" in prompt

    def test_work_in_progress_is_deprioritised(self, prompt):
        assert "work in progress" in prompt or "still under way" in prompt
