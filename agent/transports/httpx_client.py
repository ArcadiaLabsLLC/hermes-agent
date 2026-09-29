"""SDK-free provider client: the OpenAI chat-completions wire over raw ``httpx`` + SSE.

Re-homed from the July mobile core's ``turn_runner`` (embedded-hermes plan Stage 2
step 6). The upstream transports under ``agent.transports`` build requests and
normalize responses but leave the HTTP call to a provider SDK, and the ``openai``
SDK pulls ``pydantic-core`` and ``jiter`` (Rust), which a phone cannot load. This
module is the HTTP call without the SDK: it duck-types ``client.chat.completions.
create(**kwargs)`` — the one surface upstream's agent loop calls on the
chat-completions wire — so the loop, its retries, its error classifier and its
normalization all run unchanged on top of it (never a second loop).

Selection is a profile switch, not a provider property: ``agent.provider_sdks``
(default on) read through ``hermes_cli.config.config_switch``. Off, the one
client chokepoint (``agent.agent_runtime_helpers.create_openai_client``) returns
:class:`SdkFreeClient` instead of the SDK client; desktop keeps the SDKs.

Objects returned mirror the SDK's typed models the way pydantic builds them:
every field the SDK types is an attribute (``None`` when the provider omitted
it), and every key it does not type (``reasoning``, ``reasoning_details``, ...)
stays raw JSON, both as an attribute and in ``model_extra`` — pydantic's
``extra="allow"``. Only the chat-completions wire exists here: the Anthropic
Messages and Codex Responses wires consume SDK stream objects in the loop, so a
profile without SDKs refuses them at client construction instead of failing
mid-turn.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from types import SimpleNamespace
from typing import Any

import httpx

__all__ = [
    "CHAT_COMPLETIONS_WIRE",
    "MalformedSSE",
    "ProviderHTTPError",
    "ProviderStreamError",
    "SdkFreeClient",
    "SdkFreeWireUnavailable",
    "completion_record",
    "iter_sse_data",
    "provider_sdks_enabled",
    "sdk_free_client",
]

CHAT_COMPLETIONS_WIRE = "chat_completions"
#: Error bodies are read at most this far; a provider page is not a diagnostic.
_ERROR_BODY_BYTES = 16384


class MalformedSSE(ValueError):
    """The provider's event stream broke the SSE or JSON framing."""


class ProviderHTTPError(Exception):
    """A non-2xx answer, shaped like the SDK's ``APIStatusError`` for the loop's
    error classifier: ``status_code``, ``response`` (headers, ``Retry-After``) and
    ``body`` (the parsed JSON error object, when there is one)."""

    def __init__(self, status_code: int, *, message: str, body: Any, response: httpx.Response | None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body
        self.response = response


class ProviderStreamError(Exception):
    """An ``error`` object delivered inside an HTTP-200 stream."""

    def __init__(self, message: str, *, body: Any) -> None:
        super().__init__(message)
        self.message = message
        self.body = body
        self.status_code = None


class SdkFreeWireUnavailable(RuntimeError):
    """The profile has no provider SDKs and this api_mode has no SDK-free client."""


def provider_sdks_enabled() -> bool:
    """``agent.provider_sdks`` — off in a profile that ships no provider SDK."""
    from hermes_cli.config import config_switch

    return config_switch("agent", "provider_sdks", default=True)


def sdk_free_client(client_kwargs: Mapping[str, Any], *, api_mode: str | None) -> "SdkFreeClient | None":
    """The SDK-free client when the profile switches the SDKs off, else ``None``.

    ``client_kwargs`` are the SDK constructor's (``api_key``, ``base_url``,
    ``default_headers``, ``timeout``, ``http_client``, ...), so the chokepoint
    hands over exactly what the SDK client would have received.
    """
    if provider_sdks_enabled():
        return None
    wire = api_mode or CHAT_COMPLETIONS_WIRE
    if wire != CHAT_COMPLETIONS_WIRE:
        raise SdkFreeWireUnavailable(
            f"api_mode {wire!r} needs a provider SDK, and this profile ships none "
            "(agent.provider_sdks: false); only chat_completions runs SDK-free"
        )
    return SdkFreeClient(**client_kwargs)


# ── SSE ──────────────────────────────────────────────────────────────────────


def iter_sse_data(lines: Iterator[str]) -> Iterator[str]:
    """``data`` payloads of an SSE line stream; multi-line data joins with ``\\n``."""
    data_lines: list[str] = []
    for line in lines:
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            value = line[5:]
            data_lines.append(value[1:] if value.startswith(" ") else value)
        elif not line.startswith(("event:", "id:", "retry:")):
            raise MalformedSSE(f"invalid SSE field: {line[:40]}")
    if data_lines:
        yield "\n".join(data_lines)


# ── SDK-shaped records ───────────────────────────────────────────────────────

#: The fields the SDK's chat models type, per model; a nested model is named by
#: ``(kind, "one" | "list")``. Anything a provider sends outside this table is an
#: extra and stays raw JSON.
_SCHEMA: dict[str, dict[str, tuple[str, str] | None]] = {
    "completion": {
        "id": None, "object": None, "created": None, "model": None, "system_fingerprint": None,
        "service_tier": None, "choices": ("choice", "list"), "usage": ("usage", "one"),
    },
    "chunk": {
        "id": None, "object": None, "created": None, "model": None, "system_fingerprint": None,
        "service_tier": None, "choices": ("chunk_choice", "list"), "usage": ("usage", "one"),
    },
    "choice": {"index": None, "finish_reason": None, "logprobs": None, "message": ("message", "one")},
    "chunk_choice": {"index": None, "finish_reason": None, "logprobs": None, "delta": ("message", "one")},
    "message": {
        "role": None, "content": None, "refusal": None, "function_call": None, "audio": None,
        "annotations": None, "tool_calls": ("tool_call", "list"),
    },
    "tool_call": {"index": None, "id": None, "type": None, "function": ("function", "one")},
    "function": {"name": None, "arguments": None},
    "usage": {
        "prompt_tokens": None, "completion_tokens": None, "total_tokens": None,
        "prompt_tokens_details": ("details", "one"), "completion_tokens_details": ("details", "one"),
    },
    "details": {"cached_tokens": None, "reasoning_tokens": None, "audio_tokens": None},
}


def _typed(kind: str, arity: str, value: Any) -> Any:
    if arity == "list":
        return [_record(kind, item) for item in value] if isinstance(value, list) else value
    return _record(kind, value)


def _record(kind: str, raw: Any) -> Any:
    """``raw`` as the SDK's ``kind`` model: typed fields as records, extras raw."""
    if not isinstance(raw, Mapping):
        return raw
    fields = _SCHEMA[kind]
    values: dict[str, Any] = dict.fromkeys(fields)
    extra: dict[str, Any] = {}
    for key, value in raw.items():
        key = str(key)
        nested = fields.get(key, False)
        if nested is False:
            extra[key] = value
        elif nested is None:
            values[key] = value
        else:
            values[key] = _typed(nested[0], nested[1], value)
    record = SimpleNamespace(**values)
    for key, value in extra.items():
        if key.isidentifier() and not key.startswith("_") and key != "model_extra":
            setattr(record, key, value)
    record.model_extra = extra
    return record


def completion_record(payload: Mapping[str, Any]) -> Any:
    """A parsed ``chat.completion`` JSON body as the SDK's ``ChatCompletion``."""
    return _record("completion", payload)


def _chunk_record(payload: Mapping[str, Any]) -> Any:
    return _record("chunk", payload)


# ── client ───────────────────────────────────────────────────────────────────


def _error_body(text: str) -> Any:
    try:
        parsed = json.loads(text) if text else None
    except ValueError:
        return None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        return error if isinstance(error, dict) else parsed
    return None


class _Stream:
    """The SDK's ``Stream`` surface: iterate chunks, ``response``, ``close()``."""

    def __init__(self, response: httpx.Response, redact: Callable[[str], str]) -> None:
        self.response = response
        self._redact = redact

    def __iter__(self) -> Iterator[Any]:
        try:
            for data in iter_sse_data(self.response.iter_lines()):
                if data.strip() == "[DONE]":
                    return
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise MalformedSSE(f"invalid SSE JSON at column {exc.colno}") from exc
                if not isinstance(chunk, dict):
                    raise MalformedSSE("SSE data must decode to an object")
                if chunk.get("error"):
                    body = chunk["error"] if isinstance(chunk["error"], dict) else chunk
                    raise ProviderStreamError(self._redact(f"provider stream error: {chunk['error']}"), body=body)
                yield _chunk_record(chunk)
        finally:
            self.response.close()

    def close(self) -> None:
        self.response.close()

    def __enter__(self) -> "_Stream":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class SdkFreeClient:
    """``openai.OpenAI``'s chat-completions surface over raw ``httpx``.

    Built from the SDK's own constructor kwargs; an injected ``http_client`` (the
    loop's keep-alive client) is used as-is and kept on ``_client``, where the
    served-model header capture looks for it.
    """

    # auxiliary_client: a complete client, never re-wrapped by a wire adapter.
    HERMES_SKIP_TRANSPORT_WRAP = True

    def __init__(
        self, *, api_key: Any = "", base_url: Any = "", default_headers: Mapping[str, str] | None = None,
        timeout: Any = None, http_client: httpx.Client | None = None, organization: str | None = None,
        project: str | None = None, default_query: Mapping[str, Any] | None = None, **_sdk_only: Any,
    ) -> None:
        self.api_key = api_key
        self.base_url = str(base_url or "").rstrip("/")
        self._default_headers = {str(k): str(v) for k, v in (default_headers or {}).items()}
        if organization:
            self._default_headers.setdefault("OpenAI-Organization", organization)
        if project:
            self._default_headers.setdefault("OpenAI-Project", project)
        self._default_query = dict(default_query or {})
        self._timeout = timeout
        self._client = http_client or httpx.Client(
            timeout=timeout if timeout is not None else httpx.Timeout(600.0, connect=10.0)
        )
        self.is_closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat_completion))

    def close(self) -> None:
        self.is_closed = True
        self._client.close()

    def __enter__(self) -> "SdkFreeClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def _bearer(self) -> str:
        # Entra ID / rotating credentials hand the SDK a zero-arg token callable.
        key = self.api_key() if callable(self.api_key) else self.api_key
        return str(key or "")

    def _redact(self, text: str) -> str:
        from agent_runtime.redaction import redact_transport_text

        return redact_transport_text(text, secrets=(self._bearer(),))

    def _create_chat_completion(
        self, *, stream: bool = False, extra_headers: Mapping[str, Any] | None = None,
        extra_body: Mapping[str, Any] | None = None, extra_query: Mapping[str, Any] | None = None,
        timeout: Any = None, **params: Any,
    ) -> Any:
        body = {key: value for key, value in params.items() if value is not None}
        if extra_body:
            body.update(extra_body)
        if stream:
            body["stream"] = True
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream" if stream else "application/json",
                   **self._default_headers}
        if bearer := self._bearer():
            headers["Authorization"] = f"Bearer {bearer}"
        headers.update({str(k): str(v) for k, v in (extra_headers or {}).items()})
        effective_timeout = timeout if timeout is not None else self._timeout
        request = self._client.build_request(
            "POST", self.base_url + "/chat/completions", json=body, headers=headers,
            params={**self._default_query, **(extra_query or {})} or None,
            timeout=effective_timeout if effective_timeout is not None else httpx.USE_CLIENT_DEFAULT,
        )
        response = self._client.send(request, stream=True)
        if not 200 <= response.status_code < 300:
            self._raise_for_status(response)
        if stream:
            return _Stream(response, self._redact)
        try:
            payload = json.loads(response.read())
        except ValueError as exc:
            raise MalformedSSE("provider returned a non-JSON completion body") from exc
        finally:
            response.close()
        if not isinstance(payload, dict):
            raise MalformedSSE("provider completion body must be a JSON object")
        return completion_record(payload)

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            text = response.read()[:_ERROR_BODY_BYTES].decode("utf-8", errors="replace")
        finally:
            response.close()
        body = _error_body(text)
        detail = body.get("message") if isinstance(body, dict) and isinstance(body.get("message"), str) else text
        raise ProviderHTTPError(
            response.status_code, message=self._redact(f"HTTP {response.status_code}: {detail[:500]}"),
            body=body, response=response,
        )
