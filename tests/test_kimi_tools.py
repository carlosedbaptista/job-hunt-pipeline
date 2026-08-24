"""
test_kimi_tools.py -- Pins the tool-calling extension of KimiClient.

chat_completion() must expose tool_calls/usage/model for the agent runtime
while chat() keeps returning a plain string for the rest of the pipeline.
All HTTP is mocked at KimiClient._post, which also records the payload it
was asked to send.
"""
import pytest

from kimi_client import KimiClient


@pytest.fixture
def captured(monkeypatch):
    """Replaces _post with a recorder; tests set captured['response']."""
    box = {"payloads": [], "response": None}

    def fake_post(self, endpoint, payload, timeout_sec=60):
        box["payloads"].append(payload)
        return box["response"]

    monkeypatch.setattr(KimiClient, "_post", fake_post)
    return box


def _client():
    return KimiClient(api_key="test-key", base_url="https://example.test/v1")


def _completion(content="hello", tool_calls=None, usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"index": 0, "message": message}],
            "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "kimi-k2.6"}


TOOL = {"type": "function",
        "function": {"name": "lookup",
                     "description": "Look something up",
                     "parameters": {"type": "object", "properties": {}}}}

MESSAGES = [{"role": "user", "content": "hi"}]


class TestPayload:
    def test_tools_and_tool_choice_land_in_the_payload(self, captured):
        captured["response"] = _completion()
        _client().chat_completion(MESSAGES, model="kimi-k2.6",
                                  tools=[TOOL], tool_choice="auto")
        payload = captured["payloads"][0]
        assert payload["tools"] == [TOOL]
        assert payload["tool_choice"] == "auto"

    def test_tools_keys_are_absent_when_not_given(self, captured):
        captured["response"] = _completion()
        _client().chat_completion(MESSAGES, model="kimi-k2.6")
        payload = captured["payloads"][0]
        assert "tools" not in payload
        assert "tool_choice" not in payload

    def test_thinking_stays_disabled_for_kimi_models_with_tools(self, captured):
        """Tools change nothing about the reasoning-token budget problem."""
        captured["response"] = _completion()
        _client().chat_completion(MESSAGES, model="kimi-k2.6",
                                  tools=[TOOL], tool_choice="auto")
        assert captured["payloads"][0]["thinking"] == {"type": "disabled"}


class TestResponseParsing:
    def test_tool_calls_are_parsed_and_content_may_be_none(self, captured):
        calls = [{"id": "call_1", "type": "function",
                  "function": {"name": "lookup", "arguments": "{}"}}]
        captured["response"] = _completion(content=None, tool_calls=calls)
        result = _client().chat_completion(MESSAGES, model="kimi-k2.6",
                                           tools=[TOOL])
        assert result["content"] is None
        assert result["tool_calls"] == calls
        assert result["model"] == "kimi-k2.6"

    def test_a_plain_answer_has_empty_tool_calls(self, captured):
        captured["response"] = _completion(content="hi there")
        result = _client().chat_completion(MESSAGES, model="kimi-k2.6")
        assert result["content"] == "hi there"
        assert result["tool_calls"] == []

    def test_usage_is_captured(self, captured):
        captured["response"] = _completion(
            usage={"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49})
        result = _client().chat_completion(MESSAGES, model="kimi-k2.6")
        assert result["usage"]["prompt_tokens"] == 42
        assert result["usage"]["completion_tokens"] == 7


class TestBackwardCompat:
    def test_chat_still_returns_a_plain_string(self, captured):
        captured["response"] = _completion(content="just text")
        result = _client().chat(MESSAGES, model="kimi-k2.6")
        assert result == "just text"
        assert isinstance(result, str)

    def test_chat_goes_through_the_same_payload_rules(self, captured):
        captured["response"] = _completion()
        _client().chat(MESSAGES, model="kimi-k2.6", temperature=0.3)
        payload = captured["payloads"][0]
        assert payload["temperature"] == 0.3
        assert payload["thinking"] == {"type": "disabled"}
        assert "tools" not in payload
