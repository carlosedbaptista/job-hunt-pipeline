"""
test_digest_documents.py -- Pins how generated CV/CL reach the candidate.

First delivery attempt mailed one message per APPLY job with the PDFs
attached. It worked, and the candidate's verdict on 2026-08-23 was that he
would rather not get the files pushed at him in a separate thread: he wanted
a line in the digest he already reads, telling him documents are waiting.

So the daily batch no longer mails per job. doc_generator writes
digests/generated_docs_latest.json and the digest e-mail announces and
carries whatever is in it. agents/add_job.py still mails directly, because
it runs alone with no digest to ride on.

Two failure modes this pins down:

  * the manifest is a COMMITTED file, so on a run where doc generation is
    skipped (the step is continue-on-error) a stale manifest would announce
    yesterday's documents and attach paths that no longer exist;
  * announcing a file that is not there promises an attachment that never
    arrives.
"""
import json
import os

import pytest

import email_notifier as notifier


def _write_manifest(tmp_path, monkeypatch, documents, generated_at):
    path = tmp_path / "generated_docs_latest.json"
    path.write_text(json.dumps({"generated_at": generated_at,
                                "documents": documents}), encoding="utf-8")
    monkeypatch.setattr(notifier, "DOCS_MANIFEST", str(path))
    return path


@pytest.fixture
def pdf(tmp_path):
    f = tmp_path / "CV_Acme.pdf"
    f.write_bytes(b"%PDF-1.4")
    return str(f)


def _now():
    from datetime import datetime
    return datetime.now().isoformat()


def _long_ago():
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=48)).isoformat()


# ─── 1. Freshness ────────────────────────────────────────────────────────────

class TestFreshness:
    def test_todays_manifest_is_used(self, tmp_path, monkeypatch, pdf):
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "AI Engineer", "company": "Acme",
                          "score": 82, "files": [pdf]}], _now())
        assert len(notifier.load_generated_docs()) == 1

    def test_yesterdays_manifest_is_ignored(self, tmp_path, monkeypatch, pdf):
        """The step is continue-on-error; a skipped run must not re-announce."""
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "AI Engineer", "company": "Acme",
                          "score": 82, "files": [pdf]}], _long_ago())
        assert notifier.load_generated_docs() == []

    def test_missing_manifest_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(notifier, "DOCS_MANIFEST", str(tmp_path / "nope.json"))
        assert notifier.load_generated_docs() == []

    def test_entry_whose_files_vanished_is_dropped(self, tmp_path, monkeypatch):
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "AI Engineer", "company": "Acme", "score": 82,
                          "files": [str(tmp_path / "gone.pdf")]}], _now())
        assert notifier.load_generated_docs() == []


# ─── 2. What the digest says ─────────────────────────────────────────────────

class TestDigestSection:
    DIGEST = {"generated_at": "2026-08-23T08:00:00", "total_evaluated": 3,
              "top_jobs": [{"job": {"title": "T", "company": "C", "location": "L"},
                            "score": 82, "decision": "APPLY"}]}

    def test_section_appears_when_documents_exist(self, tmp_path, monkeypatch, pdf):
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "AI Engineer", "company": "Acme",
                          "score": 82, "files": [pdf]}], _now())
        out = notifier.format_digest_as_html(dict(self.DIGEST))
        assert "Application materials ready" in out
        assert "AI Engineer" in out
        assert "attached to this e-mail" in out

    def test_no_section_when_nothing_was_generated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(notifier, "DOCS_MANIFEST", str(tmp_path / "nope.json"))
        out = notifier.format_digest_as_html(dict(self.DIGEST))
        assert "Application materials ready" not in out

    def test_a_link_replaces_the_attachment_wording(self, tmp_path, monkeypatch, pdf):
        """Once Drive works the manifest carries a link and nothing is attached."""
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "AI Engineer", "company": "Acme", "score": 82,
                          "files": [pdf], "link": "https://drive.google.com/x"}], _now())
        out = notifier.format_digest_as_html(dict(self.DIGEST))
        assert "Download CV and cover letter" in out
        assert "attached to this e-mail" not in out

    def test_company_is_escaped(self, tmp_path, monkeypatch, pdf):
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "<script>x</script>", "company": "Acme",
                          "score": 82, "files": [pdf]}], _now())
        out = notifier.format_digest_as_html(dict(self.DIGEST))
        assert "<script>x</script>" not in out
        assert "&lt;script&gt;" in out

    def test_a_javascript_link_is_not_rendered(self, tmp_path, monkeypatch, pdf):
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "AI Engineer", "company": "Acme", "score": 82,
                          "files": [pdf], "link": "javascript:alert(1)"}], _now())
        assert "javascript:" not in notifier.format_digest_as_html(dict(self.DIGEST))


class TestDeliveredFormats:
    """What reaches the inbox, as opposed to what was generated.

    The candidate asked on 2026-08-24 to receive .docx rather than PDF: the
    file he opens is the one he needs to correct, and the system will not
    always be right. Both formats are still generated and both still go to
    Drive -- the PDF is the copy an employer receives, and it stays one click
    away.
    """

    DIGEST = {"generated_at": "2026-08-24T08:00:00", "total_evaluated": 1,
              "top_jobs": [{"job": {"title": "T", "company": "C", "location": "L"},
                            "score": 92, "decision": "APPLY"}]}

    @pytest.fixture
    def both_formats(self, tmp_path, monkeypatch):
        files = []
        for name in ("CV_Acme.pdf", "CV_Acme.docx", "CL_Acme.pdf", "CL_Acme.docx"):
            f = tmp_path / name
            f.write_bytes(b"x")
            files.append(str(f))
        _write_manifest(tmp_path, monkeypatch,
                        [{"title": "AI Engineer", "company": "Acme",
                          "score": 92, "files": files}], _now())
        return files

    def test_only_the_editable_copies_are_attached(self, both_formats, monkeypatch):
        monkeypatch.setattr(notifier, "DELIVER_FORMATS", (".docx",))
        docs = notifier.load_generated_docs()
        attached = [f for d in docs if not d.get("link") for f in d["files"]
                    if f.lower().endswith(notifier.DELIVER_FORMATS)]
        assert len(attached) == 2
        assert all(f.endswith(".docx") for f in attached)

    def test_the_manifest_still_lists_everything(self, both_formats):
        """Drive gets all four; only the delivery is narrowed."""
        assert len(notifier.load_generated_docs()[0]["files"]) == 4

    def test_the_setting_can_ask_for_both(self, both_formats, monkeypatch):
        monkeypatch.setattr(notifier, "DELIVER_FORMATS", (".pdf", ".docx"))
        docs = notifier.load_generated_docs()
        attached = [f for d in docs if not d.get("link") for f in d["files"]
                    if f.lower().endswith(notifier.DELIVER_FORMATS)]
        assert len(attached) == 4
