"""
test_decision_agent.py -- Pins the tool-using decision agent.

No HTTP, no secrets (tests.yml runs with none): a scripted FakeClient is
injected in place of KimiClient (same pattern as test_agent_runtime.py), the
tracker DB is redirected to tmp_path (test_feedback_loop.py), the mode/env
switches are monkeypatched, and main() runs inside tmp_path so digests/ and
data/history/ writes stay local to the test.
"""
import json
import os

import pytest

import decision_agent as da
import job_evaluator as je
import tracker_updater
from utils import effective_decision, is_truncated_description


# ─── scripted client + jobs ──────────────────────────────────────────────────

def _tool_call(name, arguments="", call_id="c1"):
    return {"content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": arguments}}],
            "usage": {}, "model": "fake"}


def _final(content="done"):
    return {"content": content, "tool_calls": [], "usage": {}, "model": "fake"}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat_completion(self, messages, max_tokens=1000, tools=None, tool_choice=None):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _record_decision_call(score=88, decision="APPLY",
                          rationale="Owns LLM workflows end to end -- his shape",
                          concerns=None, hard_blockers=None,
                          language_requirement="none", call_id="c9"):
    return _tool_call("record_decision", json.dumps({
        "score": score, "decision": decision, "rationale": rationale,
        "concerns": concerns or [], "hard_blockers": hard_blockers or [],
        "language_requirement": language_requirement}), call_id=call_id)


def _inject_clients(monkeypatch, *clients):
    """KimiClient() inside evaluate_job hands out the scripted clients, in
    order (one per job in main() runs)."""
    queue = list(clients)
    monkeypatch.setattr(da, "KimiClient", lambda *a, **k: queue.pop(0))
    return queue


# >=200 chars, ends with a period: a real, complete posting.
GOOD_DESC = ("Build LLM agent workflows and data pipelines in Python and SQL. "
             "English is our working language. ") * 6
# >=400 chars ending mid-sentence: a cut-off teaser (requirements invisible).
TRUNC_DESC = "Join our AI innovation lab and bring agentic solutions to production " * 7
# A hard C1-German clause the deterministic check must catch.
GERMAN_DESC = GOOD_DESC + ("Requirements: fluent written and spoken German (at least C1) "
                           "is required for client workshops.")


def _job(description=GOOD_DESC, **overrides):
    job = {"company": "ACME", "title": "AI Platform Engineer Intern",
           "location": "Zurich", "url": "https://x/1", "portal": "test",
           "description": description}
    job.update(overrides)
    return job


@pytest.fixture(autouse=True)
def _isolated_tracker_db(tmp_path, monkeypatch):
    """Outcome calibration (system prompt + tool) hits the tracker DB; keep
    every test off the real one."""
    monkeypatch.setattr(tracker_updater, "DB_PATH", str(tmp_path / "jobs.db"))


def _evaluator_record(monkeypatch, job, score=88):
    """A real job_evaluator record for the same posting (mocked LLM)."""
    monkeypatch.setattr(je, "call_kimi_json", lambda *a, **k: {
        "score": score, "technical_fit": "strong", "contextual_fit": "good",
        "salary_estimate": "Not disclosed", "culture_fit": "fine",
        "concerns": [], "hard_blockers": [], "language_requirement": "none",
        "decision": "APPLY"})
    return je.evaluate_job(job)


# ─── happy path ──────────────────────────────────────────────────────────────

class TestHappyPath:
    def test_full_investigation_produces_an_evaluator_shaped_record(self, monkeypatch):
        client = FakeClient([
            _tool_call("get_posting_text"),
            _tool_call("check_language_requirement", call_id="c2"),
            _record_decision_call(score=88, decision="APPLY"),
            _final()])
        _inject_clients(monkeypatch, client)

        rec = da.evaluate_job(_job())

        assert rec["score"] == 88
        assert rec["decision"] == "APPLY"  # derived by effective_decision, not the agent
        assert rec["recommendation"] == "APPLY"
        assert rec["materials_needed"] == ["cv"]
        assert rec["hard_blockers"] == []
        assert rec["insufficient_info"] is False
        # Agent provenance.
        assert rec["agent_decision"] == "APPLY"
        assert rec["agent_rationale"] == "Owns LLM workflows end to end -- his shape"
        assert [c["name"] for c in rec["agent_trace"]] == [
            "get_posting_text", "check_language_requirement", "record_decision"]

    def test_record_has_the_same_keys_as_an_evaluator_record(self, monkeypatch):
        eval_rec = _evaluator_record(monkeypatch, _job())
        client = FakeClient([_record_decision_call(score=88), _final()])
        _inject_clients(monkeypatch, client)

        agent_rec = da.evaluate_job(_job())

        missing = set(eval_rec.keys()) - set(agent_rec.keys())
        assert not missing, f"agent record is missing evaluator fields: {missing}"

    def test_a_numeric_string_score_is_accepted(self, monkeypatch):
        client = FakeClient([_record_decision_call(score="85"), _final()])
        _inject_clients(monkeypatch, client)
        rec = da.evaluate_job(_job())
        assert rec["score"] == 85
        assert rec["decision"] == "APPLY"


# ─── rails (the code decides, not the model) ─────────────────────────────────

class TestRails:
    def test_hard_language_requirement_locks_skip_despite_agent_apply(self,
                                                                      monkeypatch, capsys):
        """Agent proposes APPLY/95, but the deterministic check found a hard
        C1-German clause: the blocker is added in code and SKIP wins."""
        client = FakeClient([
            _tool_call("get_posting_text"),
            _tool_call("check_language_requirement", call_id="c2"),
            _record_decision_call(score=95, decision="APPLY",
                                  hard_blockers=[], language_requirement="none"),
            _final()])
        _inject_clients(monkeypatch, client)

        rec = da.evaluate_job(_job(GERMAN_DESC))

        assert je.detect_language_requirement_tier(GERMAN_DESC) == "hard"  # premise
        assert rec["decision"] == "SKIP"
        assert rec["score"] == 95           # the number stays visible...
        assert rec["agent_decision"] == "APPLY"  # ...and so does what the agent wanted
        assert len(rec["hard_blockers"]) == 1
        assert rec["materials_needed"] == []
        assert "agent proposed decision=APPLY" in capsys.readouterr().out

    def test_truncated_teaser_caps_at_review(self, monkeypatch):
        assert is_truncated_description(TRUNC_DESC)  # premise
        client = FakeClient([_record_decision_call(score=90, decision="APPLY"), _final()])
        _inject_clients(monkeypatch, client)

        rec = da.evaluate_job(_job(TRUNC_DESC))

        assert rec["insufficient_info"] is True
        assert rec["decision"] == "REVIEW"  # effective_decision cap
        assert rec["score"] == 90
        assert rec["agent_decision"] == "APPLY"
        assert rec["materials_needed"] == []

    def test_agent_that_never_records_a_decision_is_an_error(self, monkeypatch):
        client = FakeClient([_final("I cannot make up my mind")])
        _inject_clients(monkeypatch, client)

        rec = da.evaluate_job(_job())

        assert rec["decision"] == "ERROR"
        assert rec["score"] is None
        assert rec["materials_needed"] == []
        assert "record_decision" in rec["red_flags"][0]

    def test_iteration_cap_is_an_error_not_a_guess(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_ITERATIONS", "2")
        client = FakeClient([_tool_call("get_posting_text"),
                             _tool_call("get_posting_text", call_id="c2")])
        _inject_clients(monkeypatch, client)

        rec = da.evaluate_job(_job())

        assert rec["decision"] == "ERROR"
        assert rec["score"] is None
        assert "iteration cap" in rec["red_flags"][0]
        assert client.calls == 2

    def test_a_garbage_score_never_becomes_a_number(self, monkeypatch):
        client = FakeClient([_record_decision_call(score="high"), _final()])
        _inject_clients(monkeypatch, client)

        rec = da.evaluate_job(_job())

        assert rec["decision"] == "ERROR"
        assert rec["score"] is None
        assert "no usable score" in rec["red_flags"][0]

    def test_spurious_blockers_are_filtered(self, monkeypatch):
        client = FakeClient([_record_decision_call(
            score=88, hard_blockers=["None -- no German required"]), _final()])
        _inject_clients(monkeypatch, client)

        rec = da.evaluate_job(_job())

        assert rec["hard_blockers"] == []
        assert rec["decision"] == "APPLY"


# ─── no posting text: honest NOT_EVALUATED, no API call ──────────────────────

class TestNoPostingText:
    def test_a_bare_title_costs_no_api_call(self, monkeypatch):
        constructed = []
        monkeypatch.setattr(da, "KimiClient",
                            lambda *a, **k: constructed.append(1) or FakeClient([]))

        rec = da.evaluate_job(_job("AI Engineer"))

        assert constructed == []  # the LLM was never even constructed
        assert rec["decision"] == "NOT_EVALUATED"
        assert rec["score"] is None
        assert rec["no_posting_text"] is True


# ─── mode switch ─────────────────────────────────────────────────────────────

class TestModeSwitch:
    def _spy_on_rules_main(self, monkeypatch):
        called = {}

        def fake_main():
            called["called"] = True
            return 0

        monkeypatch.setattr(je, "main", fake_main)
        return called

    def test_unset_mode_delegates_to_the_rules_evaluator(self, monkeypatch):
        monkeypatch.delenv("EVALUATION_MODE", raising=False)
        called = self._spy_on_rules_main(monkeypatch)
        assert da.main() == 0
        assert called["called"]

    def test_rules_mode_delegates_to_the_rules_evaluator(self, monkeypatch):
        monkeypatch.setenv("EVALUATION_MODE", "rules")
        called = self._spy_on_rules_main(monkeypatch)
        assert da.main() == 0
        assert called["called"]

    def test_an_invalid_mode_warns_and_delegates(self, monkeypatch, capsys):
        monkeypatch.setenv("EVALUATION_MODE", "turbo")
        called = self._spy_on_rules_main(monkeypatch)
        assert da.main() == 0
        assert called["called"]
        out = capsys.readouterr().out
        assert "EVALUATION_MODE" in out and "rules" in out

    def test_agent_mode_does_not_touch_the_rules_evaluator(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EVALUATION_MODE", "agent")
        monkeypatch.setattr(je, "PROFILE_IS_FALLBACK", False)
        monkeypatch.setattr(je, "main",
                            lambda: pytest.fail("rules path taken in agent mode"))
        os.makedirs("digests", exist_ok=True)
        with open("digests/new_jobs_latest.json", "w", encoding="utf-8") as f:
            json.dump([], f)

        da.main()  # quiet day: clears 'latest', exits normally
        assert json.load(open("digests/job_evaluations_latest.json")) == []


# ─── schema compatibility downstream ─────────────────────────────────────────

class TestSchemaCompat:
    def test_an_agent_record_behaves_like_an_evaluator_record(self, monkeypatch):
        """The same record must round-trip through utils.effective_decision
        and the doc_generator APPLY gate (effective_decision(ev) == 'APPLY',
        agents/doc_generator.py) exactly like an evaluator record."""
        eval_rec = _evaluator_record(monkeypatch, _job(), score=88)
        client = FakeClient([_record_decision_call(score=88), _final()])
        _inject_clients(monkeypatch, client)
        agent_rec = da.evaluate_job(_job())

        assert effective_decision(agent_rec) == "APPLY" == agent_rec["decision"]
        assert effective_decision(agent_rec) == effective_decision(eval_rec)
        # The doc-generator gate, applied to both records identically.
        for rec in (agent_rec, eval_rec):
            assert (effective_decision(rec) == "APPLY") is True
            assert rec["materials_needed"] == ["cv"]


# ─── main(): full agent run ──────────────────────────────────────────────────

class TestMain:
    @pytest.fixture
    def agent_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EVALUATION_MODE", "agent")
        # The profile guard must not depend on whether the (gitignored)
        # profile happens to exist on this machine -- same trick the rest of
        # the suite needs in CI, where no secrets are restored.
        monkeypatch.setattr(je, "PROFILE_IS_FALLBACK", False)
        monkeypatch.setattr(da.time, "sleep", lambda *_: None)
        os.makedirs("digests", exist_ok=True)
        return tmp_path

    def _write_jobs(self, jobs):
        with open("digests/new_jobs_latest.json", "w", encoding="utf-8") as f:
            json.dump(jobs, f)

    def test_writes_latest_and_history_and_records_recommendations(
            self, agent_env, monkeypatch, capsys):
        self._write_jobs([_job(url="https://x/1"),
                          _job(TRUNC_DESC, company="Teaser AG", url="https://x/2")])
        _inject_clients(
            monkeypatch,
            FakeClient([_tool_call("get_posting_text"),
                        _record_decision_call(score=88), _final()]),
            # Truncated teaser: agent wants APPLY/90, the cap says REVIEW.
            FakeClient([_record_decision_call(score=90, decision="APPLY"), _final()]))

        assert da.main() is None  # exit 0

        latest = json.load(open("digests/job_evaluations_latest.json"))
        assert [e["decision"] for e in latest] == ["APPLY", "REVIEW"]
        assert all("agent_trace" in e for e in latest)

        import glob
        history = glob.glob("data/history/evaluations_*.json")
        assert len(history) == 1
        assert len(json.load(open(history[0]))) == 2

        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1  # only the APPLY job
        assert apps[0]["status"] == "recommended"
        assert apps[0]["score"] == 88

        out = capsys.readouterr().out
        assert "mode=agent" in out
        assert "agent proposed APPLY -> effective REVIEW" in out

    def test_exit_1_when_every_evaluation_fails(self, agent_env, monkeypatch):
        self._write_jobs([_job()])
        _inject_clients(monkeypatch, FakeClient([RuntimeError("API down")]))

        with pytest.raises(SystemExit) as exc:
            da.main()
        assert exc.value.code == 1

        latest = json.load(open("digests/job_evaluations_latest.json"))
        assert latest[0]["decision"] == "ERROR"
        assert latest[0]["score"] is None

    def test_the_cost_cap_is_respected(self, agent_env, monkeypatch):
        monkeypatch.setenv("MAX_EVALUATIONS_PER_RUN", "1")
        self._write_jobs([_job(url="https://x/1"), _job(url="https://x/2")])
        queue = _inject_clients(
            monkeypatch, FakeClient([_record_decision_call(score=88), _final()]))

        da.main()

        latest = json.load(open("digests/job_evaluations_latest.json"))
        assert len(latest) == 1
        assert queue == []  # the second job never even built a client
