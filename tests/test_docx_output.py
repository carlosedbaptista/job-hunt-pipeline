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


class TestEmployerLine:
    """The CV's EXPERIENCE line used to carry two identical separators.

    The profile stores a company as "Name -- what it is", because
    job_evaluator splits on that to recover the bare name for the scoring
    prompt. The CV then rendered "{title} -- {company}", producing:

        AI Software Engineer Intern -- netzdenker -- Swiss-based digital
        agency, DACH market | 06.2026 - Present

    Two "--" on one line, structural and descriptive, indistinguishable. The
    descriptor is worth keeping -- netzdenker is not a name a recruiter
    recognises -- so what changes is the rendering, not the content.
    """

    def test_the_descriptor_becomes_a_parenthetical(self):
        assert dg._format_employer("netzdenker -- Swiss-based digital agency") == \
            "netzdenker (Swiss-based digital agency)"

    def test_a_company_without_a_descriptor_is_untouched(self):
        assert dg._format_employer("netzdenker") == "netzdenker"

    def test_a_comma_in_the_name_is_not_a_separator(self):
        """"Criminal Registry, High Court of Rio de Janeiro" is one name."""
        name = "Criminal Registry, High Court of Rio de Janeiro"
        assert dg._format_employer(name) == name

    def test_only_the_first_separator_splits(self):
        assert dg._format_employer("A -- b -- c") == "A (b -- c)"

    def test_empty_input_is_safe(self):
        assert dg._format_employer("") == ""
        assert dg._format_employer(None) == ""

    def test_the_evaluator_still_recovers_the_bare_name(self):
        """job_evaluator splits the SAME stored string on "--" for its
        prompt; changing the rendering must not change the storage."""
        stored = "netzdenker -- Swiss-based digital agency, DACH market"
        assert stored.split("--")[0].strip() == "netzdenker"


class TestProjectsSection:
    """The CV omitted the candidate's strongest evidence.

    config/candidate_profile.json has carried a `projects` entry since the
    beginning -- an unattended production pipeline he audited and corrected
    himself -- and only _generate_cover_letter ever read it. The CV rendered
    PROFILE SUMMARY, SKILLS, EXPERIENCE, EDUCATION, LANGUAGES and never
    PROJECTS, so the document that reaches a recruiter first said nothing
    about it.

    For someone moving into engineering from another field, that project is
    what the job titles cannot say.
    """

    WITH_PROJECT = {
        **PROFILE,
        "projects": [{
            "title": "Job-Matching Pipeline with LLM Scoring",
            "url": "github.com/carlosedbaptista/job-hunt-pipeline",
            "bullets": ["Runs unattended twice a day",
                        "Guardrails in code rather than trust in the model"],
        }],
    }

    @pytest.fixture
    def cv_with_project(self, tmp_path):
        path = tmp_path / "cv_proj.docx"
        dg.cv_docx(self.WITH_PROJECT, {"title": "AI Engineer"}, "summary", str(path))
        return _text(docx.Document(str(path)))

    def test_the_section_is_rendered(self, cv_with_project):
        assert "PROJECTS" in cv_with_project

    def test_the_title_and_link_are_there(self, cv_with_project):
        assert "Job-Matching Pipeline with LLM Scoring" in cv_with_project
        assert "github.com/carlosedbaptista/job-hunt-pipeline" in cv_with_project

    def test_the_bullets_survive(self, cv_with_project):
        assert "Runs unattended twice a day" in cv_with_project
        assert "Guardrails in code rather than trust in the model" in cv_with_project

    def test_it_sits_after_experience_not_before(self, cv_with_project):
        """His current role is the relevant technical one. Leading with a side
        project pushes the job down the page and reads as having none."""
        assert cv_with_project.index("EXPERIENCE") < cv_with_project.index("PROJECTS")
        assert cv_with_project.index("PROJECTS") < cv_with_project.index("EDUCATION")

    def test_a_profile_without_projects_renders_no_heading(self, tmp_path):
        """A heading with nothing under it reads as a mistake, same as HOBBIES."""
        path = tmp_path / "cv_none.docx"
        dg.cv_docx(PROFILE, {"title": "AI Engineer"}, "summary", str(path))
        assert "PROJECTS" not in _text(docx.Document(str(path)))
