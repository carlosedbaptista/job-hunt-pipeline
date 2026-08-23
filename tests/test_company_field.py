"""
test_company_field.py -- Pins what may be stored as an employer name.

Found on 2026-08-23 while asking why jobs scoring 88, 85 and 82 were only
REVIEW. They were capped correctly (no description at all), but the records
underneath showed something worse: 39 of them, spread across every single day
of the history, carried a job TITLE in the company field.

    company: 'AI Engineering Student Internship (Winter or Summer 2026)...'
    company: 'Intern - Forward deployed Engineering (m/w, Zurich) Clayground'
    company: "Unknown (likely Palantir or similar given 'Forward deployed')"

Two separate causes.

_split_card_remainder takes everything before the "." separator as the
company. That is right when it receives the tail of a card whose title has
already been stripped, which is what happens when a card has both a short and
a long variant. When there is no short twin there is no title to strip, so
the whole card became the company.

And the evaluator backfills a missing company from the model's
`detected_company`, guarding only against the exact string "unknown". The
model does not answer "unknown" when it cannot tell; it speculates. That
speculation was stored as an employer name -- a field that ends up printed on
a cover letter.

The fix refuses garbage rather than trying to recover the real name from an
unstructured card. A wrong employer on a document sent to a company is far
worse than an honest "Unknown", which merely leaves the job flagged as not
understood.
"""
import pytest

from email_parser_local import MAX_COMPANY_CHARS, _reject_implausible_company


class TestRejects:
    def test_a_whole_card_is_not_a_company(self):
        card = ("AI Engineering Student Internship (Winter or Summer 2026) "
                "Bloom (YC X25)")
        assert _reject_implausible_company(card) == "Unknown"

    def test_the_models_speculation_is_not_a_company(self):
        assert _reject_implausible_company(
            "Unknown (likely Palantir or similar given 'Forward deployed')") == "Unknown"

    def test_any_unknown_prefix_is_refused(self):
        assert _reject_implausible_company("Unknown") == "Unknown"
        assert _reject_implausible_company("unknown employer") == "Unknown"

    def test_a_hedge_anywhere_is_refused(self):
        """"likely" in an employer name means the model was guessing."""
        assert _reject_implausible_company("Big Four firm, likely EY") == "Unknown"

    def test_empty_stays_unknown(self):
        assert _reject_implausible_company("") == "Unknown"
        assert _reject_implausible_company(None) == "Unknown"


class TestKeeps:
    @pytest.mark.parametrize("name", [
        "Avaloq",
        "BLP Digital AG",
        "Gravis Robotics",
        "Kanadevia Inova AG",
        "Zurich Insurance Company Ltd",
        "Gestora de Inteligencia de Credito S.A.",
        "Bloom (YC X25)",
    ])
    def test_real_employers_survive(self, name):
        assert _reject_implausible_company(name) == name

    def test_the_limit_leaves_room_for_real_names(self):
        """The longest genuine employer in the history is well under it."""
        assert MAX_COMPANY_CHARS >= len("Gestora de Inteligencia de Credito S.A.")


class TestEvaluatorBackfill:
    """The same speculation must not come back through detected_company."""

    def test_speculative_detection_is_not_written_to_the_record(self):
        import job_evaluator as je

        job = {"title": "Intern - Forward deployed Engineering",
               "company": "Unknown", "location": "Zurich",
               "description": "x" * 400}
        fake = {"score": 85, "decision": "REVIEW", "concerns": [],
                "hard_blockers": [],
                "detected_company": "Unknown (likely Palantir or similar)",
                "detected_title": "", "detected_location": "Zurich"}
        je.call_kimi_json = lambda *a, **kw: dict(fake)
        result = je.evaluate_job(job)
        assert result["job"]["company"] == "Unknown"

    def test_a_real_detection_is_still_written(self):
        import job_evaluator as je

        job = {"title": "AI Engineer", "company": "Unknown",
               "location": "Zurich", "description": "x" * 400}
        fake = {"score": 60, "decision": "SKIP", "concerns": [],
                "hard_blockers": [], "detected_company": "Avaloq",
                "detected_title": "", "detected_location": ""}
        je.call_kimi_json = lambda *a, **kw: dict(fake)
        assert je.evaluate_job(job)["job"]["company"] == "Avaloq"
