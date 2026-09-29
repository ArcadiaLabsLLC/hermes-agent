"""The ``anthropic_messages`` wire without the ``anthropic`` SDK: ``messages.create`` / ``messages.stream``.

Upstream's Anthropic path builds its client in one place
(``agent.anthropic_adapter._new_sdk_client``, reached from ``build_anthropic_client``
by the loop, the per-request client cache, the fallback chain and the auxiliary
client) and then reads it through the SDK's surface: ``messages.stream(**kwargs)``
entered as a context manager, iterated for events, then ``get_final_message()``;
``messages.create(**kwargs)`` where streaming is unavailable. Under
``agent.provider_sdks: false`` the adapter's SDK loader hands this module's
:data:`SDK_FREE_ANTHROPIC` to that one builder in place of the ``anthropic``
package, so every caller gets :class:`SdkFreeAnthropicClient` and nothing above it
changes.

Faithful to the SDK (0.87) on the parts the loop depends on, and measured against
it byte-for-byte in ``tests/agent/transports/test_httpx_anthropic.py``:

* SSE events dispatch on the ``event:`` name (an unnamed or unknown event is
  ignored, ``ping`` skipped, ``error`` raised as a status error);
* the message snapshot accumulates as ``accumulate_event`` does, including the
  ``Unexpected event order`` error the loop's stream-fallback test reads, and the
  stream yields the SDK's derived ``text`` / ``thinking`` / ``signature`` /
  ``input_json`` / ``citation`` events and its parsed ``content_block_stop`` /
  ``message_stop``;
* a streamed tool input is parsed with ``jiter``'s partial rules
  (:mod:`agent.transports.partial_json`);
* ``usage: null`` (MiniMax, #60683) is filled exactly as the loop's
  ``normalize_stream_usage`` fills it for the SDK — this stream has no
  ``_raw_stream`` for that wrapper to reach, so the fill is built in.

Recovered from the July mobile core's raw Anthropic lane (``turn_runner.py`` at
``a4ce2c42c89``), which assembled a turn of its own; this one returns the SDK's
objects and leaves the turn to the loop.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Mapping
from types import SimpleNamespace
from typing import Any

import httpx

from agent.transports import sdk_shapes
from agent.transports.httpx_client import (
    HttpCore,
    ProviderHTTPError,
    SdkStream,
    iter_sse_events,
    sdk_record,
    sse_json,
)
from agent.transports.partial_json import parse_partial_json

__all__ = ["SDK_FREE_ANTHROPIC", "MessageStream", "Omit", "SdkFreeAnthropicClient"]

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"
_RAW_EVENT = sdk_shapes.ROOTS["anthropic.raw_event"]
_STREAM_EVENT = sdk_shapes.ROOTS["anthropic.stream_event"]
_MESSAGE = sdk_shapes.ROOTS["anthropic.message"]
_PARSED_MESSAGE = sdk_shapes.ROOTS["anthropic.parsed_message"]
_PARSED_BLOCK = sdk_shapes.KINDS[_PARSED_MESSAGE]["content"][0]
#: The SDK's ``TRACKS_TOOL_INPUT``: blocks whose ``input`` a ``input_json_delta`` rebuilds.
_TRACKS_TOOL_INPUT = frozenset({"anthropic.ToolUseBlock", "anthropic.ServerToolUseBlock"})
#: SSE event names the SDK's ``Stream`` turns into events; any other name is ignored.
_MESSAGE_EVENTS = frozenset({
    "message_start", "message_delta", "message_stop", "content_block_start", "content_block_delta",
    "content_block_stop",
})


class Omit:
    """The SDK's ``Omit``: a default header whose value is this is not sent at all."""


def _merge_headers(*layers: Mapping[str, Any] | None) -> dict[str, str]:
    """Case-insensitive merge, later layers winning; an :class:`Omit` value removes the header."""
    merged: dict[str, tuple[str, Any]] = {}
    for layer in layers:
        for name, value in (layer or {}).items():
            merged[str(name).lower()] = (str(name), value)
    return {name: str(value) for name, value in merged.values() if not isinstance(value, Omit)}


def anthropic_error_body(text: str) -> Any:
    """The ``anthropic`` SDK's ``APIStatusError.body``: the whole parsed JSON, else the text."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except ValueError:
        return stripped


# ── the stream ───────────────────────────────────────────────────────────────


def raw_events(response: httpx.Response, raise_status: Callable[[str, Any], Exception]) -> Iterator[dict]:
    """The SDK ``Stream``'s dispatch: named message events as JSON objects (``type`` defaulted
    from the event name), ``ping`` skipped, ``error`` raised, anything else ignored."""
    for event, data in iter_sse_events(response.iter_lines()):
        if event in _MESSAGE_EVENTS:
            payload = sse_json(data, what="Anthropic")
            payload.setdefault("type", event)
            yield payload
        elif event == "error":
            try:
                body: Any = json.loads(data or "")
                message = f"{body}"
            except ValueError:
                body = data
                message = data or f"Error code: {response.status_code}"
            raise raise_status(message, body)


class _UsageFill:
    """``anthropic_adapter.normalize_stream_usage``'s fill, applied to the raw JSON before it is
    typed: ``usage: null`` on ``message_start`` becomes zero counts, and on ``message_delta``
    carries ``message_start``'s output count forward."""

    def __init__(self) -> None:
        self.output_tokens = 0

    def __call__(self, raw: dict) -> dict:
        kind = raw.get("type")
        message = raw.get("message")
        if kind == "message_start" and isinstance(message, dict):
            if message.get("usage") is None:
                message["usage"] = {"input_tokens": 0, "output_tokens": 0}
            elif isinstance(message["usage"], dict):
                self.output_tokens = message["usage"].get("output_tokens", 0) or 0
        elif kind == "message_delta" and raw.get("usage") is None:
            raw["usage"] = {"output_tokens": self.output_tokens}
        return raw


class _Snapshot:
    """``accumulate_event``: the ``ParsedMessage`` the stream builds, one typed event at a time."""

    def __init__(self) -> None:
        self.message: Any = None
        self._json_bufs: dict[int, str] = {}

    def add(self, event: Any) -> None:
        if self.message is None:
            if event.type != "message_start":
                raise RuntimeError(f'Unexpected event order, got {event.type} before "message_start"')
            self.message = sdk_record(_PARSED_MESSAGE, event.message.to_dict())
            return
        handler = _ACCUMULATORS.get(event.type)
        if handler is not None:
            handler(self, event)

    def _block_start(self, event: Any) -> None:
        self.message.content.append(sdk_record(_PARSED_BLOCK, event.content_block.model_dump()))

    def _block_delta(self, event: Any) -> None:
        index = event.index
        block = self.message.content[index]
        delta = event.delta
        apply = _DELTAS.get(delta.type)
        if apply is not None:
            apply(self, index, block, delta)

    def _text(self, _index: int, block: Any, delta: Any) -> None:
        if block.type == "text":
            block.text += delta.text

    def _input_json(self, index: int, block: Any, delta: Any) -> None:
        if block._kind in _TRACKS_TOOL_INPUT:
            buf = self._json_bufs.get(index, "") + delta.partial_json
            if buf:
                block.input = parse_partial_json(buf)
            self._json_bufs[index] = buf

    def _citation(self, _index: int, block: Any, delta: Any) -> None:
        if block.type == "text":
            block.citations = [*(block.citations or []), delta.citation]

    def _thinking(self, _index: int, block: Any, delta: Any) -> None:
        if block.type == "thinking":
            block.thinking += delta.thinking

    def _signature(self, _index: int, block: Any, delta: Any) -> None:
        if block.type == "thinking":
            block.signature = delta.signature

    def _message_delta(self, event: Any) -> None:
        message, usage = self.message, event.usage
        message.stop_reason = event.delta.stop_reason
        message.stop_sequence = event.delta.stop_sequence
        message.usage.output_tokens = usage.output_tokens
        for field in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "server_tool_use"):
            if getattr(usage, field, None) is not None:
                setattr(message.usage, field, getattr(usage, field))


_ACCUMULATORS: dict[str, Callable[[_Snapshot, Any], None]] = {
    "content_block_start": _Snapshot._block_start,
    "content_block_delta": _Snapshot._block_delta,
    "message_delta": _Snapshot._message_delta,
}
_DELTAS: dict[str, Callable[[_Snapshot, int, Any, Any], None]] = {
    "text_delta": _Snapshot._text,
    "input_json_delta": _Snapshot._input_json,
    "citations_delta": _Snapshot._citation,
    "thinking_delta": _Snapshot._thinking,
    "signature_delta": _Snapshot._signature,
}


def _event(**fields: Any) -> Any:
    return sdk_record(_STREAM_EVENT, fields)


def _delta_events(block: Any, delta: Any) -> list[Any]:
    """``build_events``' derived event for one ``content_block_delta`` (none when the block's type
    does not match the delta's, as in the SDK)."""
    derive = {
        "text_delta": ("text", lambda: _event(type="text", text=delta.text, snapshot=block.text)),
        "input_json_delta": ("tool_use", lambda: _event(type="input_json", partial_json=delta.partial_json,
                                                        snapshot=block.input)),
        "citations_delta": ("text", lambda: _event(type="citation", citation=delta.citation,
                                                   snapshot=block.citations or [])),
        "thinking_delta": ("thinking", lambda: _event(type="thinking", thinking=delta.thinking,
                                                      snapshot=block.thinking)),
        "signature_delta": ("thinking", lambda: _event(type="signature", signature=block.signature)),
    }.get(delta.type)
    return [derive[1]()] if derive is not None and block.type == derive[0] else []


#: ``build_events``: the events one accumulated raw event becomes (the raw event itself when unlisted).
_BUILD_EVENTS: dict[str, Callable[[Any, Any], list[Any]]] = {
    "message_stop": lambda event, snapshot: [_event(type="message_stop", message=snapshot)],
    "content_block_stop": lambda event, snapshot: [
        _event(type="content_block_stop", index=event.index, content_block=snapshot.content[event.index])],
    "content_block_delta": lambda event, snapshot: [
        event, *_delta_events(snapshot.content[event.index], event.delta)],
}


def _events_for(event: Any, snapshot: Any) -> list[Any]:
    """``build_events``: what the stream yields for one raw event, after it is accumulated."""
    build = _BUILD_EVENTS.get(event.type)
    return [event] if build is None else build(event, snapshot)


class MessageStream:
    """The SDK's ``MessageStream``: iterate events, ``get_final_message()``, ``text_stream``, ``response``."""

    def __init__(self, response: httpx.Response, raise_status: Callable[[str, Any], Exception]) -> None:
        self.response = response
        self._raise_status = raise_status
        self._snapshot = _Snapshot()
        self._iterator = self._stream()
        self.text_stream = self._text_stream()

    @property
    def request_id(self) -> str | None:
        return self.response.headers.get("request-id")

    def __iter__(self) -> Iterator[Any]:
        yield from self._iterator

    def __next__(self) -> Any:
        return next(self._iterator)

    def __enter__(self) -> "MessageStream":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self.response.close()

    def until_done(self) -> None:
        for _event in self:
            pass

    def get_final_message(self) -> Any:
        self.until_done()
        assert self._snapshot.message is not None
        return self._snapshot.message

    def get_final_text(self) -> str:
        message = self.get_final_message()
        texts = [block.text for block in message.content if block.type == "text"]
        if not texts:
            raise RuntimeError(".get_final_text() can only be called when the API returns a `text` content block.")
        return "".join(texts)

    @property
    def current_message_snapshot(self) -> Any:
        assert self._snapshot.message is not None
        return self._snapshot.message

    def _stream(self) -> Iterator[Any]:
        fill = _UsageFill()
        try:
            for raw in raw_events(self.response, self._raise_status):
                event = sdk_record(_RAW_EVENT, fill(raw))
                self._snapshot.add(event)
                yield from _events_for(event, self._snapshot.message)
        finally:
            self.response.close()

    def _text_stream(self) -> Iterator[str]:
        for event in self:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield event.delta.text


class MessageStreamManager:
    """``messages.stream()``'s return: the request is sent on ``__enter__``, closed on ``__exit__``."""

    def __init__(self, open_stream: Callable[[], MessageStream]) -> None:
        self._open = open_stream
        self._stream: MessageStream | None = None

    def __enter__(self) -> MessageStream:
        self._stream = self._open()
        return self._stream

    def __exit__(self, *_exc: Any) -> None:
        if self._stream is not None:
            self._stream.close()


# ── the client ───────────────────────────────────────────────────────────────


class _Messages:
    """``anthropic.Anthropic().messages``."""

    def __init__(self, client: "SdkFreeAnthropicClient") -> None:
        self._client = client

    def create(self, *, stream: bool = False, **params: Any) -> Any:
        response = self._client.post_messages(params, stream=stream)
        if stream:
            return SdkStream(response, lambda r: (sdk_record(_RAW_EVENT, raw)
                                                  for raw in raw_events(r, self._client.stream_error_factory(r))))
        return sdk_record(_MESSAGE, self._client.read_json(response))

    def stream(self, **params: Any) -> MessageStreamManager:
        def open_stream() -> MessageStream:
            response = self._client.post_messages(params, stream=True)
            return MessageStream(response, self._client.stream_error_factory(response))

        return MessageStreamManager(open_stream)


class SdkFreeAnthropicClient(HttpCore):
    """``anthropic.Anthropic`` over raw ``httpx``, built from the SDK's own constructor kwargs.

    Exactly the credential it is given is sent (``api_key`` -> ``X-Api-Key``, ``auth_token`` ->
    ``Authorization: Bearer``); unlike the SDK it never reads one from the environment, so the
    builder's ``Omit`` guard against dual auth is honoured by construction as well as by header.
    """

    error_body = staticmethod(anthropic_error_body)

    def __init__(self, *, api_key: str | None = None, auth_token: str | None = None, base_url: Any = None,
                 timeout: Any = None, default_headers: Mapping[str, Any] | None = None,
                 default_query: Mapping[str, Any] | None = None, http_client: httpx.Client | None = None,
                 **_sdk_only: Any) -> None:
        base = base_url or os.environ.get("ANTHROPIC_BASE_URL") or DEFAULT_BASE_URL
        super().__init__(api_key=api_key, base_url=base, timeout=timeout, http_client=http_client,
                         default_headers=default_headers, default_query=default_query)
        self.auth_token = auth_token
        self._init_kwargs = {"api_key": api_key, "auth_token": auth_token, "base_url": base_url, "timeout": timeout,
                             "default_query": default_query, "http_client": http_client}
        self.messages = _Messages(self)

    def with_options(self, *, default_headers: Mapping[str, Any] | None = None, **overrides: Any) -> "SdkFreeAnthropicClient":
        """The SDK's copy: same client, ``default_headers`` merged over the current ones."""
        headers = {**self._default_headers, **(default_headers or {})}
        return SdkFreeAnthropicClient(**{**self._init_kwargs, **overrides}, default_headers=headers)

    def _secret(self) -> str:
        return str(self.api_key or self.auth_token or "")

    def _auth_headers(self) -> dict[str, str]:
        headers = {}
        if self.api_key:
            headers["X-Api-Key"] = str(self.api_key)
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def post_messages(self, params: Mapping[str, Any], *, stream: bool) -> httpx.Response:
        """POST ``/v1/messages`` as the SDK sends it; ``None`` params are left out of the body."""
        params = dict(params)
        extra_headers = params.pop("extra_headers", None)
        extra_body = params.pop("extra_body", None)
        extra_query = params.pop("extra_query", None)
        timeout = params.pop("timeout", None)
        body = {key: value for key, value in params.items() if value is not None}
        if extra_body:
            body.update(extra_body)
        if stream:
            body["stream"] = True
        base = {"Accept": "application/json", "Content-Type": "application/json",
                "anthropic-version": ANTHROPIC_VERSION}
        headers = _merge_headers(base, self._auth_headers(), self._default_headers, extra_headers)
        return self.send("/v1/messages", body=body, headers=headers, query=extra_query, timeout=timeout)

    def stream_error_factory(self, response: httpx.Response) -> Callable[[str, Any], Exception]:
        """An in-stream ``error`` event -> the SDK's status error for the (200) response."""

        def make(message: str, body: Any) -> Exception:
            return ProviderHTTPError(response.status_code, message=self._redact(message), body=body,
                                     response=response)

        return make


#: What ``agent.anthropic_adapter`` loads in place of the ``anthropic`` package when the profile
#: ships no SDK: the two names its client builder reads.
SDK_FREE_ANTHROPIC = SimpleNamespace(Anthropic=SdkFreeAnthropicClient, Omit=Omit)
