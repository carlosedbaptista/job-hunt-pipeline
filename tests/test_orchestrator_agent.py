"""
test_orchestrator_agent.py -- Pins the run-level orchestrator agent.

No HTTP, no secrets (tests.yml runs with none): a scripted FakeClient is
injected in place of KimiClient (same pattern as test_decision_agent.py),
subprocess.run is monkeypatched to record the legacy chain instead of
launching it, and every test runs inside tmp_path so digests/, data/history/
and the tracker DB stay local to the test.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

import orchestrator_agent as oa
import agents.tracker_updater as agents_tracker_updater
import decision_agent
import doc_generator
import followup_sender
import high_score_alert
import tracker_updater


# ─── scripted client (same pattern as test_decision_agent.py) ────────────────

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


def _inject_client(monkeypatch, client):
    monkeypatch.setattr(oa, "KimiClient", lambda *a, **k: client)


def _finish_run_call(summary="Docs, alerts and follow-ups done",
                     rationale="APPLY jobs were fresh", call_id="c99"):
    return _tool_call("finish_run", json.dumps(
        {"summary": summary, "rationale": rationale}), call_id=call_id)


# ─── isolation ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """digests/, data/history/ and the tracker DB stay in tmp_path; agent
    mode is opt-in per test via the ORCHESTRATION_MODE env var.

    The DB path lives in THREE bindings: followup_sender does
    `from agents.tracker_updater import DB_PATH, init_applications_table`,
    and `agents.tracker_updater` is a DISTINCT module object from the
    top-level `tracker_updater` the rest of the suite imports (both sys.path
    entries resolve, so the file is imported twice). Patching only one
    leaves the other pointed at the real tracker/jobs.db."""
    monkeypatch.chdir(tmp_path)
    db = str(tmp_path / "jobs.db")
    monkeypatch.setattr(tracker_updater, "DB_PATH", db)
    monkeypatch.setattr(agents_tracker_updater, "DB_PATH", db)
    monkeypatch.setattr(followup_sender, "DB_PATH", db)
    monkeypatch.delenv("ORCHESTRATION_MODE", raising=False)
    os.makedirs("digests", exist_ok=True)
    return tmp_path


class _Completed:
    def __init__(self, returncode=0):
        self.returncode = returncode


def _record_subprocess(monkeypatch, returncodes=None):
    """subprocess.run -> recorded, never launched."""
    calls = []
    rcs = list(returncodes or [])

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        return _Completed(rcs.pop(0) if rcs else 0)

    monkeypatch.setattr(oa.subprocess, "run", fake_run)
    return calls


def _write_evaluations(records):
    with open(oa.EVALUATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f)


def _apply_record(company="Lakeside Analytics AG", score=88, evaluated_at=None):
    return {"score": score, "decision": "APPLY", "recommendation": "APPLY",
            "hard_blockers": [], "insufficient_info": False,
            "language_gap_intermediate": False, "red_flags": [], "concerns": [],
            "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
            "job": {"company": company, "title": "AI Platform Engineer Intern",
                    "location": "Zurich", "url": "https://x/1",
                    "description": "Build LLM agent workflows. " * 20}}


def _review_record(company, score=75, evaluated_at=None):
    return {"score": score, "decision": "REVIEW", "recommendation": "REVIEW",
            "hard_blockers": [], "insufficient_info": False,
            "language_gap_intermediate": False, "red_flags": [], "concerns": [],
            "evaluated_at": evaluated_at or datetime.now(timezone.utc).isoformat(),
            "job": {"company": company, "title": "Data Analyst Intern",
                    "location": "Zurich", "url": "https://x/2",
                    "description": "SQL dashboards and Python automation. " * 20}}


def _read_log(tmp_path):
    logs = list(tmp_path.glob("digests/orchestrator_log_*.json"))
    assert len(logs) == 1, f"expected exactly one orchestrator log, got {logs}"
    return json.loads(logs[0].read_text(encoding="utf-8"))


LEGACY_ORDER = ["agents/doc_generator.py",
                "agents/high_score_alert.py",
                "agents/followup_sender.py"]

REQUIRED_LOG_KEYS = {"ts", "mode", "stopped_reason", "iterations", "usage",
                     "tool_calls_made", "tool_results_summary", "fallback_used",
                     "agent_summary", "agent_rationale"}


# ─── rules mode ──────────────────────────────────────────────────────────────

class TestRulesMode:
    def test_default_mode_runs_the_legacy_chain_in_order(self, monkeypatch):
        calls = _record_subprocess(monkeypatch)

        assert oa.main() == 0

        assert [c[1] for c in calls] == LEGACY_ORDER
        assert all(c[0] == sys.executable for c in calls)

    def test_explicit_rules_mode(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "rules")
        calls = _record_subprocess(monkeypatch)
        assert oa.main() == 0
        assert len(calls) == 3

    def test_an_invalid_mode_warns_and_runs_rules(self, monkeypatch, capsys):
        monkeypatch.setenv("ORCHESTRATION_MODE", "turbo")
        calls = _record_subprocess(monkeypatch)
        assert oa.main() == 0
        assert len(calls) == 3
        out = capsys.readouterr().out
        assert "ORCHESTRATION_MODE" in out and "rules" in out

    def test_a_failing_stage_does_not_stop_the_chain(self, monkeypatch, capsys):
        calls = _record_subprocess(monkeypatch, returncodes=[1, 0, 0])

        assert oa.main() == 0

        assert [c[1] for c in calls] == LEGACY_ORDER  # all three ran
        assert "exited 1" in capsys.readouterr().out

    def test_agent_mode_never_touches_subprocess_on_a_clean_run(self, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        calls = _record_subprocess(monkeypatch)
        _write_evaluations([_apply_record()])
        _inject_client(monkeypatch, FakeClient([
            _tool_call("get_run_state"), _finish_run_call(call_id="c2"), _final()]))

        assert oa.main() == 0
        assert calls == []


# ─── agent happy path ────────────────────────────────────────────────────────

class TestAgentHappyPath:
    def test_full_sequence_runs_each_stage_and_writes_the_log(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        _write_evaluations([_apply_record()])
        order = []
        monkeypatch.setattr(doc_generator, "main", lambda: order.append("docs"))
        monkeypatch.setattr(high_score_alert, "main", lambda: order.append("alerts"))
        monkeypatch.setattr(followup_sender, "draft_followups",
                            lambda: order.append("followups") or True)
        _inject_client(monkeypatch, FakeClient([
            _tool_call("get_run_state"),
            _tool_call("generate_docs", call_id="c2"),
            _tool_call("send_high_score_alerts", call_id="c3"),
            _tool_call("draft_followups", call_id="c4"),
            _finish_run_call(summary="One APPLY job: docs, alert, no follow-ups",
                             rationale="Fresh evaluations, one stale application",
                             call_id="c5"),
            _final()]))

        assert oa.main() == 0

        assert order == ["docs", "alerts", "followups"]

        log = _read_log(tmp_path)
        assert REQUIRED_LOG_KEYS <= set(log.keys())
        assert log["fallback_used"] is False
        assert log["mode"] == "agent"
        assert log["stopped_reason"] == "final"
        assert log["agent_summary"] == "One APPLY job: docs, alert, no follow-ups"
        assert log["agent_rationale"] == "Fresh evaluations, one stale application"
        assert [c["name"] for c in log["tool_calls_made"]] == [
            "get_run_state", "generate_docs", "send_high_score_alerts",
            "draft_followups", "finish_run"]
        # The run state the agent saw: 1 APPLY, fresh, apply job listed.
        state = json.loads(log["tool_results_summary"][0]["result"])
        assert state["fresh"] is True
        assert state["decisions"]["APPLY"] == 1
        assert state["apply_jobs"][0]["company"] == "Lakeside Analytics AG"


# ─── freshness rail ──────────────────────────────────────────────────────────

class TestFreshnessRail:
    def test_stale_evaluations_refuse_doc_generation(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        _write_evaluations([_apply_record(evaluated_at=yesterday)])
        monkeypatch.setattr(doc_generator, "main",
                            lambda: pytest.fail("doc_generator ran on stale evaluations"))
        _inject_client(monkeypatch, FakeClient([
            _tool_call("generate_docs"),
            _finish_run_call(summary="Refused docs: stale state", call_id="c2"),
            _final()]))

        assert oa.main() == 0

        out = capsys.readouterr().out
        assert "REFUSED" in out
        log = _read_log(tmp_path)
        assert log["fallback_used"] is False  # finish_run was still called
        refusal = log["tool_results_summary"][0]["result"]
        assert "stale evaluations - refusing to spend on yesterday's jobs" in refusal

    def test_get_run_state_reports_stale_for_yesterdays_file(self, tmp_path, monkeypatch):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        _write_evaluations([_apply_record(evaluated_at=yesterday)])
        state = oa.get_run_state()
        assert state["fresh"] is False
        assert state["evaluations"] == 1

    def test_a_file_written_today_without_timestamps_is_fresh(self, tmp_path):
        rec = _apply_record()
        del rec["evaluated_at"]
        _write_evaluations([rec])
        assert oa.get_run_state()["fresh"] is True  # mtime decides


# ─── fallback (the guaranteed floor) ─────────────────────────────────────────

class TestFallback:
    def test_client_error_degrades_to_the_legacy_chain(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        calls = _record_subprocess(monkeypatch)
        _inject_client(monkeypatch, FakeClient([RuntimeError("API down")]))

        assert oa.main() == 0

        assert [c[1] for c in calls] == LEGACY_ORDER
        out = capsys.readouterr().out
        assert "without finish_run" in out and "[fallback]" in out
        log = _read_log(tmp_path)
        assert log["fallback_used"] is True
        assert log["stopped_reason"] == "error"
        assert log["agent_summary"] is None

    def test_missing_finish_run_degrades_to_the_legacy_chain(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        monkeypatch.setenv("ORCHESTRATOR_MAX_ITERATIONS", "2")
        calls = _record_subprocess(monkeypatch)
        # The agent keeps calling a harmless tool and never finalizes.
        _inject_client(monkeypatch, FakeClient([
            _tool_call("get_run_state"),
            _tool_call("get_run_state", call_id="c2")]))

        assert oa.main() == 0

        assert [c[1] for c in calls] == LEGACY_ORDER
        log = _read_log(tmp_path)
        assert log["fallback_used"] is True
        assert log["stopped_reason"] == "iteration_cap"
        assert log["iterations"] == 2

    def test_unconstructable_client_degrades_to_the_legacy_chain(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        calls = _record_subprocess(monkeypatch)

        def boom(*a, **k):
            raise ValueError("KIMI_API_KEY not configured")

        monkeypatch.setattr(oa, "KimiClient", boom)

        assert oa.main() == 0
        assert [c[1] for c in calls] == LEGACY_ORDER
        assert _read_log(tmp_path)["fallback_used"] is True


# ─── re-evaluation ───────────────────────────────────────────────────────────

class TestReevaluation:
    def _seed_history(self, tmp_path, records, days_ago=1):
        fdate = (date.today() - timedelta(days=days_ago)).strftime("%Y%m%d")
        hist_dir = tmp_path / "data" / "history"
        hist_dir.mkdir(parents=True, exist_ok=True)
        with open(hist_dir / f"evaluations_{fdate}.json", "w", encoding="utf-8") as f:
            json.dump(records, f)

    def test_the_cap_is_enforced_in_code(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        monkeypatch.setenv("ORCHESTRATOR_MAX_REEVALUATIONS", "1")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self._seed_history(tmp_path, [
            _review_record("Alpha AG", 72, yesterday),
            _review_record("Beta AG", 75, yesterday),
            _review_record("Gamma AG", 78, yesterday)])

        evaluated = []

        def fake_evaluate(job):
            evaluated.append(job)
            return {"score": 82, "decision": "APPLY", "recommendation": "APPLY",
                    "hard_blockers": [], "insufficient_info": False,
                    "language_gap_intermediate": False,
                    "job": {"company": job.get("company"), "title": job.get("title"),
                            "location": job.get("location", ""), "url": job.get("url", "")}}

        monkeypatch.setattr(decision_agent, "evaluate_job", fake_evaluate)
        _inject_client(monkeypatch, FakeClient([
            _tool_call("reevaluate_borderline", json.dumps({"max_jobs": 5})),
            _finish_run_call(summary="Re-evaluated one borderline job", call_id="c2"),
            _final()]))

        assert oa.main() == 0

        # Asked for 5, cap is 1: exactly one job went through the decision agent.
        assert len(evaluated) == 1

        # The new record was appended to latest AND to today's history file,
        # and the effective-APPLY result landed in the tracker.
        latest = json.loads((tmp_path / "digests" / "job_evaluations_latest.json")
                            .read_text(encoding="utf-8"))
        assert len(latest) == 1 and latest[0]["score"] == 82
        today_file = tmp_path / "data" / "history" / (
            f"evaluations_{datetime.now(timezone.utc).strftime('%Y%m%d')}.json")
        assert len(json.loads(today_file.read_text(encoding="utf-8"))) == 1
        apps = tracker_updater.get_all_applications()
        assert len(apps) == 1 and apps[0]["status"] == "recommended"

        log = _read_log(tmp_path)
        assert log["fallback_used"] is False
        reeval = json.loads(log["tool_results_summary"][0]["result"])
        assert reeval["cap"] == 1
        assert reeval["reevaluated"][0]["old_score"] is not None
        assert reeval["reevaluated"][0]["new_decision"] == "APPLY"

    def test_jobs_already_scored_today_are_not_rescored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self._seed_history(tmp_path, [_review_record("Alpha AG", 75, yesterday)])
        # The same job also appears in today's evaluations: already scored.
        _write_evaluations([_review_record("Alpha AG", 75)])
        monkeypatch.setattr(decision_agent, "evaluate_job",
                            lambda job: pytest.fail("re-scored a job scored today"))
        _inject_client(monkeypatch, FakeClient([
            _tool_call("reevaluate_borderline", json.dumps({"max_jobs": 3})),
            _finish_run_call(summary="Nothing to re-evaluate", call_id="c2"),
            _final()]))

        assert oa.main() == 0
        log = _read_log(tmp_path)
        assert "no eligible REVIEW-band jobs" in log["tool_results_summary"][0]["result"]


# ─── tool failure inside the loop ────────────────────────────────────────────

class TestToolFailure:
    def test_a_raising_tool_feeds_the_error_back_and_the_loop_continues(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        _write_evaluations([_apply_record()])

        def boom():
            raise RuntimeError("pdf backend exploded")

        monkeypatch.setattr(doc_generator, "main", boom)
        _inject_client(monkeypatch, FakeClient([
            _tool_call("generate_docs"),
            _finish_run_call(summary="Docs failed; alerts skipped", call_id="c2"),
            _final()]))

        assert oa.main() == 0

        log = _read_log(tmp_path)
        assert log["fallback_used"] is False  # finish_run still reached
        tool_result = log["tool_results_summary"][0]["result"]
        assert "RuntimeError: pdf backend exploded" in tool_result


# ─── quiet day ───────────────────────────────────────────────────────────────

class TestQuietDay:
    def test_no_evaluations_file_is_zeros_and_not_fresh(self, tmp_path):
        state = oa.get_run_state()
        assert state["evaluations"] == 0
        assert state["fresh"] is False
        assert state["decisions"] == {"APPLY": 0, "REVIEW": 0, "SKIP": 0, "ERROR": 0}
        assert state["apply_jobs"] == []

    def test_a_quiet_day_still_completes_and_writes_a_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ORCHESTRATION_MODE", "agent")
        _inject_client(monkeypatch, FakeClient([
            _tool_call("get_run_state"),
            _finish_run_call(summary="Quiet day: nothing scored, nothing to do",
                             rationale="No evaluations and no fresh state",
                             call_id="c2"),
            _final()]))

        assert oa.main() == 0

        log = _read_log(tmp_path)
        assert log["fallback_used"] is False
        state = json.loads(log["tool_results_summary"][0]["result"])
        assert state["fresh"] is False
        assert state["evaluations"] == 0

    def test_a_not_a_list_evaluations_file_is_zeros(self, tmp_path):
        with open(oa.EVALUATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump({"not": "a list"}, f)
        assert oa.get_run_state()["evaluations"] == 0
