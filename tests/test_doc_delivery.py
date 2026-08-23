"""
test_doc_delivery.py -- Pins how a generated CV/CL reaches the candidate.

Context (verified on 2026-08-23, on the first run after the ingestion-quality
merge): the tailored documents were being generated on the runner and then
lost. The repo is public, so they can be neither committed nor uploaded as an
Actions artifact, and the Google Drive path answers

    403 "Service Accounts do not have storage quota"

for every upload while GDRIVE_REFRESH_TOKEN_B64 is unset. Mail to
GMAIL_RECIPIENT is the durable copy that leaks nothing.

Two properties matter and both are easy to break by accident:

  * the PDFs must actually be attached, and the container must be
    multipart/mixed -- "alternative" says "the same content in another
    format", and clients are entitled to hide the body or drop the parts;
  * the recipient is always the candidate. CLAUDE.md's first business rule is
    that nothing reaches an employer without explicit approval, so a
    regression that mailed a recruiter would be the worst kind.

No SMTP connection is opened: smtplib.SMTP is replaced by a recorder.
"""
import os

import pytest

import doc_generator
import email_notifier


class FakeSMTP:
    """Records what would have been sent instead of connecting to Gmail."""

    sent = []

    def __init__(self, host, port):
        self.host, self.port = host, port

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def sendmail(self, sender, recipient, raw):
        FakeSMTP.sent.append({"sender": sender, "recipient": recipient, "raw": raw})

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(email_notifier.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


@pytest.fixture
def pdfs(tmp_path):
    cv = tmp_path / "CV_Acme_AI_Engineer.pdf"
    cl = tmp_path / "CL_Acme_AI_Engineer.pdf"
    cv.write_bytes(b"%PDF-1.4 cv bytes")
    cl.write_bytes(b"%PDF-1.4 cl bytes")
    return [str(cv), str(cl)]


# ─── 1. send_email carries the files ─────────────────────────────────────────

class TestAttachments:
    def test_attachments_are_present_and_named(self, smtp, pdfs):
        assert email_notifier.send_email(
            "me@example.com", "subject", "<p>body</p>", "me@example.com", "pw",
            attachments=pdfs,
        )
        raw = smtp.sent[0]["raw"]
        assert "CV_Acme_AI_Engineer.pdf" in raw
        assert "CL_Acme_AI_Engineer.pdf" in raw
        assert raw.count("Content-Disposition: attachment") == 2

    def test_container_is_mixed_when_attaching(self, smtp, pdfs):
        email_notifier.send_email("me@example.com", "s", "<p>b</p>", "me@example.com", "pw",
                                  attachments=pdfs)
        assert "multipart/mixed" in smtp.sent[0]["raw"]

    def test_plain_digest_email_is_unchanged(self, smtp):
        """The daily digest passes no attachments and must stay alternative."""
        email_notifier.send_email("me@example.com", "s", "<p>b</p>", "me@example.com", "pw")
        raw = smtp.sent[0]["raw"]
        assert "multipart/alternative" in raw
        assert "Content-Disposition: attachment" not in raw

    def test_missing_file_is_skipped_not_fatal(self, smtp, pdfs):
        """A half-written folder must not cost the candidate the other file."""
        assert email_notifier.send_email(
            "me@example.com", "s", "<p>b</p>", "me@example.com", "pw",
            attachments=pdfs[:1] + [os.path.join("nope", "gone.pdf")],
        )
        assert smtp.sent[0]["raw"].count("Content-Disposition: attachment") == 1


# ─── 2. doc_generator mails the candidate, and only the candidate ────────────

class TestRecipient:
    def test_goes_to_gmail_recipient(self, smtp, pdfs, monkeypatch):
        monkeypatch.setenv("GMAIL_SENDER", "bot@example.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
        monkeypatch.setenv("GMAIL_RECIPIENT", "candidate@example.com")
        assert doc_generator._email_docs_to_candidate(
            "folder", "AI Engineer", "Acme", 92, pdfs
        )
        assert smtp.sent[0]["recipient"] == "candidate@example.com"

    def test_nothing_sent_when_unconfigured(self, smtp, pdfs, monkeypatch):
        for var in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD", "GMAIL_RECIPIENT"):
            monkeypatch.delenv(var, raising=False)
        assert doc_generator._email_docs_to_candidate(
            "folder", "AI Engineer", "Acme", 92, pdfs
        ) is False
        assert smtp.sent == []

    def test_company_and_title_are_escaped(self, smtp, pdfs, monkeypatch):
        """Company names are scraped from third-party alerts; the body is HTML."""
        monkeypatch.setenv("GMAIL_SENDER", "bot@example.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
        monkeypatch.setenv("GMAIL_RECIPIENT", "candidate@example.com")
        doc_generator._email_docs_to_candidate(
            "folder", "<script>alert(1)</script>", "Acme & Co", 92, pdfs
        )
        raw = smtp.sent[0]["raw"]
        body = raw.split("Content-Type: text/html")[1]
        assert "<script>" not in body
        assert "&lt;script&gt;" in body

    def test_subject_cannot_inject_headers(self, smtp, pdfs, monkeypatch):
        """A newline in a scraped company name must not become a new header."""
        monkeypatch.setenv("GMAIL_SENDER", "bot@example.com")
        monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
        monkeypatch.setenv("GMAIL_RECIPIENT", "candidate@example.com")
        doc_generator._email_docs_to_candidate(
            "folder", "AI Engineer", "Acme\nBcc: recruiter@employer.com", 92, pdfs
        )
        raw = smtp.sent[0]["raw"]
        # Only the header block can be injected into: past the first blank
        # line the text is body content and a "Bcc:" there is inert.
        headers = raw.split("\n\n", 1)[0]
        assert not any(line.startswith("Bcc:") for line in headers.splitlines())
        # The newline was folded away, so the payload rides inside the Subject.
        assert "Subject: [Job Hunt] CV + cover letter: AI Engineer @ Acme Bcc:" in headers
