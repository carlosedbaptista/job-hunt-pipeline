"""
test_ingestion_quality.py -- Pins the ingestion-side fixes.

Where test_scoring_consistency.py protects the scoring brain, this file
protects what the brain is fed. Every case below reproduces something found
in the committed data (data/history/, data/raw_jobs/) on 2026-08-21:

  * 169 of the first 190 evaluations were `insufficient_info` -- scored from
    the job title alone, and therefore capped at REVIEW by design. Only
    Adzuna, the one source that ships a description, ever produced an APPLY.
  * 36 of the 187 distinct titles were the short/long pair of ONE job-alert
    card, so the same posting was evaluated twice and the clean variant
    carried neither company nor location.
  * two "Your job alert for intern in the past" navigation links reached the
    evaluator and were scored 0/SKIP.

Nothing here touches the network: the Adzuna fetch is injected.
"""
import description_enricher as enricher
import email_parser_local as parser
from utils import deduplicate_jobs


# ─── 1. Alert navigation links are not jobs ──────────────────────────────────

class TestAlertNavigationFilter:
    def test_alert_header_rejected(self):
        assert parser._is_alert_navigation("Your job alert for internship or intern in the past")
        assert parser._is_alert_navigation("See all jobs in Zurich")
        assert parser._is_alert_navigation("3 new jobs for you")

    def test_real_titles_survive(self):
        assert not parser._is_alert_navigation("Junior AI & Knowledge Engineer")
        assert not parser._is_alert_navigation("Working Student Data Analyst 60-80%")
        assert not parser._is_alert_navigation("Praktikum Data Science")


# ─── 2. Card variants collapse into one job, with fields recovered ───────────

def _card_pair():
    """The exact shape both LinkedIn variants had in
    data/raw_jobs/all_jobs_20260821_1238.json."""
    return [
        {"title": "Junior AI & Knowledge Engineer Randstad Digital · Zurich, "
                  "Switzerland (Hybrid) Easy Apply",
         "company": "Junior AI & Knowledge Engineer",
         "location": "Randstad Digital · Zurich, Switzerland (Hybrid)",
         "url": "https://lnkd.in/card", "portal": "linkedin.com"},
        {"title": "Junior AI & Knowledge Engineer", "company": "Unknown",
         "location": "Unknown", "url": "", "portal": "linkedin.com"},
    ]


class TestCardVariantCollapse:
    def test_pair_becomes_one_job(self):
        assert len(parser._collapse_card_variants(_card_pair())) == 1

    def test_clean_title_wins_and_fields_are_recovered(self):
        job = parser._collapse_card_variants(_card_pair())[0]
        assert job["title"] == "Junior AI & Knowledge Engineer"
        assert job["company"] == "Randstad Digital"
        assert job["location"] == "Zurich, Switzerland"
        # The only URL in the pair lives on the long variant.
        assert job["url"] == "https://lnkd.in/card"

    def test_distinct_jobs_are_not_merged(self):
        jobs = [{"title": "Data Engineer", "company": "A", "location": "Zug", "url": "1"},
                {"title": "Data Scientist", "company": "B", "location": "Zug", "url": "2"}]
        assert len(parser._collapse_card_variants(jobs)) == 2

    def test_prefix_must_be_a_word_boundary(self):
        """'Data Engineer' must not swallow 'Data EngineerX' style titles that
        merely share a character prefix -- only ' '-separated card tails."""
        jobs = [{"title": "Data Engineer", "company": "A", "location": "Zug", "url": "1"},
                {"title": "Data Engineering Lead", "company": "B", "location": "Zug", "url": "2"}]
        assert len(parser._collapse_card_variants(jobs)) == 2


class TestTidyJobFields:
    def test_company_prefix_stripped_from_glassdoor_title(self):
        job = parser.tidy_job_fields(
            {"title": "Equans Intern Strategy & M&A, 100% - 4-6 Monate Zürich",
             "company": "Equans", "location": "Unknown"})
        assert job["title"] == "Intern Strategy & M&A, 100% - 4-6 Monate"
        assert job["location"] == "Zürich"

    def test_known_location_is_not_overwritten(self):
        job = parser.tidy_job_fields(
            {"title": "Data Analyst Basel", "company": "Unknown", "location": "Zug"})
        assert job["location"] == "Zug"

    def test_title_without_city_is_untouched(self):
        job = parser.tidy_job_fields(
            {"title": "Machine Learning Engineer", "company": "Unknown", "location": "Unknown"})
        assert job["title"] == "Machine Learning Engineer"
        assert job["location"] == "Unknown"


# ─── 3. In-batch dedup: same normalization as the hash, richest copy wins ────

class TestInBatchDedup:
    def test_uses_the_same_normalization_as_the_hash(self):
        """These two hash identically in deduplicator.make_hash, so they must
        not both survive the in-batch pass and cost two LLM calls."""
        jobs = [{"company": "BLP Digital AG", "title": "Data Engineer", "location": "Zürich"},
                {"company": "BLP Digital", "title": "Data Engineer", "location": "Zurich, Switzerland"}]
        assert len(deduplicate_jobs(jobs)) == 1

    def test_richest_description_wins_regardless_of_order(self):
        thin = {"company": "ACME", "title": "AI Engineer", "location": "Zurich",
                "description": "", "portal": "linkedin.com"}
        rich = {"company": "ACME", "title": "AI Engineer", "location": "Zurich",
                "description": "x" * 3000, "portal": "adzuna"}
        for order in ([thin, rich], [rich, thin]):
            (kept,) = deduplicate_jobs([dict(j) for j in order])
            assert len(kept["description"]) == 3000

    def test_missing_fields_are_backfilled_from_the_loser(self):
        rich = {"company": "ACME", "title": "AI Engineer", "location": "Zurich",
                "description": "x" * 3000, "url": ""}
        thin = {"company": "ACME", "title": "AI Engineer", "location": "Zurich",
                "description": "", "url": "https://jobs.example/1"}
        (kept,) = deduplicate_jobs([rich, thin])
        assert kept["url"] == "https://jobs.example/1"

    def test_distinct_jobs_survive_and_keep_input_order(self):
        jobs = [{"company": "A", "title": "T1", "location": "Zug"},
                {"company": "B", "title": "T2", "location": "Zug"},
                {"company": "C", "title": "T3", "location": "Zug"}]
        assert [j["company"] for j in deduplicate_jobs(jobs)] == ["A", "B", "C"]


# ─── 4. Description enrichment: helpful when sure, silent when not ───────────

def adzuna_result(title="Junior AI & Knowledge Engineer",
                  company="Randstad Digital AG", description=None):
    return {"title": title,
            "company": {"display_name": company},
            "location": {"display_name": "Zurich, Zurich"},
            "description": description if description is not None else "Real posting text. " * 30,
            "redirect_url": "https://adzuna.example/job/9?utm_source=leaks_the_app_id"}


def fetch_returning(*results):
    def _fetch(what, where="Zurich", max_days_old=7):
        return list(results)
    return _fetch


class TestSearchTerms:
    def test_percentage_and_gender_noise_removed(self):
        assert enricher.search_terms("Working Student Data Analyst 60-80% (f/m/d)") == \
               "Working Student Data Analyst"

    def test_long_titles_are_truncated_to_the_role(self):
        terms = enricher.search_terms(
            "Praktikum Marketing mit Ziel auf Festanstellung - Paid Media, Content & KI")
        assert len(terms.split()) <= 8


class TestEnrichment:
    def _blind_job(self, **over):
        job = {"title": "Junior AI & Knowledge Engineer", "company": "Randstad Digital",
               "location": "Zurich, Switzerland (Hybrid)", "description": "",
               "url": "https://lnkd.in/x", "portal": "linkedin.com"}
        job.update(over)
        return job

    def test_confident_match_attaches_the_description(self):
        jobs = [self._blind_job()]
        enriched, attempted = enricher.enrich_jobs(jobs, fetch=fetch_returning(adzuna_result()))
        assert (enriched, attempted) == (1, 1)
        assert len(jobs[0]["description"]) > 200
        assert jobs[0]["description_source"] == "adzuna_enrichment"

    def test_original_url_is_never_replaced(self):
        """The candidate applies through the link he received; enrichment only
        borrows the text."""
        jobs = [self._blind_job()]
        enricher.enrich_jobs(jobs, fetch=fetch_returning(adzuna_result()))
        assert jobs[0]["url"] == "https://lnkd.in/x"
        assert jobs[0]["enriched_from_url"].startswith("https://adzuna.example/job/9")
        assert "utm_source" not in jobs[0]["enriched_from_url"]  # app_id stripped

    def test_different_company_is_rejected(self):
        """A wrong description silently corrupts a score -- worse than none."""
        jobs = [self._blind_job()]
        enriched, _ = enricher.enrich_jobs(
            jobs, fetch=fetch_returning(adzuna_result(company="Some Other AG")))
        assert enriched == 0
        assert jobs[0]["description"] == ""

    def test_unrelated_title_at_the_same_company_is_rejected(self):
        jobs = [self._blind_job()]
        enriched, _ = enricher.enrich_jobs(
            jobs, fetch=fetch_returning(adzuna_result(title="Warehouse Operations Lead")))
        assert enriched == 0

    def test_unknown_company_requires_an_exact_title(self):
        near = self._blind_job(company="Unknown")
        assert enricher.enrich_jobs([near], fetch=fetch_returning(
            adzuna_result(title="Junior AI & Knowledge Engineer (Zurich)")))[0] == 0

        exact = self._blind_job(company="Unknown")
        assert enricher.enrich_jobs([exact], fetch=fetch_returning(adzuna_result()))[0] == 1

    def test_thin_candidate_descriptions_are_not_used(self):
        jobs = [self._blind_job()]
        enriched, _ = enricher.enrich_jobs(
            jobs, fetch=fetch_returning(adzuna_result(description="Apply now.")))
        assert enriched == 0

    def test_jobs_that_already_have_text_are_left_alone(self):
        jobs = [self._blind_job(description="y" * 500)]
        assert enricher.enrich_jobs(jobs, fetch=fetch_returning(adzuna_result()))[1] == 0

    def test_budget_caps_the_number_of_lookups(self):
        jobs = [self._blind_job(title=f"Role {i}", company=f"Comp {i}") for i in range(10)]
        assert enricher.enrich_jobs(jobs, fetch=fetch_returning(), budget=3)[1] == 3

    def test_a_failing_lookup_leaves_the_job_untouched(self):
        def boom(what, where="Zurich", max_days_old=7):
            raise RuntimeError("Adzuna 429")

        jobs = [self._blind_job()]
        enriched, attempted = enricher.enrich_jobs(jobs, fetch=boom)
        assert (enriched, attempted) == (0, 1)
        assert jobs[0]["description"] == ""

    def test_location_is_reduced_to_a_locality_for_the_query(self):
        seen = {}

        def spy(what, where="Zurich", max_days_old=7):
            seen["where"] = where
            return []

        enricher.enrich_jobs([self._blind_job()], fetch=spy)
        assert seen["where"] == "Zurich"

    def test_unknown_location_falls_back_to_zurich(self):
        seen = {}

        def spy(what, where="Zurich", max_days_old=7):
            seen["where"] = where
            return []

        enricher.enrich_jobs([self._blind_job(location="Unknown")], fetch=spy)
        assert seen["where"] == "Zurich"


# ─── 5. Re-scoring stored history under today's rules ────────────────────────

import rescore_history
from job_evaluator import detect_language_requirement_tier


class TestRescoreHistory:
    """Rules change; the records already in data/history do not. This pins
    what the deterministic pass may and may not do to them."""

    def _record(self, **over):
        record = {"score": 92, "decision": "APPLY", "hard_blockers": [],
                  "insufficient_info": False,
                  "job": {"title": "AI Engineer", "company": "ACME",
                          "description": "Build LLM pipelines. " * 20}}
        record.update(over)
        return record

    def test_language_band_change_is_applied_retroactively(self):
        """Under the old fixed {B2} band a 'German B1 required' posting was a
        soft mention. With the candidate at A2 it is an intermediate gap, and
        the stored APPLY has to become REVIEW."""
        record = self._record()
        record["job"]["description"] += " German B1 required for client contact."
        changed, before, after = rescore_history.redecide(
            record, lambda t: detect_language_requirement_tier(t, levels=["b1", "b2"]))
        assert (changed, before, after) == (True, "APPLY", "REVIEW")
        assert record["language_gap_intermediate"] is True

    def test_enriched_record_stops_being_blind(self):
        """A job scored title-only and capped at REVIEW is uncapped once a
        real description is attached."""
        record = self._record(score=85, decision="REVIEW", insufficient_info=True)
        changed, before, after = rescore_history.redecide(record, detect_language_requirement_tier)
        assert (changed, before, after) == (True, "REVIEW", "APPLY")
        assert record["insufficient_info"] is False

    def test_error_records_are_never_given_a_decision(self):
        """ERROR means the job was never scored. Re-deriving must not invent
        one -- that is the fake-score rule the whole pipeline is built on."""
        record = {"score": None, "decision": "ERROR", "job": {"description": ""}}
        changed, before, after = rescore_history.redecide(record, detect_language_requirement_tier)
        assert changed is False
        assert record["decision"] == "ERROR"
        assert record["score"] is None

    def test_hard_blocker_lock_survives_rescoring(self):
        record = self._record(hard_blockers=["Requires fluent German (C1)"])
        _, _, after = rescore_history.redecide(record, detect_language_requirement_tier)
        assert after == "SKIP"

    def test_materials_follow_the_new_decision(self):
        record = self._record(score=85, decision="REVIEW", insufficient_info=True)
        rescore_history.redecide(record, detect_language_requirement_tier)
        assert record["materials_needed"] == ["cv"]
