"""
test_posting_resolver.py -- Pins the recovery of full posting text.

Adzuna ships exactly 500 characters per posting, always, and the requirements
section never survives the cut. The resolver goes to the employer's own
applicant tracking system, where the complete text sits behind a public JSON
board with no bot protection.

Measured hit rate on 2026-08-23, over 40 distinct real postings: 40%. That
number is the point of this module, and so is the 60%: a miss must leave the
job with its teaser and its insufficient_info flag, visible but never
auto-APPLYed. Half-knowledge that announces itself is trustworthy; confident
half-knowledge is not.

The two ways this could turn into a silent disaster, both pinned below:

  * accepting a board that is not one. Personio answers HTTP 200 with the
    same 1.6 MB marketing page for every slug, including invented ones, so
    status codes prove nothing;
  * accepting a weak title match. Feeding the evaluator another job's
    requirements would be confidently, invisibly wrong -- worse than the
    teaser it replaced.

Nothing here touches the network: providers are injected.
"""
import pytest

import description_enricher as enricher
import posting_resolver as pr


LONG = ("We are hiring an engineer. " * 40) + "Requirements: 5 years of experience."


class TestSlugs:
    def test_legal_suffix_is_dropped(self):
        assert pr.company_slugs("BLP Digital AG")[0] == "blpdigital"

    def test_hyphenated_and_first_word_are_tried(self):
        slugs = pr.company_slugs("Gravis Robotics GmbH")
        assert "gravisrobotics" in slugs and "gravis-robotics" in slugs and "gravis" in slugs

    def test_punctuation_and_accents_do_not_leak_into_a_url(self):
        assert pr.company_slugs("Zürich Versicherungs-Gesellschaft")[0].isalnum()

    def test_empty_company_yields_nothing(self):
        assert pr.company_slugs("") == []
        assert pr.company_slugs(None) == []


class TestTitleMatching:
    def test_exact_title_matches(self):
        hit = pr.best_match("Field Robotics Engineer",
                            [("Field Robotics Engineer", LONG)])
        assert hit and hit["ratio"] == 1.0

    def test_cosmetic_differences_still_match(self):
        """Boards decorate titles: "(m/w/d)", "80-100%", "(all genders)"."""
        hit = pr.best_match("Data Platform Engineer 80-100%",
                            [("Data Platform Engineer (m/w/d)", LONG)])
        assert hit is not None

    def test_a_different_job_is_rejected(self):
        """The real case: "Machine Learning Intern, Autonomy" had left the
        Gravis board and the nearest title was a senior RL role at 0.48."""
        assert pr.best_match("Machine Learning Intern, Autonomy",
                             [("Senior Reinforcement Learning Engineer", LONG)]) is None

    def test_the_closest_of_several_wins(self):
        hit = pr.best_match("Data Engineer Intern", [
            ("Marketing Manager", LONG),
            ("Data Engineer Internship", LONG),
            ("Senior Data Architect", LONG),
        ])
        assert hit["matched_title"] == "Data Engineer Internship"


class TestProviderValidation:
    def test_personio_marketing_html_is_not_a_board(self, monkeypatch):
        """200 OK with a landing page for any slug -- the trap that would have
        'resolved' every company on earth."""
        class R:
            text = "<!DOCTYPE html><html><head><title>Personio</title></head></html>"

        monkeypatch.setattr(pr, "_get", lambda url: R())
        assert pr._personio("doesnotexist") == []

    def test_a_non_json_body_is_not_a_board(self, monkeypatch):
        class R:
            text = "<html>error</html>"

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(pr, "_get", lambda url: R())
        assert pr._greenhouse("whatever") == []
        assert pr._lever("whatever") == []


class TestResolve:
    def _only(self, monkeypatch, postings):
        monkeypatch.setattr(pr, "_BOARD_CACHE", {})
        monkeypatch.setattr(pr, "PROVIDERS", {"lever": lambda slug: postings})

    def test_a_good_match_is_returned(self, monkeypatch):
        self._only(monkeypatch, [("AI Engineer", LONG)])
        hit = pr.resolve("Acme AG", "AI Engineer")
        assert hit["provider"] == "lever" and hit["text"] == LONG

    def test_a_short_body_is_not_an_improvement(self, monkeypatch):
        """A 200-char 'full' text replaces a 500-char teaser with less."""
        self._only(monkeypatch, [("AI Engineer", "Too short.")])
        assert pr.resolve("Acme AG", "AI Engineer") is None

    def test_a_truncated_body_is_refused(self, monkeypatch):
        self._only(monkeypatch, [("AI Engineer", "We are hiring. " * 60 + "and then")])
        assert pr.resolve("Acme AG", "AI Engineer") is None

    def test_the_board_is_fetched_once_per_company(self, monkeypatch):
        """8 of 40 postings in the sample were one employer."""
        calls = []
        monkeypatch.setattr(pr, "_BOARD_CACHE", {})
        monkeypatch.setattr(pr, "PROVIDERS", {
            "lever": lambda slug: calls.append(slug) or [("AI Engineer", LONG)]})
        pr.resolve("Acme AG", "AI Engineer")
        pr.resolve("Acme AG", "AI Engineer")
        assert len(calls) == 1


class TestEnricherIntegration:
    def test_a_resolved_job_records_where_the_text_came_from(self):
        jobs = [{"company": "Acme AG", "title": "AI Engineer",
                 "description": "Teaser text that stops mid"}]
        # make it long enough to read as truncated rather than missing
        jobs[0]["description"] = "Teaser. " * 70 + "stops mid"
        replaced, attempted = enricher.resolve_full_texts(
            jobs, resolver=lambda c, t: {"provider": "lever", "text": LONG,
                                         "matched_title": t, "ratio": 1.0})
        assert (replaced, attempted) == (1, 1)
        assert jobs[0]["description"] == LONG
        assert jobs[0]["description_source"] == "lever"

    def test_a_miss_leaves_the_teaser_untouched(self):
        teaser = "Teaser. " * 70 + "stops mid"
        jobs = [{"company": "Acme AG", "title": "AI Engineer", "description": teaser}]
        replaced, attempted = enricher.resolve_full_texts(jobs, resolver=lambda c, t: None)
        assert (replaced, attempted) == (0, 1)
        assert jobs[0]["description"] == teaser
        assert enricher.needs_full_text(jobs[0])

    def test_aggregator_names_are_not_chased(self):
        """Adzuna puts the SOURCE BOARD in the company field for aggregated
        listings. "Job-Room" is not an employer and has no ATS board."""
        jobs = [{"company": "Job-Room", "title": "AI Engineer",
                 "description": "Teaser. " * 70 + "stops mid"}]
        assert enricher.resolve_full_texts(jobs, resolver=lambda c, t: 1 / 0) == (0, 0)

    def test_a_resolver_crash_does_not_lose_the_run(self):
        jobs = [{"company": "Acme AG", "title": "AI Engineer",
                 "description": "Teaser. " * 70 + "stops mid"}]

        def boom(c, t):
            raise RuntimeError("network on fire")

        assert enricher.resolve_full_texts(jobs, resolver=boom) == (0, 1)

    def test_the_budget_is_respected(self):
        jobs = [{"company": f"Acme{i} AG", "title": "AI Engineer",
                 "description": "Teaser. " * 70 + "stops mid"} for i in range(10)]
        replaced, attempted = enricher.resolve_full_texts(
            jobs, budget=3, resolver=lambda c, t: {"provider": "lever", "text": LONG,
                                                   "matched_title": t, "ratio": 1.0})
        assert attempted == 3 and replaced == 3
