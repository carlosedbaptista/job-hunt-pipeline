"""
test_pdf_text.py -- Pins the characters that reach the PDF.

fpdf2's core fonts are Latin-1 only, so anything outside it has to be
substituted or dropped. _safe_text did both, in the wrong order:

    text = text.encode("latin-1", "ignore").decode("latin-1")   # drops
    text = text.replace("\\u2014", "-")                          # too late

`ignore` DELETES what it cannot map, so by the time the replacements ran the
character was already gone, and they were dead code.

This was not theoretical. The cover letter generated for BLP Digital on
2026-08-23 and uploaded to Drive contained six holes where the model had
written em dashes:

    "I construct automation pipelines with LLM APIs  Claude, Kimi  and ship"
    "German at A2  actively studying toward B1"

That document goes to an employer. Substitute first, drop second.
"""
import pytest

from doc_generator import _safe_text


class TestSubstitution:
    @pytest.mark.parametrize("char,expected", [
        ("—", "-"),      # em dash -- the one that shipped broken
        ("–", "-"),      # en dash, as in "90-100%"
        ("−", "-"),      # minus sign
        ("’", "'"),      # curly apostrophe, in every "you'll"
        ("“", '"'),
        ("”", '"'),
        ("…", "..."),
        ("•", "-"),      # bullet, common in pasted postings
        (" ", " "),      # non-breaking space
    ])
    def test_each_character_becomes_something(self, char, expected):
        assert _safe_text(f"a{char}b") == f"a{expected}b"

    def test_the_exact_sentence_that_shipped_broken(self):
        out = _safe_text("LLM APIs — Claude, Kimi — and ship them")
        assert out == "LLM APIs - Claude, Kimi - and ship them"
        assert "  " not in out

    def test_no_silent_holes_are_left(self):
        """A gap mid-sentence is worse than a wrong character: it reads as
        carelessness to whoever opens the PDF."""
        assert "  " not in _safe_text("A — B – C … D • E")


class TestDropping:
    def test_emoji_are_still_removed(self):
        """They cannot be rendered at all; dropping them is correct."""
        assert _safe_text("ok \U0001F600") == "ok "

    def test_accents_survive(self):
        """Latin-1 covers them, and they appear in real company names."""
        assert _safe_text("Zürich café") == "Zürich café"

    def test_empty_and_none_are_safe(self):
        assert _safe_text("") == ""
        assert _safe_text(None) == ""
