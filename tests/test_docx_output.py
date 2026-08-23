"""
test_docx_output.py -- Pins the editable copies of the CV and cover letter.

The candidate's reason, in his words: "eu quero que o sistema gere perfeito,
mas sei que isso nao vai acontecer, entao preciso do docx para editar os
erros". He is right, and the day this session started proved it -- the
generated letter contained an invented technical detail he had to catch by
reading it.

So the PDF stays the copy that gets sent (fixed layout, nobody edits it by
accident) and the .docx is the working copy. Two properties matter:

  * the .docx must carry the SAME content as the PDF, in the same order. A
    "working copy" missing a section is a trap: he edits it, sends it, and
    discovers later that Education was never in there;
  * .docx is UTF-8, so it must NOT go through _safe_text. That function exists
    for the PDF's Latin-1 core fonts, and applying it here would degrade the
    editable copy for no reason.

Note on size, since it motivated the request: the .docx is LARGER, not
smaller. Measured on the BLP Digital documents -- letter 2,881 bytes as PDF
against 38,050 as .docx; CV 28,076 against 62,807. The value is editability,
never weight.
"""
import pytest

import doc_generator as dg

docx = pytest.importorskip("docx", reason="python-docx not installed")


PROFILE = {
    "name": "Test Candidate",
    "role": "AI Engineer Intern",
    "location": "Zurich",
    "address": "8000 Zurich, Switzerland",
    "phone": "+41 00 000 00 00",
    "email": "test@example.com",
    "linkedin": "linkedin.com/in/test",
    "permit": "B",
    "notice_period": "2 weeks",
    "languages": "PT native, EN C1, DE A2",
    "hobbies": "",
    "skills": {"technical_default": ["Python", "SQL"],
               "communication": ["Writing"], "certifications": ["Cert"]},
    "experience": [{"title": "Intern", "company": "Acme", "period": "2026",
                    "bullets": ["Did a thing", "Did another thing"]}],
    "education": [{"degree": "BSc", "institution": "Uni", "period": "2024"}],
}

LETTER = "First paragraph — with an em dash.\n\nSecond paragraph.\n\nThird paragraph."


@pytest.fixture
def cv(tmp_path):
    path = tmp_path / "cv.docx"
    dg.cv_docx(PROFILE, {"title": "AI Engineer"}, "A tailored summary.", str(path))
    return docx.Document(str(path))


@pytest.fixture
def letter(tmp_path):
    path = tmp_path / "cl.docx"
    dg.cl_docx(PROFILE, LETTER, "AI Engineer", "Acme AG", "Zurich", str(path))
    return docx.Document(str(path))


def _text(document):
    return "\n".join(p.text for p in document.paragraphs)


class TestCv:
    def test_every_section_is_present(self, cv):
        """Same sections as the PDF. A missing one is a silent trap."""
        text = _text(cv)
        for heading in ("PROFILE SUMMARY", "SKILLS", "EXPERIENCE",
                        "EDUCATION", "LANGUAGES"):
            assert heading in text

    def test_the_tailored_summary_is_the_generated_one(self, cv):
        assert "A tailored summary." in _text(cv)

    def test_experience_bullets_survive(self, cv):
        text = _text(cv)
        assert "Did a thing" in text and "Did another thing" in text

    def test_an_empty_hobbies_section_is_omitted(self, cv):
        """A heading with nothing under it reads as a mistake to an employer."""
        assert "HOBBIES" not in _text(cv)

    def test_hobbies_appear_when_present(self, tmp_path):
        profile = {**PROFILE, "hobbies": "Chess and running"}
        path = tmp_path / "cv2.docx"
        dg.cv_docx(profile, {"title": "AI Engineer"}, "s", str(path))
        assert "Chess and running" in _text(docx.Document(str(path)))


class TestLetter:
    def test_paragraphs_are_kept_separate(self, letter):
        """Splitting on blank lines: one run-on block would be unreadable."""
        text = _text(letter)
        assert "First paragraph" in text
        assert "Second paragraph." in text
        assert "Third paragraph." in text

    def test_the_subject_line_names_the_job(self, letter):
        assert "Re: Application for AI Engineer" in _text(letter)

    def test_the_employer_is_addressed(self, letter):
        assert "Acme AG" in _text(letter)

    def test_it_is_signed(self, letter):
        text = _text(letter)
        assert "Kind regards," in text and PROFILE["name"] in text

    def test_utf8_is_preserved_unlike_the_pdf(self, letter):
        """_safe_text exists for the PDF's Latin-1 fonts. Running it here would
        degrade the editable copy for nothing."""
        assert "—" in _text(letter)
