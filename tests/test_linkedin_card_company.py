"""
test_linkedin_card_company.py -- The employer must survive the card merge.

A LinkedIn alert renders each posting twice: once as the bare title, once as
the whole card blob ("<title> <company> - <location> (Hybrid) Easy Apply").
_collapse_card_variants merges the two and lifts company and location out of
the tail -- but only when the existing field was "Unknown".

For LinkedIn it never is. The parser fills company from the same blob it
fills the title from, so the two come out identical and the field LOOKS
populated; the real employer, sitting in the tail, was discarded. The posting
then hashed as (title, title, city) while the same job from a job board
hashed as (company, title, city). The two never deduplicated and both were
evaluated, every day, for as long as the posting stayed up.

Measured 2026-09-14 over data/raw_jobs/: 428 affected cards, all from
linkedin.com, inside a history where 130 of 370 scored evaluations -- 35% of
the spend -- were re-scores of byte-identical text.
"""
import email_parser_local as ep


def _cards(title, company, location):
    """The two rows one LinkedIn card produces, as the parser sees them."""
    return [
        {"title": title, "company": title, "location": location,
         "url": "", "portal": "linkedin.com"},
        {"title": f"{title} {company} · {location} (Hybrid) Easy Apply",
         "company": title, "location": location,
         "url": "https://linkedin.com/jobs/view/1", "portal": "linkedin.com"},
    ]


class TestTheEmployerIsRecovered:
    def test_company_equal_to_title_is_treated_as_unset(self):
        out = ep._collapse_card_variants(
            _cards("Working Student AI & Digital Innovation", "Arcplace AG", "Zurich"))
        assert len(out) == 1
        assert out[0]["company"] == "Arcplace AG"

    def test_the_title_is_not_damaged(self):
        out = ep._collapse_card_variants(
            _cards("Junior AI & Knowledge Engineer", "Randstad Digital", "Zurich"))
        assert out[0]["title"] == "Junior AI & Knowledge Engineer"

    def test_case_and_spacing_do_not_hide_the_repetition(self):
        cards = _cards("AI Engineer", "ParetoLabs", "Zurich")
        cards[0]["company"] = "  ai engineer  "
        cards[1]["company"] = "  ai engineer  "
        assert ep._collapse_card_variants(cards)[0]["company"] == "ParetoLabs"


class TestAGenuineCompanyIsNeverOverwritten:
    def test_a_real_employer_survives(self):
        """The guard must not turn into "always overwrite": a card that
        already names its employer keeps it."""
        cards = _cards("AI Engineer", "ParetoLabs", "Zurich")
        cards[0]["company"] = "Already Correct AG"
        out = ep._collapse_card_variants(cards)
        assert out[0]["company"] == "Already Correct AG"


class TestLocation:
    def test_the_company_city_blob_is_replaced_by_the_city(self):
        cards = _cards("AI Engineer", "Arcplace AG", "Zurich")
        cards[0]["location"] = "Arcplace AG · Zurich (Hybrid)"
        assert ep._collapse_card_variants(cards)[0]["location"] == "Zurich"

    def test_a_plain_city_is_left_alone(self):
        cards = _cards("AI Engineer", "Arcplace AG", "Zurich")
        cards[0]["location"] = "Winterthur"
        assert ep._collapse_card_variants(cards)[0]["location"] == "Winterthur"


class TestTheyNowDeduplicate:
    def test_the_linkedin_card_and_the_board_row_hash_alike(self):
        """The whole point: the same posting from two sources must collapse."""
        from deduplicator import make_hash
        out = ep._collapse_card_variants(
            _cards("Junior AI & Knowledge Engineer", "Randstad Digital", "Zurich"))
        from_linkedin = make_hash(out[0]["company"], out[0]["title"], out[0]["location"])
        from_board = make_hash("Randstad Digital", "Junior AI & Knowledge Engineer", "Zurich")
        assert from_linkedin == from_board
