"""
test_rescore_filters.py -- Pins --before and --decision on the full re-score.

Both exist because --limit alone cannot express the job that comes up after a
target change. Re-scoring the newest N records leaves older ones carrying
scores from the old target: on 2026-09-14 the five highest-scoring rows on the
dashboard were exactly those -- stale internships outranking the genuine APPLY
results below them -- and reaching those twenty-odd rows with --limit would
have paid to re-evaluate 289 records that had just been done.
"""
import json

import pytest
import rescore_history as rh


def _hist(tmp_path, rows):
    """rows: (evaluated_at, decision, score)"""
    d = tmp_path / "history"
    d.mkdir()
    (d / "evaluations_20260820.json").write_text(json.dumps([
        {"evaluated_at": at, "decision": dec, "score": sc,
         "job": {"company": "C", "title": f"T{i}", "description": "x" * 400}}
        for i, (at, dec, sc) in enumerate(rows)
    ]), encoding="utf-8")
    return d


@pytest.fixture
def selected(monkeypatch, tmp_path):
    """Runs full_pass as a dry run and returns the records it would re-score."""
    def run(rows, **kwargs):
        d = _hist(tmp_path, rows)
        monkeypatch.setattr(rh, "iter_files",
                            lambda: [str(p) for p in sorted(d.glob("*.json"))])
        import job_evaluator
        monkeypatch.setattr(job_evaluator, "PROFILE_IS_FALLBACK", False)
        captured = {}
        real = rh.load_json

        def spy(path, default=None):
            data = real(path, default=default)
            captured["data"] = data
            return data
        monkeypatch.setattr(rh, "load_json", spy)
        rh.full_pass(apply_changes=False, **kwargs)
        return captured
    return run


ROWS = [
    ("2026-08-18T10:00:00", "APPLY", 88),
    ("2026-08-20T10:00:00", "REVIEW", 74),
    ("2026-08-19T10:00:00", "SKIP", 30),
    ("2026-09-10T10:00:00", "APPLY", 82),
]


class TestBefore:
    def test_only_records_older_than_the_date_are_selected(self, selected, capsys):
        selected(ROWS, limit=30, before="2026-08-23")
        out = capsys.readouterr().out
        # three records predate the cut, one does not
        assert "Full re-score: 3 of 3" in out

    def test_the_date_comes_from_the_record_not_the_filename(self, selected, capsys):
        """A record can be re-evaluated days after the posting arrived; the
        filename would then select the wrong ones."""
        selected([("2026-09-10T10:00:00", "APPLY", 82)], limit=30,
                 before="2026-08-23")
        # the file is named ...20260820 but the record is from September
        assert "Full re-score: 0 of 0" in capsys.readouterr().out


class TestDecision:
    def test_skip_records_are_left_alone(self, selected, capsys):
        selected(ROWS, limit=30, decisions=["APPLY", "REVIEW"])
        assert "Full re-score: 3 of 3" in capsys.readouterr().out

    def test_matching_is_case_insensitive(self, selected, capsys):
        selected(ROWS, limit=30, decisions=["apply"])
        assert "Full re-score: 2 of 2" in capsys.readouterr().out


class TestCombined:
    def test_both_filters_compose(self, selected, capsys):
        """The actual 2026-09-14 invocation: old AND still near the top."""
        selected(ROWS, limit=30, before="2026-08-23",
                 decisions=["APPLY", "REVIEW"])
        assert "Full re-score: 2 of 2" in capsys.readouterr().out

    def test_no_filters_keeps_the_old_behaviour(self, selected, capsys):
        selected(ROWS, limit=30)
        assert "Full re-score: 4 of 4" in capsys.readouterr().out
