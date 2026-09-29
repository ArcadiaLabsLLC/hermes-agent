"""The Launcher's app functions as agent tools (embedded Harness Stage 7, harness half).

The Launcher owns a set of app functions — list the library, open a page, read
or change a setting — behind ONE dispatcher that applies permission, reach,
gate, argument validation and confirmation (launcher
``docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md``, "Stage 7
launcher half as landed"). This module is the agent's side of that door:

* at the start of a chat turn that arrived over the serve connection, ask the
  Launcher ``launcher.app_functions.list`` on that connection;
* register one tool per entry (name, description and parameters exactly as
  given) in the :data:`APP_FUNCTIONS_TOOLSET` toolset;
* a tool call is a JSON-RPC REQUEST on the same connection whose method is the
  entry's ``method`` and whose ``params._meta.origin`` is ``local`` or
  ``paired_device`` — who started the turn. The Launcher refuses a request
  with no origin, so every call states one.

Policy is the Launcher's, never re-decided here: an entry the Launcher refuses
comes back as a JSON-RPC error carrying ``data.refusal``, and the tool returns
that refusal to the model as its result.

The request lane is :class:`ClientRequests`: server→client requests on the
serve NDJSON wire, each answered by a response frame with the same ``id``
(``handle_message`` routes those frames to :func:`resolve_response`). Ids are
``lrq-<12 hex>`` strings, so they never collide with the Launcher's own ids.

A connection that never answers the list (an older Launcher, a CLI client)
is latched as ``unanswered`` after one probe and not asked again, so a turn
pays that probe once per connection, not once per turn.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

__layer__ = "stores"

logger = logging.getLogger(__name__)

__all__ = [
    "APP_FUNCTIONS_TOOLSET",
    "CALL_TIMEOUT_SECONDS",
    "CLIENT_REQUESTS",
    "LIST_METHOD",
    "LIST_TIMEOUT_SECONDS",
    "ORIGIN_LOCAL",
    "ORIGIN_PAIRED_DEVICE",
    "AppFunctionEntry",
    "app_function_tools_registered",
    "ClientRequestFailed",
    "ClientRequests",
    "LauncherLink",
    "bind_launcher_link",
    "call_app_function",
    "current_launcher_link",
    "is_response_frame",
    "refresh_app_function_tools",
    "reset_launcher_link",
    "resolve_response",
]

#: The toolset every app-function tool registers under.
APP_FUNCTIONS_TOOLSET = "launcher_app_functions"
#: The discovery request; its result is ``{"tools": [entry, ...]}``.
LIST_METHOD = "launcher.app_functions.list"
#: Every app-function method lives under this namespace on the Launcher.
METHOD_PREFIX = "launcher."
ORIGIN_LOCAL = "local"
ORIGIN_PAIRED_DEVICE = "paired_device"
_ORIGINS = frozenset({ORIGIN_LOCAL, ORIGIN_PAIRED_DEVICE})
#: The list is answered from memory in the Launcher; a connection silent this
#: long has no responder and is latched ``unanswered``.
LIST_TIMEOUT_SECONDS = 3.0
#: A ``confirm`` entry waits for the operator's approval card, so a call gets
#: the clarify-sized wait rather than the list's.
CALL_TIMEOUT_SECONDS = 300.0
#: JSON-RPC code this side answers with when the Launcher never replied.
_NO_REPLY_CODE = -32000
#: The client has no handler for the method: as final as silence.
_METHOD_NOT_FOUND = -32601


class ClientRequestFailed(Exception):
    """The client answered with an error, or never answered."""

    def __init__(self, code: int, message: str, data: Any = None, *, timed_out: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data
        #: True when nothing answered at all (as opposed to an error reply).
        self.timed_out = timed_out


class _Pending:
    __slots__ = ("event", "frame", "sink")

    def __init__(self, sink: Any) -> None:
        self.sink = sink
        self.event = threading.Event()
        self.frame: dict[str, Any] | None = None


def is_response_frame(frame: Any) -> bool:
    """A JSON-RPC response: an ``id`` and a ``result``/``error``, and no ``method``."""

    return (
        isinstance(frame, dict)
        and "method" not in frame
        and "id" in frame
        and ("result" in frame or "error" in frame)
    )


class ClientRequests:
    """Server→client requests on the serve wire, settled by id on the asking sink."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._open: dict[str, _Pending] = {}

    def request(self, sink: Any, method: str, params: Mapping[str, Any], *, timeout: float) -> dict[str, Any]:
        """Send one request on *sink* and wait for its result (a dict)."""

        request_id = f"lrq-{uuid.uuid4().hex[:12]}"
        pending = _Pending(sink)
        with self._lock:
            self._open[request_id] = pending
        try:
            sink.emit({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)})
            answered = pending.event.wait(timeout)
        finally:
            with self._lock:
                self._open.pop(request_id, None)
        if not answered or pending.frame is None:
            raise ClientRequestFailed(_NO_REPLY_CODE, f"no reply to {method} within {timeout:g}s", timed_out=True)
        return _result_of(pending.frame)

    def resolve(self, frame: Mapping[str, Any], sink: Any) -> bool:
        """Settle the open request *frame* answers. False when nothing on *sink* waits for it."""

        request_id = frame.get("id")
        if not isinstance(request_id, str):
            return False
        with self._lock:
            pending = self._open.get(request_id)
            if pending is None or pending.sink is not sink:
                return False
            self._open.pop(request_id, None)
        pending.frame = dict(frame)
        pending.event.set()
        return True

    def open_count(self) -> int:
        with self._lock:
            return len(self._open)


def _result_of(frame: Mapping[str, Any]) -> dict[str, Any]:
    error = frame.get("error")
    if error is not None:
        body = error if isinstance(error, dict) else {}
        code = body.get("code")
        raise ClientRequestFailed(
            code if isinstance(code, int) else _NO_REPLY_CODE,
            str(body.get("message") or "the client answered with an error"),
            body.get("data"),
        )
    result = frame.get("result")
    return result if isinstance(result, dict) else {}


#: The one request lane of this process.
CLIENT_REQUESTS = ClientRequests()


def resolve_response(frame: Mapping[str, Any], sink: Any) -> bool:
    """Route one inbound response frame (``handle_message``'s entry point)."""

    return CLIENT_REQUESTS.resolve(frame, sink)


@dataclass(frozen=True, slots=True)
class LauncherLink:
    """Where this turn's app-function requests go, and who started the turn."""

    sink: Any
    origin: str

    def __post_init__(self) -> None:
        if self.origin not in _ORIGINS:
            raise ValueError(f"origin must be one of {sorted(_ORIGINS)}, not {self.origin!r}")


_link: contextvars.ContextVar[LauncherLink | None] = contextvars.ContextVar(
    "launcher_app_function_link", default=None
)


def current_launcher_link() -> LauncherLink | None:
    return _link.get()


def bind_launcher_link(link: LauncherLink | None) -> contextvars.Token:
    return _link.set(link)


def reset_launcher_link(token: contextvars.Token) -> None:
    _link.reset(token)


@dataclass(frozen=True, slots=True)
class AppFunctionEntry:
    """One entry of the Launcher's agent tool projection."""

    name: str
    method: str
    description: str
    parameters: dict[str, Any]

    @classmethod
    def parse(cls, raw: Any) -> AppFunctionEntry | None:
        """The entry, or None when the Launcher sent something no tool can be built from."""

        if not isinstance(raw, dict):
            return None
        name, method = raw.get("name"), raw.get("method")
        parameters = raw.get("parameters")
        if not (isinstance(name, str) and name and isinstance(method, str)):
            return None
        if not method.startswith(METHOD_PREFIX) or method == LIST_METHOD:
            return None
        if not isinstance(parameters, dict):
            parameters = {"type": "object", "properties": {}}
        description = raw.get("description")
        return cls(name, method, description if isinstance(description, str) else "", parameters)

    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


def call_app_function(entry: AppFunctionEntry, args: Mapping[str, Any]) -> str:
    """Run one app function over this turn's link; the tool result as JSON text."""

    link = current_launcher_link()
    if link is None:
        return json.dumps({"error": "no Launcher is attached to this turn; app functions are unavailable"})
    params = {key: value for key, value in dict(args or {}).items() if key != "_meta"}
    params["_meta"] = {"origin": link.origin}
    try:
        result = CLIENT_REQUESTS.request(link.sink, entry.method, params, timeout=CALL_TIMEOUT_SECONDS)
    except ClientRequestFailed as exc:
        refusal = exc.data.get("refusal") if isinstance(exc.data, dict) else None
        return json.dumps({"error": exc.message, "code": exc.code, "refusal": refusal}, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False, default=str)


class _ToolsetState:
    """What the registry holds for the toolset, and which sinks never answered."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.registered: dict[str, AppFunctionEntry] = {}
        self.unanswered: dict[int, Any] = {}


_state = _ToolsetState()


def app_function_tools_registered() -> bool:
    """Does the registry hold any app-function tool? (The chat lane adds the
    toolset only then; ``registry_epoch`` moves whenever this answer does.)"""

    with _state.lock:
        return bool(_state.registered)


def _link_available() -> bool:
    return current_launcher_link() is not None


def _sync_registry(entries: list[AppFunctionEntry]) -> None:
    """Make the registry hold exactly *entries*; untouched when nothing changed.

    Idempotence is the point: a re-registration bumps ``registry_epoch``, which
    every chat-lane bundle memo keys on, so re-registering the same list each
    turn would rebuild every bundle every turn.
    """

    from tools.registry import no_cache_check_fn, registry

    wanted = {entry.name: entry for entry in entries}
    if wanted == _state.registered:
        return
    for name in set(_state.registered) - set(wanted):
        registry.deregister(name)
    check = no_cache_check_fn(_link_available)
    for name, entry in wanted.items():
        if _state.registered.get(name) == entry:
            continue
        registry.register(
            name=name,
            toolset=APP_FUNCTIONS_TOOLSET,
            schema=entry.schema(),
            handler=lambda args, _entry=entry, **_kw: call_app_function(_entry, args),
            check_fn=check,
            description=entry.description,
        )
    _state.registered = wanted


def refresh_app_function_tools(link: LauncherLink) -> list[str] | None:
    """Ask *link*'s connection for its app functions and register them as tools.

    Returns the tool names, or None when the list failed. A connection that
    stayed silent or has no such method is latched and not asked again; an
    error reply from a real responder is not latched. A malformed entry is skipped and logged,
    never registered half-built.
    """

    with _state.lock:
        if id(link.sink) in _state.unanswered:
            return None
    try:
        result = CLIENT_REQUESTS.request(link.sink, LIST_METHOD, {"_meta": {"origin": link.origin}},
                                         timeout=LIST_TIMEOUT_SECONDS)
    except ClientRequestFailed as exc:
        logger.info("launcher app functions unavailable on this connection: %s", exc.message)
        if exc.timed_out or exc.code == _METHOD_NOT_FOUND:
            with _state.lock:
                _state.unanswered[id(link.sink)] = link.sink
        return None
    raw_tools = result.get("tools")
    entries = []
    for raw in raw_tools if isinstance(raw_tools, list) else []:
        entry = AppFunctionEntry.parse(raw)
        if entry is None:
            logger.warning("launcher app function entry skipped (no name/method under launcher.): %r", raw)
            continue
        entries.append(entry)
    with _state.lock:
        _sync_registry(entries)
    return [entry.name for entry in entries]


def _reset_for_tests() -> None:
    from tools.registry import registry

    with _state.lock:
        for name in _state.registered:
            registry.deregister(name)
        _state.registered = {}
        _state.unanswered.clear()
