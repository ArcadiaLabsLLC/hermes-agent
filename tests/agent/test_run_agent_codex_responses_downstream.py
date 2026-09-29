"""Fork-owned half of ``tests/agent/test_run_agent_codex_responses.py``.

The SDK-free client (the embedded phone's, ``agent.transports.httpx_client``)
must take upstream's #103673 pre-stream retry exactly as the SDK does. Moved
out of the upstream file so its bytes stay upstream's; upstream's helpers and
its autouse ``_no_codex_backoff`` are imported by name.
"""

from __future__ import annotations

import pytest

from tests.agent.test_run_agent_codex_responses import (  # noqa: F401 — upstream names the moved test uses
    _build_agent,
    _codex_request_kwargs,
    _no_codex_backoff,
)


@pytest.mark.parametrize("client_kind", ["sdk", "sdk_free"])
@pytest.mark.parametrize("failure", ["ConnectTimeout", "PoolTimeout", "WriteError", "ConnectError"])
def test_a_prestream_failure_is_retried_once_on_either_client(monkeypatch, client_kind, failure):
    """The #103673 retry, measured on the wire: the first request gets no answer (``failure`` raised by
    the transport), the second streams a completed response. The SDK wraps the failure in
    ``APIConnectionError`` / ``APITimeoutError``; the SDK-free client (the phone's) raises its own
    classes of those names from ``HttpCore.send`` — both must take the one retry. Before the wrap the
    SDK-free client raised ``httpx.ConnectTimeout`` / ``PoolTimeout`` / ``WriteError`` raw, which no
    arm retried."""
    import json

    import httpx
    from openai import OpenAI

    from agent.transports.httpx_client import SdkFreeClient

    base = "https://chatgpt.com/backend-api/codex"
    message = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "Recovered.", "annotations": []}]}
    done = {"id": "resp_retry_1", "object": "response", "created_at": 1, "model": "gpt-5-codex", "status": "completed",
            "output": [message], "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
            "usage": {"input_tokens": 10, "output_tokens": 6, "total_tokens": 16,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}
    events = [{"type": "response.output_item.done", "sequence_number": 0, "output_index": 0, "item": message},
              {"type": "response.completed", "sequence_number": 1, "response": done}]
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise getattr(httpx, failure)("no answer", request=request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    agent = _build_agent(monkeypatch)
    agent.client = (OpenAI(api_key="k", base_url=base, http_client=http, max_retries=0) if client_kind == "sdk"
                    else SdkFreeClient(api_key="k", base_url=base, http_client=http))

    response = agent._run_codex_stream(_codex_request_kwargs())

    assert len(calls) == 2
    assert response.status == "completed" and response.id == "resp_retry_1"
