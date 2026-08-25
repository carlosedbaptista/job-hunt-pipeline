"""Dashboard identity merge (2026-08-25).

The exact dedup key (normalized company+title) splits ONE posting into two
dashboard rows when a job board pads the title ('AI Engineer (80%-100%) -
Zurich') or the company arrives under an alias ('iudexnc' vs 'Iudex Non
Calculat') -- and a manual re-evaluation, designed to REPLACE the older
row, then shows as a second row with a second score. The compatibility
merge in src/dashboard.py is the second pass that fixes it; these tests pin
both real pairs plus the near-misses that must NOT merge.
"""
import dashboard


def _ev(company, title, score=80, decision="APPLY"):
    return {"score": score, "decision": decision,
            "job": {"company": company, "title": title,
                    "location": "Zurich", "url": ""}}


class TestStrongTitle:
    def test_strips_workload_parens_and_location_tail(self):
        assert (dashboard._strong_title("AI Engineer (80%-100%) - Zurich")
                == dashboard._strong_title("AI Engineer "))

    def test_hyphen_suffix_that_is_not_a_location_survives(self):
        assert (dashboard._strong_title("Software Engineer - Frontend")
                != dashboard._strong_title("Software Engineer - Backend"))

    def test_location_tail_only_stripped_at_the_end(self):
        # 'Remote' mid-title is content, not padding
        assert dashboard._strong_title("Remote Sensing Data Analyst")


class TestCompaniesCompatible:
    def test_emoji_variant_is_equal_after_normalisation(self):
        assert dashboard._companies_compatible("Code Compass 🧭", "Code Compass")

    def test_alias_first_token_plus_initials(self):
        assert dashboard._companies_compatible("iudexnc", "Iudex Non Calculat")

    def test_common_first_token_is_not_enough(self):
        assert not dashboard._companies_compatible(
            "Swiss International Air Lines", "Swiss Re")

    def test_unknown_never_compatible(self):
        assert not dashboard._companies_compatible("Unknown", "Unknown")
        assert not dashboard._companies_compatible("", "Acme")


class TestMergeCompatibleJobs:
    def test_code_compass_pair_merges_and_first_seen_wins(self):
        # manual evaluation inserted first (its design: re-evaluation replaces)
        rows = dashboard.merge_compatible_jobs([
            _ev("Code Compass", "AI Engineer ", score=82),
            _ev("Code Compass 🧭", "AI Engineer (80%-100%) - Zurich", score=85)])
        assert len(rows) == 1
        assert rows[0]["score"] == 82
        assert rows[0]["job"]["company"] == "Code Compass"

    def test_iudex_alias_pair_merges(self):
        rows = dashboard.merge_compatible_jobs([
            _ev("iudexnc", "Engineering Internship - AI/Data", score=78,
                decision="REVIEW"),
            _ev("Iudex Non Calculat", "Engineering Internship - AI/Data",
                score=72, decision="REVIEW")])
        assert len(rows) == 1
        assert rows[0]["score"] == 78

    def test_different_companies_same_title_stay_separate(self):
        rows = dashboard.merge_compatible_jobs([
            _ev("Swiss International Air Lines", "Data Analyst", score=70),
            _ev("Swiss Re", "Data Analyst", score=71)])
        assert len(rows) == 2

    def test_same_company_different_titles_stay_separate(self):
        rows = dashboard.merge_compatible_jobs([
            _ev("Acme", "Data Engineer", score=70),
            _ev("Acme", "AI Engineer", score=71)])
        assert len(rows) == 2

    def test_unknown_companies_do_not_collapse(self):
        rows = dashboard.merge_compatible_jobs([
            _ev("Unknown", "Internship", score=60),
            _ev("Unknown", "Internship", score=61)])
        assert len(rows) == 2
