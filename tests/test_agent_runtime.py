"""
test_agent_runtime.py -- Pins the generic tool-calling loop.

No HTTP anywhere: FakeClient replays a scripted queue of chat_completion
responses and records what the runtime sent back, so the message flow
(assistant turn -> tool results -> next call) can be asserted exactly.
"""
import json

import pytest

from agent_runtime import Tool, run_agent


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []  # snapshots of messages seen on each call

    def chat_completion(self, messages, max_tokens=1000, tools=None, tool_choice=None):
        self.calls.append({"messages": [dict(m) for m in messages],
                           "tools": tools, "tool_choice": tool_choice})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _tool_call(name, arguments, call_id="call_1"):
    return {"content": None,
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": arguments}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            "model": "fake"}


def _final(content):
    return {"content": content, "tool_calls": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 4},
            "model": "fake"}


def _make_tool(function):
    return Tool(name="lookup", description="Look something up",
                parameters={"type": "object",
                            "properties": {"query": {"type": "string"}}},
                function=function)


class TestHappyPath:
    def test_tool_result_is_fed_back_and_final_answer_returned(self):
        seen = {}

        def lookup(query):
            seen["query"] = query
            return {"answer": 42}

        client = FakeClient([_tool_call("lookup", '{"query": "meaning"}'),
                             _final("The answer is 42.")])
        result = run_agent(client, "sys", "usr", [_make_tool(lookup)])

        assert result["stopped_reason"] == "final"
        assert result["final"] == "The answer is 42."
        assert result["iterations"] == 2
        assert seen["query"] == "meaning"

        tool_messages = [m for m in result["messages"] if m["role"] == "tool"]
        assert len(tool_messages) == 1
        assert tool_messages[0]["tool_call_id"] == "call_1"
        assert tool_messages[0]["name"] == "lookup"
        assert json.loads(tool_messages[0]["content"]) == {"answer": 42}

    def test_assistant_turn_replays_tool_calls_for_the_next_call(self):
        """Without them the API could not match results to calls."""
        client = FakeClient([_tool_call("lookup", "{}"), _final("done")])
        run_agent(client, "sys", "usr", [_make_tool(lambda: "x")])
        second_call = client.calls[1]["messages"]
        assistant = [m for m in second_call if m["role"] == "assistant"]
        assert assistant[0]["tool_calls"][0]["function"]["name"] == "lookup"

    def test_schemas_and_tool_choice_are_sent(self):
        client = FakeClient([_final("done")])
        run_agent(client, "sys", "usr", [_make_tool(lambda: "x")])
        assert client.calls[0]["tool_choice"] == "auto"
        assert client.calls[0]["tools"] == [{
            "type": "function",
            "function": {"name": "lookup",
                         "description": "Look something up",
                         "parameters": {"type": "object",
                                        "properties": {"query": {"type": "string"}}}}}]

    def test_usage_is_summed_across_iterations(self):
        client = FakeClient([_tool_call("lookup", "{}"), _final("done")])
        result = run_agent(client, "sys", "usr", [_make_tool(lambda: "x")])
        assert result["usage"] == {"prompt_tokens": 8, "completion_tokens": 6}


class TestIterationCap:
    def test_a_client_that_only_calls_tools_hits_the_cap(self):
        client = FakeClient([_tool_call("lookup", "{}", call_id=f"c{i}")
                             for i in range(5)])
        result = run_agent(client, "sys", "usr",
                           [_make_tool(lambda: "x")], max_iterations=2)
        assert result["stopped_reason"] == "iteration_cap"
        assert result["final"] is None
        assert result["iterations"] == 2
        assert len(client.calls) == 2


class TestToolFailures:
    def _run_with(self, tool_call):
        client = FakeClient([tool_call, _final("recovered")])
        return run_agent(client, "sys", "usr", [_make_tool(self._boom)])

    def _boom(self, **kwargs):
        raise ValueError("bad input")

    def test_a_raising_tool_reports_the_error_and_the_loop_continues(self):
        result = self._run_with(_tool_call("lookup", "{}"))
        assert result["stopped_reason"] == "final"
        assert result["final"] == "recovered"
        content = json.loads(result["messages"][3]["content"])
        assert content["error"] == "ValueError: bad input"

    def test_an_unknown_tool_name_reports_the_error_and_continues(self):
        result = self._run_with(_tool_call("nope", "{}"))
        assert result["stopped_reason"] == "final"
        content = json.loads(result["messages"][3]["content"])
        assert "UnknownTool" in content["error"]
        assert "nope" in content["error"]

    def test_empty_arguments_string_means_no_arguments(self):
        seen = {}

        def lookup():
            seen["called"] = True
            return "ok"

        tool = Tool(name="lookup", description="d", parameters={}, function=lookup)
        client = FakeClient([_tool_call("lookup", ""), _final("done")])
        result = run_agent(client, "sys", "usr", [tool])
        assert seen["called"]
        assert result["tool_calls_made"][0]["arguments"] == {}


class TestClientFailure:
    def test_an_api_outage_stops_the_agent_without_raising(self):
        client = FakeClient([RuntimeError("API down")])
        result = run_agent(client, "sys", "usr", [_make_tool(lambda: "x")])
        assert result["stopped_reason"] == "error"
        assert result["final"] is None


class TestAuditTrace:
    def test_tool_calls_made_records_names_and_arguments_in_order(self):
        client = FakeClient([
            {"content": None,
             "tool_calls": [
                 {"id": "c1", "type": "function",
                  "function": {"name": "lookup", "arguments": '{"query": "a"}'}},
                 {"id": "c2", "type": "function",
                  "function": {"name": "lookup", "arguments": '{"query": "b"}'}}],
             "usage": {}, "model": "fake"},
            _final("done")])
        result = run_agent(client, "sys", "usr", [_make_tool(lambda query: query)])
        assert result["tool_calls_made"] == [
            {"name": "lookup", "arguments": {"query": "a"}},
            {"name": "lookup", "arguments": {"query": "b"}}]
