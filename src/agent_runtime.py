"""
agent_runtime.py -- generic tool-calling loop over the Kimi client.

The agent decides nothing by itself: each iteration the model either asks for
tools (their results are fed back as `role: tool` messages) or answers with
final content. Tool failures are reported back to the model as data, never
raised -- an agent that crashes on a bad tool call cannot recover, one that
can read the error message usually can.
"""
import json
from dataclasses import dataclass
from typing import Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict          # JSON Schema object describing arguments
    function: Callable        # (**kwargs) -> JSON-serializable result


def _schema(tool):
    """OpenAI-compatible tool schema for the API payload."""
    return {"type": "function",
            "function": {"name": tool.name,
                         "description": tool.description,
                         "parameters": tool.parameters}}


def run_agent(client, system, user, tools, max_iterations=5, max_tokens=2000):
    """Returns {'final': str|None, 'messages': list, 'tool_calls_made': list,
    'iterations': int, 'stopped_reason': 'final'|'iteration_cap'|'error',
    'usage': dict}"""
    tools_by_name = {t.name: t for t in tools}
    schemas = [_schema(t) for t in tools]
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
    tool_calls_made = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0}

    def result(stopped_reason, final, iterations):
        return {"final": final, "messages": messages,
                "tool_calls_made": tool_calls_made, "iterations": iterations,
                "stopped_reason": stopped_reason, "usage": usage}

    for iteration in range(1, max_iterations + 1):
        try:
            # An empty tool list with tool_choice set is rejected by some
            # APIs, so both are dropped when the agent has no tools.
            response = client.chat_completion(
                messages, max_tokens=max_tokens,
                tools=schemas or None,
                tool_choice="auto" if schemas else None)
        except Exception:
            # API outage: the agent reports failure, it never propagates it
            return result("error", None, iteration)

        iter_usage = response.get("usage") or {}
        usage["prompt_tokens"] += iter_usage.get("prompt_tokens", 0)
        usage["completion_tokens"] += iter_usage.get("completion_tokens", 0)

        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            return result("final", response.get("content"), iteration)

        # The assistant turn must be replayed verbatim (tool_calls included)
        # or the API cannot match the tool results that follow.
        messages.append({"role": "assistant",
                         "content": response.get("content"),
                         "tool_calls": tool_calls})

        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name", "")
            raw_arguments = function.get("arguments") or ""
            try:
                # Models sometimes emit "" for a no-argument call
                arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
            except ValueError as e:
                arguments = {}
                tool_result = {"error": f"{type(e).__name__}: {e}"}
            else:
                tool = tools_by_name.get(name)
                if tool is None:
                    tool_result = {"error": f"UnknownTool: no tool named '{name}'"}
                else:
                    try:
                        tool_result = tool.function(**arguments)
                    except Exception as e:
                        tool_result = {"error": f"{type(e).__name__}: {e}"}
            tool_calls_made.append({"name": name, "arguments": arguments})
            messages.append({"role": "tool",
                             "tool_call_id": call.get("id"),
                             "name": name,
                             "content": json.dumps(tool_result)})

    return result("iteration_cap", None, max_iterations)
