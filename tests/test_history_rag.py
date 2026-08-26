"""history_rag: sparse retrieval, grounding rail, and prompt construction.

The retriever is BM25 in pure Python (Moonshot has no embeddings endpoint,
verified 2026-08-26); the grounding rail mirrors the evaluator's
no-fake-scores rule: below the evidence floor the answer is a refusal,
never an invention. LLM mocked everywhere.
"""
import json

import history_rag as rag


def _write_history(tmp_path, records, name="evaluations_20990101.json"):
    d = tmp_path / "data" / "history"
    d.mkdir(parents=True)
    (d / name).write_text(json.dumps(records), encoding="utf-8")
    return str(d)


def _rec(company, title, score, decision, rationale=""):
    return {"score": score, "decision": decision, "job": {
        "company": company, "title": title, "location": "Zurich",
        "url": "https://x/1"}, "agent_rationale": rationale,
        "evaluated_at": "2026-08-20T05:00:00+00:00"}


class TestTokenize:
    def test_stopwords_punctuation_and_plural(self):
        assert rag.tokenize("The AI Engineers, und der Data-Science!") == \
            ["ai", "engineer", "data", "science"]

    def test_empty(self):
        assert rag.tokenize(None) == []


class TestBM25:
    def test_ranks_the_relevant_record_first(self, tmp_path):
        hist = _write_history(tmp_path, [
            _rec("Avaloq", "AI Software Engineer", 58, "SKIP",
                 "demands five years full-stack and a B.Sc."),
            _rec("Bakery AG", "Baker", 20, "SKIP", "bread and pastries"),
        ])
        hits = rag.retrieve("machine learning engineer skills", k=2,
                            history_dir=hist)
        assert hits[0][1]["meta"]["company"] == "Avaloq"

    def test_no_overlap_returns_empty(self, tmp_path):
        hist = _write_history(tmp_path, [_rec("Bakery AG", "Baker", 20, "SKIP")])
        assert rag.retrieve("quantum chromodynamics", history_dir=hist) == []


class TestAsk:
    def test_below_the_floor_is_a_refusal_not_an_invention(self, tmp_path, monkeypatch):
        hist = _write_history(tmp_path, [_rec("Bakery AG", "Baker", 20, "SKIP")])
        monkeypatch.setattr(rag, "call_kimi", lambda *a, **k: "machine learning")
        out = rag.ask("why were quantum computing roles skipped?",
                      history_dir=hist)
        assert out["answer"] is None
        assert out["sources"] == []

    def test_answer_is_grounded_in_numbered_sources(self, tmp_path, monkeypatch):
        hist = _write_history(tmp_path, [
            _rec("Avaloq", "AI Software Engineer", 58, "SKIP",
                 "demands 5y full-stack, 3y applied ML, B.Sc."),
            _rec("Bakery AG", "Baker", 20, "SKIP", "bread"),
        ])
        # Tiny corpus -> tiny idf -> tiny scores; the production floor is
        # calibrated on the real ~300-record corpus.
        monkeypatch.setattr(rag, "MIN_RETRIEVAL_SCORE", 0.5)
        seen = {}

        def fake_call(prompt, system=None, max_tokens=4096, **kw):
            if system is None:            # the expansion call
                return "machine learning"
            seen["prompt"] = prompt
            seen["system"] = system
            return "Pela fonte [1], foi SKIP por exigir 5 anos de full-stack."

        monkeypatch.setattr(rag, "call_kimi", fake_call)
        out = rag.ask("por que a Avaloq foi skip?", history_dir=hist)

        assert out["answer"].startswith("Pela fonte [1]")
        assert out["sources"][0]["company"] == "Avaloq"
        assert "[1]" in seen["prompt"] and "Avaloq" in seen["prompt"]
        assert "Use ONLY" in seen["system"]

    def test_expansion_failure_falls_back_to_the_raw_question(self, tmp_path, monkeypatch):
        hist = _write_history(tmp_path, [
            _rec("Avaloq", "AI Software Engineer", 58, "SKIP", "ml demands"),
        ])
        def boom(*a, **k):
            if len(a) == 1:
                raise RuntimeError("api down")
            return "ok"
        monkeypatch.setattr(rag, "call_kimi", boom)
        out = rag.ask("Avaloq skip reason", history_dir=hist, expand=True)
        assert out["expanded_query"] == "Avaloq skip reason"

    def test_llm_failure_does_not_crash(self, tmp_path, monkeypatch):
        hist = _write_history(tmp_path, [
            _rec("Avaloq", "AI Software Engineer", 58, "SKIP", "ml demands"),
        ])
        monkeypatch.setattr(rag, "MIN_RETRIEVAL_SCORE", 0.5)
        monkeypatch.setattr(rag, "call_kimi",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        out = rag.ask("Avaloq skip", history_dir=hist, expand=False)
        assert "LLM call failed" in out["answer"]
