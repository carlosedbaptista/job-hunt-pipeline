"""
test_add_job_inputs.py -- Pins which input wins in the manual add-job path.

Found by running the live workflow on 2026-08-23. The Actions form offers
"Job URL (optional if you paste the description)" and "Full job description
text (most reliable -- paste it here)", so filling in both is the natural
thing to do: paste the posting, keep the link for reference. It failed the
entire run.

add_job.main() checked `if args.url:` first and tried to scrape, ignoring the
text that was right there. Adzuna answers 403 to a GitHub runner, so the
scrape raised, and in non-interactive mode the fallback is sys.exit(1):

    Could not extract the job from the link (403 Client Error: Forbidden ...)
    ##[error]Process completed with exit code 1

The pasted text is the reliable input by construction -- a human read the
posting and copied it -- so it wins, and the URL is kept as metadata.
"""
import sys

import pytest

import add_job


@pytest.fixture
def no_scraping(monkeypatch):
    """Any attempt to reach the network is a failure of the test's premise."""
    def explode(url):
        raise AssertionError(f"add_job tried to scrape {url} instead of using the pasted text")

    monkeypatch.setattr(add_job, "fetch_job_from_url", explode)


@pytest.fixture
def captured_job(monkeypatch):
    """Stops after the job dict is built: the LLM call is not under test."""
    seen = {}

    def fake_evaluate(job):
        seen.update(job)
        raise SystemExit(0)

    monkeypatch.setattr(add_job, "evaluate_job", fake_evaluate)
    return seen


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["add_job.py", *argv])
    with pytest.raises(SystemExit) as exc:
        add_job.main()
    return exc.value.code


class TestTextBeatsUrl:
    def test_text_and_url_together_uses_the_text(self, monkeypatch, no_scraping, captured_job):
        code = _run(monkeypatch, "--text", "A long posting body.",
                    "--url", "https://www.adzuna.ch/details/5851075269",
                    "--title", "AI Software Engineer", "--company", "Avaloq")
        assert code == 0
        assert captured_job["description"] == "A long posting body."
        assert captured_job["title"] == "AI Software Engineer"

    def test_the_url_is_still_recorded(self, monkeypatch, no_scraping, captured_job):
        """It is how the job is reached later -- keep it, just don't fetch it."""
        _run(monkeypatch, "--text", "body", "--url", "https://example.com/job/1")
        assert captured_job["url"] == "https://example.com/job/1"

    def test_file_and_url_together_uses_the_file(self, monkeypatch, no_scraping,
                                                 captured_job, tmp_path):
        f = tmp_path / "job.txt"
        f.write_text("Posting from a file.", encoding="utf-8")
        _run(monkeypatch, "--file", str(f), "--url", "https://example.com/job/2")
        assert captured_job["description"] == "Posting from a file."

    def test_whitespace_only_text_does_not_count_as_pasted(self, monkeypatch, captured_job):
        """An empty box in the form must fall through to the URL, not score
        an empty posting."""
        called = {}

        def fake_fetch(url):
            called["url"] = url
            return {"title": "T", "company": "C", "location": "L",
                    "description": "scraped body", "url": url, "portal": "manual"}

        monkeypatch.setattr(add_job, "fetch_job_from_url", fake_fetch)
        _run(monkeypatch, "--text", "   \n  ", "--url", "https://example.com/job/3")
        assert called["url"] == "https://example.com/job/3"
        assert captured_job["description"] == "scraped body"


class TestUrlOnly:
    def test_url_alone_still_scrapes(self, monkeypatch, captured_job):
        monkeypatch.setattr(add_job, "fetch_job_from_url", lambda url: {
            "title": "T", "company": "C", "location": "L",
            "description": "scraped", "url": url, "portal": "manual"})
        _run(monkeypatch, "--url", "https://example.com/job/4")
        assert captured_job["description"] == "scraped"
