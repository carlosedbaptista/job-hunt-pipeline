"""Dedup kernel strengthening (2026-08-25).

The exact hash split ONE posting into two seen/evaluated jobs when a board
padded the title ('AI Engineer (80%-100%) - Zurich') or the company arrived
under an alias ('iudexnc' vs 'Iudex Non Calculat') -- the same pair the
dashboard merge caught in the view. These tests pin the strengthened hash,
the compatibility second layer in filter_new_jobs, and the rehash_seen_jobs
migration for rows stored under the old function.
"""
import sqlite3

import deduplicator as dd


def _job(company, title, location="Zurich"):
    return {"company": company, "title": title, "location": location,
            "url": "", "portal": "test"}


def _seed_seen(db_path, rows):
    dd.init_db(db_path)
    conn = sqlite3.connect(db_path)
    now = "2026-08-20T00:00:00+00:00"
    for company, title, location in rows:
        h = dd.make_hash(company, title, location)
        conn.execute(
            "INSERT OR REPLACE INTO seen_jobs "
            "(hash, company, title, location, url, portal, first_seen, last_seen, status) "
            "VALUES (?, ?, ?, ?, '', 'test', ?, ?, 'new')",
            (h, company, title, location, now, now))
    conn.commit()
    conn.close()


class TestStrengthenedHash:
    def test_padded_title_hashes_like_the_clean_one(self):
        assert dd.make_hash("Code Compass", "AI Engineer (80%-100%) - Zurich", "Zurich") == \
               dd.make_hash("Code Compass", "AI Engineer ", "Zurich")

    def test_company_alias_still_does_not_hash_equal(self):
        # Aliases are NOT a hash concern: they belong to the compat layer.
        assert dd.make_hash("iudexnc", "Engineering Internship - AI/Data", "Zurich") != \
               dd.make_hash("Iudex Non Calculat", "Engineering Internship - AI/Data", "Zurich")

    def test_existing_pins_untouched(self):
        assert dd.make_hash("ACME", "Engineer", "Zürich") == \
               dd.make_hash("ACME", "Engineer", "Zurich")
        assert dd.make_hash("BLP Digital AG", "Engineer", "Zurich") == \
               dd.make_hash("BLP Digital", "Engineer", "Zurich")
        assert dd.make_hash("ACME", "Eng", "Zurich") != \
               dd.make_hash("ACME", "Eng", "Zug")


class TestFilterCompatLayer:
    def test_alias_duplicate_is_filtered_and_touches_last_seen(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        _seed_seen(db, [("Iudex Non Calculat",
                         "Engineering Internship - AI/Data", "Zürich")])
        new = dd.filter_new_jobs(
            [_job("iudexnc", "Engineering Internship - AI/Data")], db_path=db)
        assert new == []
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT COUNT(*) FROM seen_jobs").fetchone()[0]
        touched = conn.execute("SELECT last_seen FROM seen_jobs").fetchone()[0]
        conn.close()
        assert rows == 1                      # no second row for the same job
        assert touched > "2026-08-20"         # last_seen updated by the hit

    def test_swiss_near_miss_stays_separate(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        _seed_seen(db, [("Swiss International Air Lines", "Data Analyst", "Zurich")])
        new = dd.filter_new_jobs([_job("Swiss Re", "Data Analyst")], db_path=db)
        assert len(new) == 1

    def test_unknown_companies_never_merge(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        _seed_seen(db, [("Unknown", "Internship", "Zurich")])
        new = dd.filter_new_jobs([_job("Unknown", "Internship")], db_path=db)
        # exact hash DOES merge identical Unknown rows (same key, no alias
        # involved); the 'never compatible' guard only blocks the fuzzy pass
        assert new == []

    def test_location_mismatch_blocks_the_alias(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        _seed_seen(db, [("Iudex Non Calculat",
                         "Engineering Internship - AI/Data", "Zurich")])
        new = dd.filter_new_jobs(
            [_job("iudexnc", "Engineering Internship - AI/Data", "Zug")],
            db_path=db)
        assert len(new) == 1


class TestRehashMigration:
    def test_old_hash_rows_are_recomputed(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        dd.init_db(db)
        conn = sqlite3.connect(db)
        # A row hashed the OLD way (title through plain normalize()).
        import hashlib
        old_key = "code compass|ai engineer 80 100 zurich|zurich"
        old_h = hashlib.sha256(old_key.encode()).hexdigest()[:16]
        conn.execute(
            "INSERT INTO seen_jobs (hash, company, title, location, url, portal, "
            "first_seen, last_seen, status) VALUES (?, ?, ?, ?, '', 'test', ?, ?, 'new')",
            (old_h, "Code Compass", "AI Engineer (80%-100%) - Zurich", "Zurich",
             "2026-08-20", "2026-08-20"))
        conn.commit()
        conn.close()

        result = dd.rehash_seen_jobs(db)

        assert result["rehashed"] == 1
        conn = sqlite3.connect(db)
        new_h = conn.execute("SELECT hash FROM seen_jobs").fetchone()[0]
        conn.close()
        assert new_h == dd.make_hash("Code Compass",
                                     "AI Engineer (80%-100%) - Zurich", "Zurich")

    def test_collisions_merge_keeping_the_best_of_both(self, tmp_path):
        db = str(tmp_path / "jobs.db")
        dd.init_db(db)
        conn = sqlite3.connect(db)
        # Two rows that only collide under the NEW hash.
        h1 = "0" * 16
        h2 = "f" * 16
        for h, first, last in ((h1, "2026-08-01", "2026-08-10"),
                               (h2, "2026-07-20", "2026-08-21")):
            conn.execute(
                "INSERT INTO seen_jobs (hash, company, title, location, url, portal, "
                "first_seen, last_seen, status) VALUES (?, ?, ?, ?, '', 'test', ?, ?, 'new')",
                (h, "Code Compass", "AI Engineer (80%-100%) - Zurich", "Zurich",
                 first, last))
        conn.commit()
        conn.close()

        result = dd.rehash_seen_jobs(db)

        assert result["merged"] == 1
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT first_seen, last_seen FROM seen_jobs").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0] == ("2026-07-20", "2026-08-21")  # earliest, latest
