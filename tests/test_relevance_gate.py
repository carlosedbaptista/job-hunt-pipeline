"""
test_relevance_gate.py -- Pins the cheap gate that runs before any LLM call.

Broadening the Adzuna queries multiplied intake by 7.7 and brought the noise
with it: on 2026-08-23, 49 of 56 evaluated titles did not match the target
shape at all -- EY consulting, Videographer, Strategic Account Executive,
M&A. The scorer rejected every one correctly, at the cost of one Kimi call
each, out of a per-run cap of 30 that better jobs then could not reach.

The obvious implementation was measured and thrown away. Ranked by mean
score, the worst keywords in the history were "praktikum" (19 postings, max
45) and "werkstudent" (6, max 45) -- German for internship and working
student, the core of what he is looking for. They score low because those
particular postings did not fit. A blacklist would have deleted his entire
German-language funnel, invisibly, and "science" (as in Data Science) was on
the list too.

So the gate is a conjunction: a non-technical FUNCTION and no technical term
anywhere in the title. Validated over all 278 scored titles: it drops 13% and
the highest score among everything it drops is 35.

A false positive here is invisible -- the posting never reaches a human -- so
the gate is deliberately biased towards paying for the evaluation instead.
"""
import pytest

from utils import is_off_target_title


class TestRejects:
    @pytest.mark.parametrize("title", [
        "Content Marketing Lead - Customer Stories",
        "Videographer / Visual Storyteller / Content Creator (Part Time)",
        "Strategic Account Executive",
        "Customer Marketing & Advocacy Manager",
        "Intern Strategy & M&A, 100% - 4-6 Monate",
        "Praktikant:in Sales & Business Development (80-100%)",
        "Emerging Talent Specialist",
    ])
    def test_non_technical_roles_are_dropped(self, title):
        assert is_off_target_title(title)


class TestKeeps:
    @pytest.mark.parametrize("title", [
        # The German internship words a keyword blacklist would have killed.
        "Praktikum Data Engineering",
        "Werkstudent AI",
        "Praktikum AI",
        # A technical role in a non-technical DOMAIN stays: the domain is not
        # the disqualifier, the function is.
        "AI Engineer - Marketing Analytics",
        "Data Scientist, Wealth Management",
        "Machine Learning Engineer, Trading Systems",
        "Software Engineer - Tax Technology",
        # Plain target roles.
        "Machine Learning Intern",
        "Data Engineer Intern",
        "Junior AI Engineer",
        "AI Software Engineer",
    ])
    def test_anything_technical_survives(self, title):
        assert not is_off_target_title(title)

    @pytest.mark.parametrize("title", ["", None, "   "])
    def test_a_missing_title_is_never_dropped(self, title):
        """An unparsed title is a parser problem, not a relevance signal."""
        assert not is_off_target_title(title)


class TestHistoricalSafety:
    def test_it_never_drops_a_job_that_scored_well(self):
        """The guarantee that makes this safe to run unattended, re-derived
        from the committed history rather than trusted from a comment."""
        import glob
        import json

        worst_kept = 0
        for path in sorted(glob.glob("data/history/evaluations_*.json")):
            try:
                records = json.load(open(path, encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for record in records:
                score = record.get("score")
                title = str((record.get("job") or {}).get("title") or "")
                if isinstance(score, int) and title and is_off_target_title(title):
                    worst_kept = max(worst_kept, score)
        # Nothing it drops has ever come close to REVIEW (70).
        assert worst_kept <= 45, f"gate dropped a posting scoring {worst_kept}"
