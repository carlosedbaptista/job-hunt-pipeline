"""
test_adzuna_targeting.py -- Pins the Adzuna search budget and reach.

Measured on 2026-08-23 over the 84 days of data/raw_jobs/ (897 postings):

  * the search ran against Zurich AND Zug. Zug produced 4 DISTINCT jobs in
    those 84 days while consuming half the free tier -- roughly 2,000 calls
    for four postings. Zug is 30 km from Zurich, so a wider radius reaches it
    inside the Zurich call;
  * `results_per_page` was 20 when Adzuna allows 50, and the extra 30 cost
    nothing: page size does not change the call count;
  * Adzuna's default radius is 5 km, which silently excluded Zug, Winterthur
    and Baden even though the candidate's target area is "Zurich area".

The free tier is 100 calls/day and the arithmetic is easy to break by adding
one innocent-looking query, so it is asserted here rather than left in a
comment. Nothing below touches the network.
"""
import adzuna_ingestor as adz


# ─── 1. The daily call budget ────────────────────────────────────────────────

class TestQuota:
    #  queries x locations x runs/day, plus description_enricher's lookups.
    RUNS_PER_DAY = 2
    ENRICHER_LOOKUPS_PER_RUN = 12
    FREE_TIER_PER_DAY = 100

    def test_daily_calls_stay_inside_the_free_tier(self):
        search = len(adz.SEARCH_QUERIES) * len(adz.LOCATIONS) * self.RUNS_PER_DAY
        enrich = self.ENRICHER_LOOKUPS_PER_RUN * self.RUNS_PER_DAY
        assert search + enrich <= self.FREE_TIER_PER_DAY, (
            f"{search} search + {enrich} enrich = {search + enrich} calls/day "
            f"exceeds Adzuna's free tier of {self.FREE_TIER_PER_DAY}"
        )

    def test_a_run_cannot_exceed_its_own_hit_cap(self):
        """ADZUNA_MAX_HITS aborts the loop mid-way, which would silently drop
        the last queries in the list rather than the least useful ones."""
        assert len(adz.SEARCH_QUERIES) * len(adz.LOCATIONS) <= adz.ADZUNA_MAX_HITS


# ─── 2. Reach per call ───────────────────────────────────────────────────────

class TestReach:
    def _params(self, monkeypatch, **kwargs):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"results": []}

        class FakeClient:
            def __init__(self, timeout=None):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get(self, url, params=None):
                captured.update(params or {})
                return FakeResponse()

        monkeypatch.setattr(adz, "ADZUNA_APP_ID", "id")
        monkeypatch.setattr(adz, "ADZUNA_APP_KEY", "key")
        monkeypatch.setattr(adz.httpx, "Client", FakeClient)
        adz.fetch_adzuna("AI Engineer", "Zurich", **kwargs)
        return captured

    def test_radius_reaches_zug(self, monkeypatch):
        """Zug is ~30 km out. At Adzuna's 5 km default it is invisible."""
        assert int(self._params(monkeypatch)["distance"]) >= 30

    def test_page_size_is_the_maximum(self, monkeypatch):
        """A bigger page is the same single call -- never leave results unread."""
        assert self._params(monkeypatch)["results_per_page"] == "50"

    def test_distance_is_overridable_per_call(self, monkeypatch):
        assert self._params(monkeypatch, distance_km=5)["distance"] == "5"


# ─── 3. Targeting stays overridable without a code change ────────────────────

class TestOverrides:
    def test_queries_and_locations_have_defaults(self):
        assert adz.SEARCH_QUERIES and adz.LOCATIONS
        assert "Zurich" in adz.LOCATIONS

    def test_no_duplicate_queries(self):
        """A duplicate is a wasted call out of a budget of 100."""
        assert len(adz.SEARCH_QUERIES) == len(set(adz.SEARCH_QUERIES))
