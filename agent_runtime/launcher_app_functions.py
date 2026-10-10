"""The Launcher's app functions as agent tools (embedded Harness Stage 7, harness half).

The Launcher owns a set of app functions — list the library, open a page, read
or change a setting — behind ONE dispatcher that applies permission, reach,
gate, argument validation and confirmation (launcher
``docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md``, "Stage 7
launcher half as landed"). This module is the agent's side of that door:

* at the start of a chat turn that arrived over the serve connection, ask the
  Launcher ``launcher.app_functions.list`` on that connection — ONCE per
  admitted connection (the catalog is cached by sink and forgotten when the
  connection closes or the client re-declares, so a reconnect lists afresh);
* register one tool per entry (name, description and parameters exactly as
  given) in the :data:`APP_FUNCTIONS_TOOLSET` toolset;
* a tool call is a JSON-RPC REQUEST on the same connection whose method is the
  entry's ``method`` and whose ``params._meta.origin`` is ``local`` or
  ``paired_device`` — who started the turn. The Launcher refuses a request
  with no origin, so every call states one.

Policy is the Launcher's, never re-decided here: an entry the Launcher refuses
comes back as a JSON-RPC error carrying ``data.refusal``, and the tool returns
that refusal to the model as its result, read through
:mod:`agent_runtime.launcher_app_function_answers`. The runtime offers exactly
what the Launcher listed — a set the Launcher keeps behind a gate (the Studio
functions) is absent from the list while the gate is closed, and nothing here
knows those names, so no runtime setting can offer them.

The request lane is :mod:`agent_runtime.launcher_client_requests`: server→client
requests on the serve NDJSON wire, each answered by a response frame with the
same ``id``.

Only a connection that declared it answers ``launcher.`` requests
(``runtime.client.capabilities {answers: ["launcher."]}``, keyed by the serve
owner — ``stdio`` or the socket connection's key) is ever asked; any other
client never sees the frame. A declared connection that still never answers
the list is latched ``unanswered`` after one probe and not asked again.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .launcher_app_function_answers import refusal_result, success_result
from .launcher_client_requests import _METHOD_NOT_FOUND, CLIENT_REQUESTS, ClientRequestFailed

__layer__ = "stores"

logger = logging.getLogger(__name__)

__all__ = [
    "APP_FUNCTIONS_TOOLSET",
    "CALL_TIMEOUT_SECONDS",
    "LIST_METHOD",
    "LIST_TIMEOUT_SECONDS",
    "ORIGIN_LOCAL",
    "ORIGIN_PAIRED_DEVICE",
    "AppFunctionEntry",
    "answers_launcher_requests",
    "latest_answerer",
    "declare_answerer",
    "app_function_tools_registered",
    "app_function_tool_scope",
    "app_function_guidance_lines",
    "always_loaded_app_function_tools",
    "LauncherLink",
    "bind_launcher_link",
    "call_app_function",
    "mutating_app_function_tools",
    "current_launcher_link",
    "forget_launcher_connection",
    "refresh_app_function_tools",
    "reset_launcher_link",
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
#: JSON-RPC code of this side's own ``no_launcher`` answer.
_NO_LAUNCHER_CODE = -32000
@dataclass(frozen=True, slots=True)
class LauncherLink:
    """Where this turn's app-function requests go, and who started the turn."""

    sink: Any
    origin: str

    def __post_init__(self) -> None:
        if self.origin not in _ORIGINS:
            raise ValueError(f"origin must be one of {sorted(_ORIGINS)}, not {self.origin!r}")

    def request(self, method: str, args: Mapping[str, Any]) -> dict[str, Any]:
        """The connection owns origin and deadline; tool arguments cannot replace them."""
        if not method.startswith(METHOD_PREFIX):
            raise ValueError("Not an app function")
        params = {key: value for key, value in args.items() if key != "_meta"}
        params["_meta"] = {"origin": self.origin}
        from .launcher_invocation import current_invocation
        invocation = current_invocation()
        if invocation is not None:
            params["_meta"]["invocation"] = dict(invocation)
        return CLIENT_REQUESTS.request(self.sink, method, params,
            timeout=LIST_TIMEOUT_SECONDS if method == LIST_METHOD else CALL_TIMEOUT_SECONDS)


_link: contextvars.ContextVar[LauncherLink | None] = contextvars.ContextVar(
    "launcher_app_function_link", default=None
)


def current_launcher_link() -> LauncherLink | None:
    return _link.get()


def launcher_link_of(requester: Any) -> LauncherLink | None:
    """The link behind an ``RpcContext.launcher_request`` (``link.request``).

    The method lane hands handlers the bound ``request`` callable, not the
    link; this is the one place that turns it back into the link, so a handler
    can bind it for code that reads :func:`current_launcher_link`.
    """

    owner = getattr(requester, "__self__", None)
    return owner if isinstance(owner, LauncherLink) else None


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
    #: The Launcher waits for the person's approval card before running it.
    requires_confirmation: bool = False
    #: The Launcher's reach enum: ``localOnly`` or ``pairedDevice``.
    reach: str = ""
    #: Host-owned discovery preference; never a permission grant.
    always_loaded: bool = False
    #: Host-owned one-line WHEN rule, rendered in the prompt only while this
    #: tool is in the session's list (``plugins/eternia-harness`` tool guidance).
    guidance: str = ""
    #: The Launcher's per-entry ``read_only`` mark (sent since lane mc-a, 2026-10-02):
    #: ``True`` reads, ``False`` mutates, ``None`` when an older Launcher did not send it.
    read_only: bool | None = None

    @property
    def mutating(self) -> bool:
        """The mutation mark ``read_only`` mode blocks and the HUD labels: the Launcher's
        ``read_only is False``; an entry without the mark falls back to its
        ``requires_confirmation`` (the only mutation signal that wire carried)."""

        if self.read_only is None:
            return self.requires_confirmation
        return self.read_only is False

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
        reach = raw.get("reach")
        read_only = raw.get("read_only")
        return cls(name, method, description if isinstance(description, str) else "", parameters,
                   requires_confirmation=raw.get("requires_confirmation") is True,
                   reach=reach if isinstance(reach, str) else "",
                   always_loaded=raw.get("always_loaded") is True,
                   guidance=" ".join(str(raw.get("guidance")).split())
                   if isinstance(raw.get("guidance"), str) else "",
                   read_only=read_only if isinstance(read_only, bool) else None)

    def schema(self) -> dict[str, Any]:
        """The tool schema: the Launcher's name, description and parameters, with
        the one fact the model must know before calling — that a ``confirm``
        entry waits on the person — appended to the description."""

        description = self.description
        if self.requires_confirmation:
            description = (f"{description} Needs the person's approval at the Launcher before it "
                           "runs; the call waits for their answer.").strip()
        return {"name": self.name, "description": description, "parameters": self.parameters}


def call_app_function(entry: AppFunctionEntry, args: Mapping[str, Any]) -> str:
    """Run one app function over this turn's link; the tool result as JSON text."""

    link = current_launcher_link()
    if link is None:
        answer = refusal_result(refusal="no_launcher", code=_NO_LAUNCHER_CODE,
                                message="no Launcher is attached to this turn; app functions are unavailable",
                                requires_confirmation=entry.requires_confirmation)
        return json.dumps(answer, ensure_ascii=False)
    try:
        result = link.request(entry.method, args or {})
    except ClientRequestFailed as exc:
        refusal = exc.data.get("refusal") if isinstance(exc.data, dict) else None
        if refusal is None and exc.timed_out:
            refusal = "no_reply"
        answer = refusal_result(refusal=refusal, code=exc.code, message=exc.message,
                                requires_confirmation=entry.requires_confirmation)
        return json.dumps(answer, ensure_ascii=False, default=str)
    return json.dumps(success_result(result, requires_confirmation=entry.requires_confirmation),
                      ensure_ascii=False, default=str)


class _ToolsetState:
    """What the registry holds for the toolset, which serve owners declared they answer
    ``launcher.`` requests, which sinks never answered, and each answering
    connection's catalog (its last list, kept until the connection goes)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.registered: dict[str, AppFunctionEntry] = {}
        #: Declaring owners in declaration order (a re-declaration moves to the end).
        self.answerers: dict[str, None] = {}
        self.unanswered: dict[int, Any] = {}
        #: Sink, entries and an opaque memo token for this catalog's lifetime.
        self.catalog: dict[int, tuple[Any, list[AppFunctionEntry], object]] = {}


_state = _ToolsetState()


def declare_answerer(owner: str, answers: bool) -> None:
    """Record whether the serve owner *owner* (``stdio`` or a connection key) answers
    ``launcher.`` requests (``runtime.client.capabilities``)."""

    with _state.lock:
        _state.answerers.pop(owner, None)
        if answers:
            _state.answerers[owner] = None
        # A declaration is a client announcing itself: the catalogs and the
        # silence latches describe connections as they were before it, and a
        # Launcher that restarted behind the same pipe lists afresh.
        _state.catalog.clear()
        _state.unanswered.clear()


def answers_launcher_requests(owner: str) -> bool:
    with _state.lock:
        return owner in _state.answerers


def latest_answerer(owners: Iterable[str]) -> str | None:
    """The owner among *owners* that most recently declared it answers ``launcher.``
    requests, or ``None`` when none of them did."""

    candidates = set(owners)
    with _state.lock:
        declared = [owner for owner in _state.answerers if owner in candidates]
    return declared[-1] if declared else None


def app_function_tools_registered() -> bool:
    """Does the registry hold any app-function tool? (The chat lane adds the
    toolset only then; ``registry.generation`` moves whenever this answer does.)"""

    with _state.lock:
        return bool(_state.registered)


def app_function_tool_scope() -> tuple[object, str] | None:
    """Memo boundary for connection-bound availability and discovery preferences.

    No wire read: the catalog is already fetched once per admitted connection.
    A linked and an unlinked construction must never share an assembled list.
    Re-declaration replaces the token even if another connection already synced
    the same registry entries; a retired catalog cannot lend its memo to a new one.
    """
    link = current_launcher_link()
    if link is None:
        return None
    with _state.lock:
        held = _state.catalog.get(id(link.sink))
        return (held[2] if held is not None and held[0] is link.sink else None, link.origin)


def always_loaded_app_function_tools() -> frozenset[str]:
    """This connection's host-declared eager tools, within its origin's reach.

    Read the bound link's catalog, never the process-global last registered list.
    Toolset admission and the Launcher's dispatcher still decide whether a call
    is available and allowed; this only changes search classification.
    """
    link = current_launcher_link()
    if link is None:
        return frozenset()
    with _state.lock:
        held = _state.catalog.get(id(link.sink))
        if held is None or held[0] is not link.sink:
            return frozenset()
        return frozenset(entry.name for entry in held[1] if entry.always_loaded and
                         (link.origin == ORIGIN_LOCAL or entry.reach == "pairedDevice"))


def app_function_guidance_lines(tool_names: Iterable[str]) -> list[str]:
    """The host's WHEN rules for the app-function tools among *tool_names*, in
    registration order, each text once.

    Read from the registered entries — the set this process offers — so a rule
    renders only beside a tool the model can actually call; the tool-names gate
    is the caller's (the prompt section renders for THIS session's list).
    """

    wanted = {str(name) for name in tool_names}
    lines: list[str] = []
    with _state.lock:
        for name, entry in _state.registered.items():
            if name in wanted and entry.guidance and entry.guidance not in lines:
                lines.append(entry.guidance)
    return lines


def mutating_app_function_tools() -> frozenset[str]:
    """The registered tools the Launcher marks mutating (:attr:`AppFunctionEntry.mutating`:
    its ``read_only is False``) — ``read_only`` mode blocks them (``tool_permissions``) and
    the HUD labels them (``tool_visibility._mutating_tools``)."""

    with _state.lock:
        return frozenset(name for name, entry in _state.registered.items() if entry.mutating)


def forget_launcher_connection(sink: Any) -> None:
    """The connection behind *sink* is gone: drop its catalog and silence latch,
    fail its open requests now, and — when no catalog is left — empty the
    toolset, so a turn with no Launcher is offered nothing stale."""

    with _state.lock:
        _state.catalog.pop(id(sink), None)
        _state.unanswered.pop(id(sink), None)
        if not _state.catalog:
            _sync_registry([])
    abandoned = CLIENT_REQUESTS.abandon(sink)
    if abandoned:
        logger.info("launcher connection closed with %d app-function request(s) open; failed, not resent", abandoned)


def _link_available() -> bool:
    return current_launcher_link() is not None


def _sync_registry(entries: list[AppFunctionEntry]) -> None:
    """Make the registry hold exactly *entries*; untouched when nothing changed.

    Idempotence is the point: a re-registration bumps ``registry.generation``, which
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
    """Make the registry hold *link*'s connection's app functions as tools.

    The list is asked ONCE per connection: a catalog already held for this sink
    is re-synced into the registry (idempotent, no wire) and its names
    returned. Returns the tool names, or None when the list failed. A
    connection that stayed silent or has no such method is latched and not
    asked again; an error reply from a real responder is not latched. A
    malformed entry is skipped and logged, never registered half-built.
    """

    with _state.lock:
        if id(link.sink) in _state.unanswered:
            return None
        held = _state.catalog.get(id(link.sink))
        if held is not None:
            _sync_registry(held[1])
            return [entry.name for entry in held[1]]
    try:
        result = link.request(LIST_METHOD, {})
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
        _state.catalog[id(link.sink)] = (link.sink, entries, object())
        _sync_registry(entries)
    return [entry.name for entry in entries]


def _reset_for_tests() -> None:
    from tools.registry import registry

    with _state.lock:
        for name in _state.registered:
            registry.deregister(name)
        _state.registered = {}
        _state.answerers.clear()
        _state.unanswered.clear()
        _state.catalog.clear()
