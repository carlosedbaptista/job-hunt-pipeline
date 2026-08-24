"""
test_apply_gate_override.py -- Pins who the APPLY gate is allowed to stop.

generate_docs_for_job() only produces a CV and cover letter for a job whose
EFFECTIVE decision is APPLY. That gate is load-bearing: it is what stops the
unattended run from writing an application off a 500-character teaser, or off
a job with a hard eligibility blocker whose score stayed high.

But it was also stopping the candidate. He read the comparis.ch internship --
72/REVIEW, full 2,880-character posting, no blockers -- decided it was worth
applying to, and the generator answered None. CLAUDE.md business rule 4 says
the opposite: "scoring is input, not gospel: the user can override any
decision".

So the gate keeps its job and loses the part that was never its job:

  * automatic generation (the daily pipeline, add_job) still requires APPLY;
  * force=True, which only a human asks for, generates anyway.

Nothing is sent either way -- the documents go to the candidate, so the
"never submit without approval" rule is untouched.
"""
import doc_generator as dg


class StubClient:
    """Records that it was reached. No network, no key."""

    def __init__(self):
        self.calls = 0

    def chat(self, *a, **kw):
        self.calls += 1
        return "Generated text."


def evaluation(score, **extra):
    ev = {"score": score, "decision": "APPLY" if score >= 80 else "REVIEW",
          "job": {"title": "ML Internship", "company": "Comparis",
                  "location": "Zurich", "description": "x" * 2880}}
    ev.update(extra)
    return ev


class TestTheGateStillGuardsAutomation:
    def test_a_review_job_generates_nothing_by_itself(self, tmp_path):
        client = StubClient()
        assert dg.generate_docs_for_job(
            client, {}, evaluation(72), str(tmp_path), mail=False) is None
        assert client.calls == 0, "not one paid call before the gate"

    def test_a_high_score_with_a_hard_blocker_is_still_refused(self, tmp_path):
        """The score stays visible for information; the decision is capped."""
        client = StubClient()
        ev = evaluation(92, hard_blockers=["Native German required"])
        assert dg.generate_docs_for_job(
            client, {}, ev, str(tmp_path), mail=False) is None
        assert client.calls == 0

    def test_a_high_score_on_a_teaser_is_still_refused(self, tmp_path):
        """insufficient_info caps APPLY at REVIEW: no CV off 500 characters."""
        client = StubClient()
        ev = evaluation(88, insufficient_info=True)
        assert dg.generate_docs_for_job(
            client, {}, ev, str(tmp_path), mail=False) is None
        assert client.calls == 0

    def test_force_defaults_to_off(self):
        """Automatic callers must not have to remember to pass force=False."""
        import inspect
        assert inspect.signature(
            dg.generate_docs_for_job).parameters["force"].default is False


class TestTheGateNeverStopsTheCandidate:
    def test_force_generates_for_a_review_job(self, tmp_path):
        client = StubClient()
        out = dg.generate_docs_for_job(
            client, PROFILE, evaluation(72), str(tmp_path), mail=False, force=True)
        assert out is not None
        assert client.calls == 2, "one summary, one letter"

    def test_force_generates_even_over_a_hard_blocker(self, tmp_path):
        """His call, not the system's. He may know the requirement is soft."""
        ev = evaluation(92, hard_blockers=["Native German required"])
        assert dg.generate_docs_for_job(
            StubClient(), PROFILE, ev, str(tmp_path), mail=False, force=True) is not None


PROFILE = {
    "name": "Test Candidate",
    "role": "AI Software Engineer Intern",
    "location": "Zurich",
    "address": "8000 Zurich",
    "phone": "+41 00 000 00 00",
    "email": "test@example.com",
    "linkedin": "linkedin.com/in/test",
    "permit": "B",
    "notice_period": "2 weeks",
    "languages": "PT native, EN C1, DE A2",
    "hobbies": "",
    "skills": {"technical_default": ["Python", "SQL"],
               "communication": ["Writing"], "certifications": ["Cert"]},
    "experience": [{"title": "AI Software Engineer Intern", "company": "netzdenker",
                    "period": "2026", "bullets": ["Did a thing"]}],
    "education": [{"degree": "BSc", "institution": "Uni", "period": "2024"}],
}
