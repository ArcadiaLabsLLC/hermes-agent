"""The auxiliary client (title, compression, vision, ...) on the SDK-free clients under ``agent.provider_sdks: false``.

``agent/auxiliary_client.py`` builds its clients through three doors: the module's lazy
``OpenAI`` proxy (every OpenAI-wire provider), ``build_anthropic_client`` (Anthropic
Messages endpoints, wrapped in ``AnthropicAuxiliaryClient``), and ``CodexAuxiliaryClient``
over an OpenAI client (the Responses wire); the async lane rebuilds a twin in
``_to_async_client``. Each door is exercised with the switch off, and the two wrapped wires
are compared with the SDK-backed wrapper fed the same bytes.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``_load_openai_cls`` ignores the switch                        -> proxy test red.
* ``sdk_free_async_client`` returns ``None``                     -> async test red (``from openai import AsyncOpenAI`` twin).
* ``auxiliary_wire`` drops ``SdkFreeClient`` from its isinstance -> hygiene test red.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from agent.transports.httpx_client import AsyncSdkFreeClient, SdkFreeClient

openai = pytest.importorskip("openai")
anthropic = pytest.importorskip("anthropic")

BASE = "https://provider.example/v1"
KEY = "fixture-aux-key-never-emitted"


def _profile(sdk_free: bool) -> None:
    from hermes_constants import get_hermes_home

    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": not sdk_free}}), encoding="utf-8")


def _mock(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_auxiliary_openai_door_hands_out_the_sdk_free_client_under_the_switch():
    from agent import auxiliary_client

    _profile(sdk_free=False)
    assert isinstance(auxiliary_client._create_openai_client(api_key=KEY, base_url=BASE), openai.OpenAI)  # control
    _profile(sdk_free=True)
    client = auxiliary_client._create_openai_client(api_key=KEY, base_url=BASE)
    assert isinstance(client, SdkFreeClient) and isinstance(client, auxiliary_client.OpenAI)


def test_the_async_twin_runs_the_sdk_free_client_off_loop():
    from agent import auxiliary_client

    _profile(sdk_free=True)
    body = {"id": "c", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "a title"}}]}
    sync = SdkFreeClient(api_key=KEY, base_url=BASE, http_client=_mock(lambda _r: httpx.Response(200, json=body)))
    twin, model = auxiliary_client._to_async_client(sync, "m")
    assert isinstance(twin, AsyncSdkFreeClient) and twin._real_client is sync and model == "m"
    answer = asyncio.run(twin.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}]))
    assert answer.choices[0].message.content == "a title"


def test_the_chat_wire_hygiene_recognises_the_sdk_free_clients():
    from agent.auxiliary_wire import prepare_chat_messages

    messages = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y",
                                                   "reasoning_details": [{"type": "reasoning.text", "text": "r"}]}]
    sync = SdkFreeClient(api_key=KEY, base_url=BASE)
    for client in (openai.OpenAI(api_key=KEY, base_url=BASE), sync, AsyncSdkFreeClient(sync)):
        prepared = prepare_chat_messages(client, {"model": "m", "messages": messages})
        assert prepared["messages"] is not messages, type(client).__name__  # the transport sanitized a copy
    native = object()
    assert prepare_chat_messages(native, {"messages": messages})["messages"] is messages  # control


_ANTHROPIC_STREAM = (
    'event: message_start\ndata: {"type": "message_start", "message": {"id": "m", "type": "message", "role": '
    '"assistant", "model": "claude-x", "content": [], "stop_reason": null, "stop_sequence": null, "usage": '
    '{"input_tokens": 3, "output_tokens": 1}}}\n\n'
    'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": '
    '{"type": "text", "text": ""}}\n\n'
    'event: content_block_delta\ndata: {"type": "content_block_delta", "index": 0, "delta": '
    '{"type": "text_delta", "text": "Compressed summary."}}\n\n'
    'event: content_block_stop\ndata: {"type": "content_block_stop", "index": 0}\n\n'
    'event: message_delta\ndata: {"type": "message_delta", "delta": {"stop_reason": "end_turn", '
    '"stop_sequence": null}, "usage": {"output_tokens": 4}}\n\n'
    'event: message_stop\ndata: {"type": "message_stop"}\n\n').encode()


def _view(answer):
    choice = answer.choices[0]
    usage = getattr(answer, "usage", None)
    return (choice.message.content, choice.finish_reason, getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None))


def test_an_anthropic_endpoint_is_wrapped_over_the_sdk_free_client_and_answers_as_the_sdk_does():
    from agent import auxiliary_client
    from agent.transports.httpx_anthropic import SdkFreeAnthropicClient

    answers = []
    for sdk_free in (False, True):
        _profile(sdk_free)
        leaf = auxiliary_client._create_openai_client(api_key=KEY, base_url="https://api.anthropic.com")
        wrapped = auxiliary_client._maybe_wrap_anthropic(leaf, "claude-x", KEY, "https://api.anthropic.com",
                                                         api_mode="anthropic_messages")
        assert isinstance(wrapped, auxiliary_client.AnthropicAuxiliaryClient)
        assert isinstance(wrapped._real_client, SdkFreeAnthropicClient) is sdk_free
        wrapped._real_client._client = _mock(lambda _r: httpx.Response(200, content=_ANTHROPIC_STREAM))
        answers.append(_view(wrapped.chat.completions.create(
            model="claude-x", messages=[{"role": "user", "content": "compress this"}], max_tokens=64)))
    assert answers[1] == answers[0] and answers[0][0] == "Compressed summary."


_CODEX_STREAM = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in [
    {"type": "response.output_item.added", "output_index": 0,
     "item": {"type": "message", "id": "msg", "role": "assistant", "status": "in_progress", "content": []}},
    {"type": "response.output_text.delta", "item_id": "msg", "output_index": 0, "content_index": 0,
     "delta": "A short title", "logprobs": []},
    {"type": "response.output_item.done", "output_index": 0, "item": {
        "type": "message", "id": "msg", "role": "assistant", "status": "completed",
        "content": [{"type": "output_text", "text": "A short title", "annotations": []}]}},
    {"type": "response.completed", "response": {"id": "r", "object": "response", "created_at": 1, "model": "gpt-5",
                                                "status": "completed", "output": [], "parallel_tool_calls": True,
                                                "tool_choice": "auto", "tools": [],
                                                "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8,
                                                          "input_tokens_details": {"cached_tokens": 0},
                                                          "output_tokens_details": {"reasoning_tokens": 0}}}},
]).encode()


def test_the_codex_wrapper_answers_over_the_sdk_free_client_as_over_the_sdk():
    from agent.auxiliary_client import CodexAuxiliaryClient

    def handler(_request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_CODEX_STREAM)

    answers = []
    for leaf in (openai.OpenAI(api_key=KEY, base_url=BASE, http_client=_mock(handler), max_retries=0),
                 SdkFreeClient(api_key=KEY, base_url=BASE, http_client=_mock(handler))):
        wrapped = CodexAuxiliaryClient(leaf, "gpt-5")
        answers.append(_view(wrapped.chat.completions.create(
            model="gpt-5", messages=[{"role": "user", "content": "title this"}])))
    assert answers[1] == answers[0] and answers[0][0] == "A short title"
