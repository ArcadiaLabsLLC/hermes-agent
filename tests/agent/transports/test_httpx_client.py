"""The SDK-free client (``agent.transports.httpx_client``) against the SDK it replaces on phones.

Re-homed with the July mobile core's ``turn_runner`` (embedded-hermes plan Stage 2
step 6): its captured goldens moved here from ``mobile_core/tests/golden``. The
parity claims compare against the real ``openai`` SDK fed the SAME bytes through
the same ``httpx`` mock transport, so "identical" is measured, not asserted from
a hand-written expectation. Every refusal carries its positive control.

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``_sdk_shaped_record`` drops extras (``extra[key] = value`` removed)  -> both parity tests red.
* ``_raise_for_status`` raises with ``status_code=None``      -> error-classification test red.
* ``_redact`` returns the text unredacted                     -> key-echo test red.
* ``sdk_free_client`` never consults ``provider_sdks_enabled`` -> selection test red.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from agent.transports.httpx_client import (
    MalformedSSE,
    ProviderHTTPError,
    SdkFreeClient,
    SdkFreeWireUnavailable,
)

GOLDEN = Path(__file__).parent / "fixtures" / "sdk_free"
BASE_URL = "https://provider.example/v1"
KEY = "fixture-secret-never-emitted"


def _golden(name: str):
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def _clients(handler):
    """(SDK client, SDK-free client) over one mock transport."""
    from openai import OpenAI

    def http():
        return httpx.Client(transport=httpx.MockTransport(handler))

    sdk = OpenAI(api_key=KEY, base_url=BASE_URL, http_client=http(), max_retries=0)
    return sdk, SdkFreeClient(api_key=KEY, base_url=BASE_URL, http_client=http())


def _chunk_view(chunk) -> dict:
    choice = chunk.choices[0] if chunk.choices else None
    delta = getattr(choice, "delta", None)
    calls = getattr(delta, "tool_calls", None) or []
    usage = chunk.usage
    return {
        "id": chunk.id, "model": chunk.model,
        "finish": getattr(choice, "finish_reason", None),
        "content": getattr(delta, "content", None),
        "reasoning": getattr(delta, "reasoning", None),
        "reasoning_content": getattr(delta, "reasoning_content", None),
        "calls": [(c.index, c.id, c.function.name, c.function.arguments) for c in calls],
        "usage": None if usage is None else (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens),
    }


def test_a_captured_stream_reads_exactly_as_the_sdk_reads_it():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content="".join(_golden("streams.json")["successful"]).encode())

    sdk, free = _clients(handler)
    kwargs = dict(model="example/model", messages=[{"role": "user", "content": "Hello"}], stream=True,
                  stream_options={"include_usage": True}, temperature=0.7, max_tokens=128, tools=None)
    expected = [_chunk_view(c) for c in sdk.chat.completions.create(**kwargs)]
    actual = [_chunk_view(c) for c in free.chat.completions.create(**kwargs)]
    assert actual == expected
    assert "".join(v["content"] or "" for v in actual) == "Hello world"  # the fixture reached both
    assert seen[0][:2] == seen[1][:2] == (BASE_URL + "/chat/completions", f"Bearer {KEY}")
    assert seen[1][2] == {k: v for k, v in seen[0][2].items() if v is not None}


def test_captured_completions_normalize_identically_to_the_sdk():
    from agent.transports.chat_completions import ChatCompletionsTransport

    fixtures = _golden("completions.json")
    assert fixtures
    for fixture in fixtures:
        sdk, free = _clients(lambda _r, body=fixture["response"]: httpx.Response(200, json=body))
        kwargs = dict(model="m", messages=[{"role": "user", "content": "x"}])
        transport = ChatCompletionsTransport()
        live = asdict(transport.normalize_response(sdk.chat.completions.create(**kwargs)))
        mine = asdict(transport.normalize_response(free.chat.completions.create(**kwargs)))
        assert mine == live, fixture["name"]
        assert live["content"] or live["tool_calls"], fixture["name"]  # control: not an empty compare


@pytest.mark.parametrize("name", ["rate_limit", "server_error", "authentication"])
def test_http_errors_classify_as_the_sdks_do(name):
    from agent.error_classifier import classify_api_error

    case = _golden("errors.json")[name]
    sdk, free = _clients(lambda _r: httpx.Response(case["status"], json=case["body"], headers={"retry-after": "3"}))
    kwargs = dict(model="m", messages=[{"role": "user", "content": "x"}])
    errors = []
    for client in (sdk, free):
        with pytest.raises(Exception) as caught:
            client.chat.completions.create(**kwargs)
        errors.append(caught.value)
    assert isinstance(errors[1], ProviderHTTPError) and errors[1].status_code == case["status"]
    expected, actual = (classify_api_error(e, provider="openrouter", model="m") for e in errors)
    assert (actual.reason, actual.retryable, actual.status_code) == (expected.reason, expected.retryable, expected.status_code)


@pytest.mark.parametrize("failure", [httpx.ConnectTimeout, httpx.PoolTimeout, httpx.WriteTimeout, httpx.ReadTimeout,
                                     httpx.ConnectError, httpx.WriteError, httpx.ReadError, httpx.RemoteProtocolError])
def test_a_request_that_gets_no_answer_raises_as_the_sdk_raises_it(failure):
    """No HTTP answer: the SDK raises ``APITimeoutError`` for a timeout and ``APIConnectionError``
    otherwise, each FROM the transport error; the SDK-free client raises its classes of the same
    names, message and cause. The loop's retry arms and error classifier key on exactly these."""
    from agent.error_classifier import classify_api_error
    from agent.transports import httpx_client

    def handler(request):
        raise failure("no answer", request=request)

    sdk, free = _clients(handler)
    errors = []
    for client in (sdk, free):
        with pytest.raises(Exception) as caught:
            client.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
        errors.append(caught.value)
    views = [(type(e).__name__, str(e), type(e.__cause__), [c.__name__ for c in type(e).__mro__[:3]]) for e in errors]
    assert views[1][:3] == views[0][:3]
    assert isinstance(errors[1], httpx_client.APIConnectionError)
    assert isinstance(errors[1], httpx_client.APITimeoutError) == issubclass(failure, httpx.TimeoutException)
    expected, actual = (classify_api_error(e, provider="openrouter", model="m") for e in errors)
    assert (actual.reason, actual.retryable) == (expected.reason, expected.retryable)


def test_a_provider_echoing_the_key_never_puts_it_in_the_error():
    secret = "fixture-secret-echoed-by-provider"
    free = SdkFreeClient(api_key=secret, base_url=BASE_URL, http_client=httpx.Client(
        transport=httpx.MockTransport(lambda _r: httpx.Response(401, text=f"invalid credential {secret}"))))
    with pytest.raises(ProviderHTTPError) as caught:
        free.chat.completions.create(model="m", messages=[])
    assert secret not in str(caught.value) and "invalid credential" in str(caught.value)


def test_malformed_sse_raises_instead_of_ending_quietly():
    free = SdkFreeClient(api_key=KEY, base_url=BASE_URL, http_client=httpx.Client(transport=httpx.MockTransport(
        lambda _r: httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=_golden("streams.json")["malformed"].encode()))))
    with pytest.raises(MalformedSSE):
        list(free.chat.completions.create(model="m", messages=[], stream=True))


def test_the_moved_goldens_carry_no_credential():
    combined = "\n".join(path.read_text(encoding="utf-8") for path in GOLDEN.glob("*.json"))
    assert len(list(GOLDEN.glob("*.json"))) == 3
    forbidden = ("sk-", "Bearer ", "api_key", "authorization", "cookie")
    assert not any(marker.lower() in combined.lower() for marker in forbidden)


def _build(api_mode=None):
    from types import SimpleNamespace

    from agent.agent_runtime_helpers import create_openai_client

    agent = SimpleNamespace(provider="openrouter", api_mode=api_mode, _client_log_context=lambda: "",
                            _build_keepalive_http_client=lambda *a, **k: None)
    return create_openai_client(agent, {"api_key": KEY, "base_url": BASE_URL}, reason="t", shared=False)


def test_the_profile_switch_picks_the_client_at_the_one_chokepoint():
    from openai import OpenAI

    from hermes_constants import get_hermes_home

    assert isinstance(_build(), OpenAI)  # positive control: desktop keeps the SDK
    home = Path(get_hermes_home())
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"agent": {"provider_sdks": False}}), encoding="utf-8")
    assert isinstance(_build(), SdkFreeClient)
    assert isinstance(_build("chat_completions"), SdkFreeClient)
    assert isinstance(_build("codex_responses"), SdkFreeClient)  # one OpenAI-shaped client, both wires
    with pytest.raises(SdkFreeWireUnavailable, match="anthropic_messages"):
        _build("anthropic_messages")  # its own client family, built in agent.anthropic_adapter
