"""SDK-free provider clients: the OpenAI-shaped client over raw ``httpx`` + SSE, and what every wire shares.

Re-homed from the July mobile core's ``turn_runner`` (embedded-hermes plan Stage 2
step 6). The upstream transports under ``agent.transports`` build requests and
normalize responses but leave the HTTP call to a provider SDK, and the ``openai``
/ ``anthropic`` SDKs pull ``pydantic-core`` and ``jiter`` (Rust), which a phone
cannot load. These modules are the HTTP call without the SDK, one client family
per SDK, each duck-typing exactly the surface upstream's agent loop and
auxiliary client call — so the loop, its retries, its error classifier and its
normalization all run unchanged on top of them (never a second loop):

* :class:`SdkFreeClient` (here) — ``openai.OpenAI``'s ``chat.completions.create``
  (the ``chat_completions`` wire) and ``responses.create`` (``codex_responses``,
  :mod:`agent.transports.httpx_responses`);
* ``SdkFreeAnthropicClient`` (:mod:`agent.transports.httpx_anthropic`) —
  ``anthropic.Anthropic``'s ``messages.create`` / ``messages.stream``
  (``anthropic_messages``).

Selection is a profile switch, not a provider property: ``agent.provider_sdks``
(default on) read through ``hermes_cli.config_switches.config_switch``. Off, the client
chokepoints (``agent.agent_runtime_helpers.create_openai_client``,
``agent.anthropic_adapter``'s SDK loader and the auxiliary client's ``OpenAI``
proxy) hand out the SDK-free clients instead; desktop keeps the SDKs.

Objects returned mirror the SDK's typed models the way pydantic builds them:
every field the SDK types is an attribute (``None`` when the provider omitted
it), nested models are records, a discriminated union picks its model by
``type`` (the first model for a value it does not know, as the SDKs do), and
every key the SDK does not type stays raw JSON, both as an attribute and in
``model_extra`` — pydantic's ``extra="allow"``. The typed fields are not written
by hand: :mod:`agent.transports.sdk_shapes` is rendered from the SDKs' own models
and diffed by a test.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from types import SimpleNamespace
from typing import Any

import httpx

from agent.transports import sdk_shapes

__all__ = [
    "APIConnectionError",
    "APIError",
    "APITimeoutError",
    "CHAT_COMPLETIONS_WIRE",
    "CODEX_RESPONSES_WIRE",
    "AsyncSdkFreeClient",
    "MalformedSSE",
    "ProviderHTTPError",
    "ProviderStreamError",
    "SdkFreeClient",
    "SdkFreeWireUnavailable",
    "SdkRecord",
    "completion_record",
    "iter_sse_data",
    "iter_sse_events",
    "missing_sdk",
    "provider_sdks_enabled",
    "sdk_import_failure",
    "chat_tool_call_factories",
    "sdk_free_async_client",
    "sdk_free_client",
    "sdk_record",
]

CHAT_COMPLETIONS_WIRE = "chat_completions"
CODEX_RESPONSES_WIRE = "codex_responses"
#: The wires :class:`SdkFreeClient` serves (``anthropic_messages`` has its own client family).
_OPENAI_SHAPED_WIRES = frozenset({CHAT_COMPLETIONS_WIRE, CODEX_RESPONSES_WIRE})
#: Error bodies are read at most this far; a provider page is not a diagnostic.
_ERROR_BODY_BYTES = 16384


class MalformedSSE(ValueError):
    """The provider's event stream broke the SSE or JSON framing."""


class APIError(Exception):
    """The SDKs' ``APIError``: the base of every error the SDK-free clients raise for a request, as
    the SDK's is the base of ``APIStatusError`` and ``APIConnectionError`` — so an upstream
    ``isinstance(exc, openai.APIError)`` reads the same on the phone's ``openai`` shim
    (:mod:`agent_runtime.provider_sdk_shim`)."""


class ProviderHTTPError(APIError):
    """A non-2xx answer, shaped like the SDK's ``APIStatusError`` for the loop's
    error classifier: ``status_code``, ``response`` (headers, ``Retry-After``) and
    ``body`` (the parsed JSON error, shaped as that SDK shapes it)."""

    def __init__(self, status_code: int, *, message: str, body: Any, response: httpx.Response | None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.body = body
        self.response = response


class ProviderStreamError(APIError):
    """An ``error`` object delivered inside an HTTP-200 stream."""

    def __init__(self, message: str, *, body: Any) -> None:
        super().__init__(message)
        self.message = message
        self.body = body
        self.status_code = None


class APIConnectionError(APIError):
    """The request got no HTTP answer: the SDKs' ``APIConnectionError``, raised from the transport
    error as they raise it (``raise APIConnectionError(request=request) from err``), so a caller's
    retry arm — ``codex_runtime.run_codex_stream`` retries a pre-stream failure once when its
    ``__cause__`` is an ``httpx.TransportError`` — takes the same path on both clients."""

    def __init__(self, *, message: str = "Connection error.", request: httpx.Request | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.request = request
        self.status_code = None
        self.body = None


class APITimeoutError(APIConnectionError):
    """The SDKs' ``APITimeoutError``: the request timed out before an answer (an ``httpx.TimeoutException``)."""

    def __init__(self, request: httpx.Request | None = None) -> None:
        super().__init__(message="Request timed out.", request=request)


class SdkFreeWireUnavailable(RuntimeError):
    """The profile has no provider SDKs and this api_mode has no SDK-free client."""


def sdk_import_failure(package: str, exc: ImportError) -> SdkFreeWireUnavailable:
    """The error for an SDK import that failed: absent only when *package* itself is not found.

    An installed SDK whose own import fails -- a dependency's compiled module built for another
    interpreter (``pydantic_core``'s ``cp314`` extension under 3.12) -- is not a profile that
    ships no SDK, and telling the operator to set ``agent.provider_sdks: false`` sends them the
    wrong way. The chained cause stays attached either way.
    """
    if isinstance(exc, ModuleNotFoundError) and exc.name == package:
        return SdkFreeWireUnavailable(f"the {package} SDK is not installed; a profile without it must set "
                                      "agent.provider_sdks: false")
    return SdkFreeWireUnavailable(f"the {package} SDK is installed but failed to import "
                                  f"({type(exc).__name__}: {exc}); its environment is broken or was built "
                                  "for another Python -- run `hermes pm repair`")


def missing_sdk(name: str) -> Callable[..., Any]:
    """The fallback of a guarded SDK-constructor import: calling it says which SDK is absent."""

    def unavailable(*_args: Any, **_kwargs: Any) -> Any:
        raise SdkFreeWireUnavailable(f"{name} needs a provider SDK, and this profile ships none "
                                     "(agent.provider_sdks: false)")

    return unavailable


def chat_tool_call_factories() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """``ChatCompletionMessageToolCall, Function`` for the phone's ``openai`` shim
    (:mod:`agent_runtime.provider_sdk_shim`): each builds the record the SDK-free chat client builds
    for that model (``Model(**fields)``)."""
    message = sdk_shapes.KINDS[sdk_shapes.KINDS[sdk_shapes.ROOTS["chat.completion"]]["choices"][0]]["message"][0]
    tool_call = _kind_for(sdk_shapes.KINDS[message]["tool_calls"][0], {"type": "function"})
    function = sdk_shapes.KINDS[tool_call]["function"][0]
    return (lambda **fields: sdk_record(tool_call, fields)), (lambda **fields: sdk_record(function, fields))


def sdk_free_async_client(sync_client: Any) -> "AsyncSdkFreeClient | None":
    """The auxiliary client's async twin of an SDK-free client, else ``None``."""
    return AsyncSdkFreeClient(sync_client) if isinstance(sync_client, SdkFreeClient) else None


def provider_sdks_enabled() -> bool:
    """``agent.provider_sdks`` — off in a profile that ships no provider SDK."""
    from hermes_cli.config_switches import config_switch

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
    if wire not in _OPENAI_SHAPED_WIRES:
        raise SdkFreeWireUnavailable(
            f"api_mode {wire!r} has no OpenAI-shaped SDK-free client (agent.provider_sdks: false); this "
            f"chokepoint serves {sorted(_OPENAI_SHAPED_WIRES)} and anthropic_messages builds its own client"
        )
    return SdkFreeClient(**client_kwargs)


# ── SSE ──────────────────────────────────────────────────────────────────────


_SSE_FIELDS = frozenset({"data", "event", "id", "retry"})


def iter_sse_events(lines: Iterator[str]) -> Iterator[tuple[str | None, str | None]]:
    """``(event, data)`` per SSE event of a line stream; multi-line data joins with ``\\n``.

    ``data`` is ``None`` for an event that carried no ``data:`` line (the SDKs' decoders still
    dispatch it); comments and ``id:`` / ``retry:`` lines are skipped.
    """
    event: str | None = None
    data_lines: list[str] | None = None
    for line in lines:
        if line == "":
            if data_lines is not None or event is not None:
                yield event, None if data_lines is None else "\n".join(data_lines)
            event, data_lines = None, None
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field not in _SSE_FIELDS:
            raise MalformedSSE(f"invalid SSE field: {line[:40]}")
        if field == "data":
            data_lines = [*(data_lines or []), value]
        elif field == "event":
            event = value  # ``id`` / ``retry`` are read and dropped, as the SDKs' streams drop them
    if data_lines is not None or event is not None:
        yield event, None if data_lines is None else "\n".join(data_lines)


def iter_sse_data(lines: Iterator[str]) -> Iterator[str]:
    """``data`` payloads of an SSE line stream (events that carried a ``data:`` line)."""
    for _event, data in iter_sse_events(lines):
        if data is not None:
            yield data


def sse_json(data: str | None, *, what: str) -> dict:
    """One SSE ``data`` payload as the JSON object it must be."""
    try:
        payload = json.loads(data or "")
    except json.JSONDecodeError as exc:
        raise MalformedSSE(f"invalid {what} SSE JSON at column {exc.colno}") from exc
    if not isinstance(payload, dict):
        raise MalformedSSE(f"{what} SSE data must decode to an object")
    return payload


# ── SDK-shaped records ───────────────────────────────────────────────────────


def _dump(value: Any, options: Mapping[str, Any]) -> Any:
    if isinstance(value, SdkRecord):
        return value.model_dump(**options)
    container = _DUMP_CONTAINERS.get(type(value))
    return value if container is None else container(value, options)


_DUMP_CONTAINERS: dict[type, Callable[[Any, Mapping[str, Any]], Any]] = {
    list: lambda value, options: [_dump(item, options) for item in value],
    dict: lambda value, options: {key: _dump(item, options) for key, item in value.items()},
}


class SdkRecord(SimpleNamespace):
    """One SDK model instance: typed fields and extras as attributes, extras also in ``model_extra``.

    ``model_dump`` answers as pydantic's does for the options the loop passes (``mode``,
    ``exclude_none``, ``exclude_unset``, ``by_alias``, ``warnings``): typed fields first, then
    extras, then any attribute set after construction (the loop sets ``stop_details``).
    """

    def model_dump(self, *, exclude_none: bool = False, exclude_unset: bool = False, by_alias: bool = False,
                   **_options: Any) -> dict[str, Any]:
        options = {"exclude_none": exclude_none, "exclude_unset": exclude_unset, "by_alias": by_alias}
        state = self.__dict__
        kind = state.get("_kind", "")
        aliases = sdk_shapes.ALIASES.get(kind, {})
        typed = {aliases.get(wire, wire) for wire in sdk_shapes.KINDS.get(kind, {})}
        skip = typed - state.get("_fields_set", frozenset()) if exclude_unset else set()
        wire_of = {attr: wire for wire, attr in aliases.items()} if by_alias else {}
        out: dict[str, Any] = {}
        for key, value in state.items():
            if key == "model_extra" or key.startswith("_") or key in skip or (exclude_none and value is None):
                continue
            out[wire_of.get(key, key)] = _dump(value, options)
        for key, value in state.get("model_extra", {}).items():
            if key not in out and not (exclude_none and value is None):
                out[key] = _dump(value, options)
        return out

    def to_dict(self, **options: Any) -> dict[str, Any]:
        """The SDKs' ``to_dict``: the wire form, unset fields left out."""
        return self.model_dump(by_alias=True, exclude_unset=True, **options)


class _ResponseRecord(SdkRecord):
    """``openai.types.responses.Response``: ``output_text`` is a property, never a field."""

    @property
    def output_text(self) -> str:
        return "".join(
            str(getattr(part, "text", "") or "")
            for item in (self.output or []) if getattr(item, "type", None) == "message"
            for part in (getattr(item, "content", None) or []) if getattr(part, "type", None) == "output_text"
        )


_RECORD_CLASSES: dict[str, type[SdkRecord]] = {"openai.Response": _ResponseRecord}


def _kind_for(target: str, raw: Mapping[str, Any]) -> str:
    if not target.startswith("union:"):
        return target
    table = sdk_shapes.UNIONS[target.removeprefix("union:")]
    return table.get(raw.get("type")) or next(iter(table.values()))


def _typed(spec: tuple[str, str], value: Any) -> Any:
    target, arity = spec
    if arity == "list":
        return [sdk_record(target, item) for item in value] if isinstance(value, list) else value
    return sdk_record(target, value)


def sdk_record(target: str, raw: Any) -> Any:
    """``raw`` JSON as the SDK builds ``target`` — a model or ``union:<name>`` of
    :mod:`agent.transports.sdk_shapes` (``sdk_shapes.ROOTS`` names each wire's roots).
    Anything that is not a JSON object is returned as it came, as the SDKs keep it."""
    if not isinstance(raw, Mapping):
        return raw
    kind = _kind_for(target, raw)
    fields = sdk_shapes.KINDS[kind]
    aliases = sdk_shapes.ALIASES.get(kind, {})
    values: dict[str, Any] = {aliases.get(wire, wire): None for wire in fields}
    extra: dict[str, Any] = {}
    for key, value in raw.items():
        key = str(key)
        if key not in fields:
            extra[key] = value
            continue
        spec = fields[key]
        values[aliases.get(key, key)] = value if spec is None else _typed(spec, value)
    cls = _RECORD_CLASSES.get(kind, SdkRecord)
    record = cls(**values)
    for key, value in extra.items():
        if key.isidentifier() and not key.startswith("_") and key != "model_extra" and not hasattr(cls, key):
            setattr(record, key, value)
    record.model_extra = extra
    record._kind = kind
    record._fields_set = frozenset(aliases.get(str(key), str(key)) for key in raw)
    return record


def completion_record(payload: Mapping[str, Any]) -> Any:
    """A parsed ``chat.completion`` JSON body as the SDK's ``ChatCompletion``."""
    return sdk_record(sdk_shapes.ROOTS["chat.completion"], payload)


# ── transport ────────────────────────────────────────────────────────────────


def openai_error_body(text: str) -> Any:
    """The ``openai`` SDK's ``APIStatusError.body``: the ``error`` object, else the whole JSON."""
    try:
        parsed = json.loads(text) if text else None
    except ValueError:
        return None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        return error if isinstance(error, dict) else parsed
    return None


def _error_detail(body: Any, text: str) -> str:
    """The provider's own error message, wherever its error JSON nests it."""
    for candidate in (body, body.get("error") if isinstance(body, dict) else None):
        if isinstance(candidate, dict) and isinstance(candidate.get("message"), str):
            return candidate["message"]
    return text


class HttpCore:
    """What every SDK-free client shares: its ``httpx`` client, redaction and the non-2xx error.

    An injected ``http_client`` (the loop's keep-alive client) is used as-is and kept on
    ``_client``, where the served-model header capture and the socket abort look for it.
    """

    #: How this SDK shapes ``APIStatusError.body`` from the error response text.
    error_body: Callable[[str], Any] = staticmethod(openai_error_body)

    def __init__(self, *, api_key: Any, base_url: Any, timeout: Any, http_client: httpx.Client | None,
                 default_headers: Mapping[str, Any] | None, default_query: Mapping[str, Any] | None) -> None:
        self.api_key = api_key
        self.base_url = str(base_url or "").rstrip("/")
        self._default_headers = dict(default_headers or {})
        self._default_query = dict(default_query or {})
        self._timeout = timeout
        self._client = http_client or httpx.Client(
            timeout=timeout if timeout is not None else httpx.Timeout(600.0, connect=10.0)
        )
        self.is_closed = False

    def close(self) -> None:
        self.is_closed = True
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def _secret(self) -> str:
        # Entra ID / rotating credentials hand the SDK a zero-arg token callable.
        key = self.api_key() if callable(self.api_key) else self.api_key
        return str(key or "")

    def _redact(self, text: str) -> str:
        from agent_runtime.redaction import redact_transport_text

        return redact_transport_text(text, secrets=(self._secret(),))

    def send(self, path: str, *, body: dict, headers: Mapping[str, Any], query: Mapping[str, Any] | None,
             timeout: Any) -> httpx.Response:
        """POST ``body`` and return the open (streaming) response; a non-2xx answer raises."""
        effective_timeout = timeout if timeout is not None else self._timeout
        request = self._client.build_request(
            "POST", self.base_url + path, json=body, headers={str(k): str(v) for k, v in headers.items()},
            params={**self._default_query, **(query or {})} or None,
            timeout=effective_timeout if effective_timeout is not None else httpx.USE_CLIENT_DEFAULT,
        )
        # The SDKs' request loop, minus its own retries (the loop's callers own retrying): a timeout
        # is an APITimeoutError, any other failure to get an answer an APIConnectionError, each raised
        # from the original error.
        try:
            response = self._client.send(request, stream=True)
        except httpx.TimeoutException as err:
            raise APITimeoutError(request=request) from err
        except Exception as err:
            raise APIConnectionError(request=request) from err
        if not 200 <= response.status_code < 300:
            self._raise_for_status(response)
        return response

    @staticmethod
    def read_json(response: httpx.Response) -> dict:
        """A non-streamed body as the JSON object it must be."""
        try:
            payload = json.loads(response.read())
        except ValueError as exc:
            raise MalformedSSE("provider returned a non-JSON body") from exc
        finally:
            response.close()
        if not isinstance(payload, dict):
            raise MalformedSSE("provider body must be a JSON object")
        return payload

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            text = response.read()[:_ERROR_BODY_BYTES].decode("utf-8", errors="replace")
        finally:
            response.close()
        body = self.error_body(text)
        raise ProviderHTTPError(
            response.status_code,
            message=self._redact(f"HTTP {response.status_code}: {_error_detail(body, text)[:500]}"),
            body=body, response=response,
        )


class SdkStream:
    """The SDKs' ``Stream`` surface: iterate typed events, ``response``, ``close()``, context manager."""

    def __init__(self, response: httpx.Response, events: Callable[[httpx.Response], Iterator[Any]]) -> None:
        self.response = response
        self._events = events

    def __iter__(self) -> Iterator[Any]:
        try:
            yield from self._events(self.response)
        finally:
            self.response.close()

    def close(self) -> None:
        self.response.close()

    def __enter__(self) -> "SdkStream":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def openai_stream_events(target: str, redact: Callable[[str], str]) -> Callable[[httpx.Response], Iterator[Any]]:
    """The ``openai`` SDK's ``Stream``: ``[DONE]`` ends it, an ``error`` key raises, else a typed event."""

    def events(response: httpx.Response) -> Iterator[Any]:
        for _event, data in iter_sse_events(response.iter_lines()):
            if (data or "").startswith("[DONE]"):
                return
            chunk = sse_json(data, what="provider")
            if chunk.get("error"):
                body = chunk["error"] if isinstance(chunk["error"], dict) else chunk
                raise ProviderStreamError(redact(f"provider stream error: {chunk['error']}"), body=body)
            yield sdk_record(target, chunk)

    return events


class SdkFreeClient(HttpCore):
    """``openai.OpenAI``'s ``chat.completions`` and ``responses`` surfaces over raw ``httpx``.

    Built from the SDK's own constructor kwargs (``organization`` / ``project`` become the
    SDK's headers; retry and other SDK-only knobs are accepted and ignored — retries belong to
    the loop).
    """

    def __init__(
        self, *, api_key: Any = "", base_url: Any = "", default_headers: Mapping[str, str] | None = None,
        timeout: Any = None, http_client: httpx.Client | None = None, organization: str | None = None,
        project: str | None = None, default_query: Mapping[str, Any] | None = None, **_sdk_only: Any,
    ) -> None:
        headers = {str(k): str(v) for k, v in (default_headers or {}).items()}
        if organization:
            headers.setdefault("OpenAI-Organization", organization)
        if project:
            headers.setdefault("OpenAI-Project", project)
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout, http_client=http_client,
                         default_headers=headers, default_query=default_query)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat_completion))
        from agent.transports.httpx_responses import ResponsesResource

        self.responses = ResponsesResource(self)

    @property
    def audio(self) -> Any:
        """The SDK's audio surface (speech, transcriptions) has no SDK-free client."""
        raise SdkFreeWireUnavailable("OpenAI audio (speech / transcription) needs a provider SDK, and this "
                                     "profile ships none (agent.provider_sdks: false)")

    def post(self, path: str, *, stream: bool, targets: tuple[str, str], extra_headers: Mapping[str, Any] | None = None,
             extra_body: Mapping[str, Any] | None = None, extra_query: Mapping[str, Any] | None = None,
             timeout: Any = None, **params: Any) -> Any:
        """One ``openai`` SDK ``create``: the typed body, or a :class:`SdkStream` of typed events.

        ``targets`` is ``(body, event)``: the models the answer and each stream event build.
        ``None`` params are left out of the body (the SDK would send them as ``null``).
        """
        body = {key: value for key, value in params.items() if value is not None}
        if extra_body:
            body.update(extra_body)
        if stream:
            body["stream"] = True
        # ``Accept: application/json`` on streams too, as the SDK sends it; ``stream: true`` asks for SSE.
        headers = {"Content-Type": "application/json", "Accept": "application/json", **self._default_headers}
        if bearer := self._secret():
            headers["Authorization"] = f"Bearer {bearer}"
        headers.update({str(k): str(v) for k, v in (extra_headers or {}).items()})
        response = self.send(path, body=body, headers=headers, query=extra_query, timeout=timeout)
        if stream:
            return SdkStream(response, openai_stream_events(targets[1], self._redact))
        return sdk_record(targets[0], self.read_json(response))

    def _create_chat_completion(self, *, stream: bool = False, **kwargs: Any) -> Any:
        targets = (sdk_shapes.ROOTS["chat.completion"], sdk_shapes.ROOTS["chat.completion.chunk"])
        return self.post("/chat/completions", stream=stream, targets=targets, **kwargs)


class AsyncSdkFreeClient:
    """``openai.AsyncOpenAI``'s ``chat.completions`` over a :class:`SdkFreeClient`, run off-loop.

    The auxiliary client's async lane rebuilds an ``AsyncOpenAI`` twin from a sync client; the
    SDK-free client has none, so its calls run on a worker thread (as the auxiliary client's
    native wrappers do). ``_real_client`` is the leaf, so cache eviction by leaf reaches it.
    """

    def __init__(self, sync_client: SdkFreeClient) -> None:
        self._real_client = sync_client
        self.api_key = sync_client.api_key
        self.base_url = sync_client.base_url
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat_completion))

    async def _create_chat_completion(self, **kwargs: Any) -> Any:
        import asyncio

        return await asyncio.to_thread(self._real_client.chat.completions.create, **kwargs)

    async def close(self) -> None:
        self._real_client.close()
