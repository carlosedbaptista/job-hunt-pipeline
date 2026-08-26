"""
history_rag.py -- ask the committed evaluation history questions, grounded.

A teaching-sized RAG over data/history/evaluations_*.json: retrieve the
records most relevant to the question, hand them to the model as numbered
sources, and answer ONLY from them.

Retrieval is BM25 (sparse, keyword-based) in pure Python -- zero new
dependencies. Why not embeddings? Verified 2026-08-26 via /v1/models: the
Moonshot API has NO embeddings endpoint, and this repo stays Kimi-only with
no heavy deps. The retriever is deliberately behind one function
(retrieve()) so a dense upgrade (embeddings + cosine) is a swap, not a
rewrite -- the grounding rail below does not care which retriever ran.

The grounding rail is the same philosophy as the evaluator's no-fake-scores
rule: below MIN_RETRIEVAL_SCORE the command refuses to answer ("sem
evidencia suficiente") instead of letting the model invent one. Every
answer cites its sources, and the sources are printed.
"""
import json
import math
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from kimi_client import call_kimi

HISTORY_DIR = "data/history"

# BM25 standard parameters (Robertson & Zaragoza 2009).
BM25_K1 = 1.5
BM25_B = 0.75
# Below this, retrieval found nothing worth grounding on: refuse, never
# invent. Calibrated 2026-08-26 on the real corpus (~300 records): relevant
# queries score 3.7-10.8 at top-1; nonsense returns no hits at all. Tests
# with tiny corpora monkeypatch the floor down.
MIN_RETRIEVAL_SCORE = 2.0

_STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "de", "do", "da", "dos", "das", "em",
    "no", "na", "e", "ou", "que", "para", "por", "com", "the", "an", "and",
    "or", "of", "to", "in", "is", "are", "was", "were", "for", "with", "on",
    "at", "by", "und", "der", "die", "das", "mit", "für", "als", "en",
}


def tokenize(text):
    """Lowercase word tokens, punctuation and stopwords removed, a light
    trailing-s strip so 'engineers' meets 'engineer'. Deliberately simple:
    retrieval you can read beats retrieval you have to trust."""
    words = re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower()).split()
    out = []
    for w in words:
        if w in _STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out


def load_records(history_dir=HISTORY_DIR):
    """One retrievable document per evaluation record:
    {id, text, meta{company,title,score,decision,evaluated_at,url}}."""
    import glob
    docs = []
    for path in sorted(glob.glob(os.path.join(history_dir, "evaluations_*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                records = json.load(f)
        except (ValueError, OSError):
            continue
        if not isinstance(records, list):
            continue
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                continue
            job = rec.get("job", {})
            rationale = (rec.get("agent_rationale") or rec.get("technical_fit")
                         or " ".join(rec.get("key_match_points") or []))
            red_flags = " ".join(str(x) for x in (rec.get("red_flags") or []))
            text = " ".join(str(x) for x in (
                job.get("title", ""), job.get("company", ""),
                job.get("location", ""), rec.get("decision", ""),
                rec.get("score", ""), rationale, red_flags) if x)
            if len(text.strip()) < 20:
                continue
            docs.append({
                "id": f"{os.path.basename(path)}#{i}",
                "text": text,
                "meta": {
                    "company": job.get("company", ""),
                    "title": job.get("title", ""),
                    "score": rec.get("score"),
                    "decision": rec.get("decision"),
                    "evaluated_at": rec.get("evaluated_at", ""),
                    "url": job.get("url", ""),
                },
            })
    return docs


class BM25:
    """Okapi BM25 over a small corpus: exact, readable, dependency-free."""

    def __init__(self, docs):
        self.docs = docs
        self.doc_tokens = [tokenize(d["text"]) for d in docs]
        self.doc_len = [len(t) or 1 for t in self.doc_tokens]
        self.avgdl = sum(self.doc_len) / max(len(self.doc_len), 1)
        df = Counter()
        for tokens in self.doc_tokens:
            for term in set(tokens):
                df[term] += 1
        n = max(len(docs), 1)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5))
                    for t, f in df.items()}

    def search(self, query, k=5):
        q_tokens = tokenize(query)
        scored = []
        for i, tokens in enumerate(self.doc_tokens):
            tf = Counter(tokens)
            score = 0.0
            for term in q_tokens:
                if term not in self.idf:
                    continue
                f = tf.get(term, 0)
                if not f:
                    continue
                score += (self.idf[term] * f * (BM25_K1 + 1)
                          / (f + BM25_K1 * (1 - BM25_B + BM25_B
                                            * self.doc_len[i] / self.avgdl)))
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        return [(score, self.docs[i]) for score, i in scored[:k]]


def retrieve(question, k=5, history_dir=HISTORY_DIR):
    """The one function a dense (embedding) retriever would replace."""
    return BM25(load_records(history_dir)).search(question, k=k)


def expand_query(question):
    """One cheap call: keywords + synonyms for the sparse retriever
    ('ML' -> 'machine learning', 'werkstudent' -> 'working student')."""
    prompt = (
        "Turn this search question into ONE LINE of keyword search terms for a "
        "keyword (BM25) engine over job-evaluation records. Include the obvious "
        "synonyms and expansions (ML -> machine learning, internship/working "
        "student/werkstudent/praktikum). Output ONLY the keyword line, no prose.\n\n"
        f"Question: {question}")
    try:
        line = call_kimi(prompt, max_tokens=80)
        return str(line).strip().splitlines()[0] if line else question
    except Exception:
        # Expansion is a bonus, never a failure mode: the raw question works.
        return question


def ask(question, k=5, history_dir=HISTORY_DIR, expand=True):
    """Retrieve -> ground -> answer only from sources. Returns
    {'answer': str|None, 'sources': [...], 'expanded_query': str}."""
    expanded = expand_query(question) if expand else question
    hits = retrieve(f"{question} {expanded}", k=k, history_dir=history_dir)
    if not hits or hits[0][0] < MIN_RETRIEVAL_SCORE:
        return {"answer": None, "sources": [], "expanded_query": expanded}

    sources = []
    blocks = []
    for rank, (score, doc) in enumerate(hits, start=1):
        meta = doc["meta"]
        sources.append({"rank": rank, "retrieval_score": round(score, 2), **meta})
        blocks.append(f"[{rank}] {meta['title']} @ {meta['company']} "
                      f"(score {meta['score']}, {meta['decision']}, "
                      f"{str(meta['evaluated_at'])[:10]})\n{doc['text'][:1200]}")
    system = (
        "You answer questions about a job-hunt evaluation history. Use ONLY "
        "the numbered sources below -- if they do not contain the answer, say "
        "so instead of inventing. Cite sources inline as [1], [2]. Answer in "
        "the language of the question. Be direct: 1 short paragraph plus "
        "bullets if useful.")
    prompt = "SOURCES:\n" + "\n\n".join(blocks) + f"\n\nQUESTION: {question}"
    try:
        answer = call_kimi(prompt, system=system, max_tokens=600)
    except Exception as e:
        answer = f"(LLM call failed: {type(e).__name__}: {e})"
    return {"answer": answer, "sources": sources, "expanded_query": expanded}


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="rebuild stats over the history")
    p_ask = sub.add_parser("ask", help="ask the history a question")
    p_ask.add_argument("question")
    p_ask.add_argument("-k", type=int, default=5)
    p_ask.add_argument("--no-expand", action="store_true")
    args = ap.parse_args()

    if args.cmd == "index":
        docs = load_records()
        bm = BM25(docs)
        print(f"{len(docs)} records indexed, {len(bm.idf)} distinct terms")
        return

    result = ask(args.question, k=args.k, expand=not args.no_expand)
    print(f"(expanded query: {result['expanded_query']})\n")
    if result["answer"] is None:
        print("SEM EVIDENCIA SUFICIENTE -- o historico nao tem base para "
              "responder isso. (Recusar e' a cerca: nunca inventar.)")
        return
    print(result["answer"])
    print("\n--- fontes ---")
    for s in result["sources"]:
        print(f"[{s['rank']}] {s['title']} @ {s['company']} "
              f"(score {s['score']}, {s['decision']}, "
              f"{str(s['evaluated_at'])[:10]}, bm25={s['retrieval_score']})")


if __name__ == "__main__":
    main()
