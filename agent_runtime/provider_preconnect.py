"""Open the provider connection on the prewarm thread, not on the first turn.

h-turn1 A4 (``docs/agent-runtime-harness/planned/turn-latency-h-turn1-2026-10-05.md``).
A resident actor's OpenAI client rides upstream's process-shared keepalive
transport (``agent/process_bootstrap.py::build_keepalive_http_client``), so a
chat's first turn opens a connection. The FIRST one in the process pays the
resolver, the first full TLS handshake and the certificate chain (262-1,454 ms
on record, every later one 21-56 ms). One ``HEAD`` to the provider's base URL
through the actor's OWN transport, right after the prewarm built it, moves that
first-in-process cost here.

The request carries the actor's IDENTITY headers (``User-Agent``, ``originator``
-- :data:`IDENTITY_HEADERS`) and nothing else. A bare ``HEAD`` is what the edge
in front of ``chatgpt.com`` challenges: it answered ``403`` with
``cf-mitigated: challenge`` and ``Connection: close`` (probed 2026-10-05), so
httpcore dropped the connection it had just opened and turn 1 still handshook
(``request_built -> tls_done`` 712 ms on the 23:16Z Neko chat, 3 s after a
``status=403`` pre-connect). With the identity the edge passes the request to
the origin, which answers ``404 Connection: keep-alive`` and the connection
stays in the pool the turn's per-request client shares
(``agent/process_bootstrap.py::build_keepalive_http_client``). The receipt's
``kept`` says which happened.

h-conn-pool: the request goes through the client the TURN checks out, not
the actor's primary client. A codex / chat-completions turn sends on the
per-request client ``agent._create_request_openai_client`` caches; the pre-connect
builds that client and leaves it cached (released with a reuse reason), so the
connection it warms sits in the pool of the very ``httpx.Client`` the turn's
request rides -- one pool whether or not upstream's process-shared transport
applies (a proxy, a full transport cache and the SDK-free client without a
keep-alive client each give a client its own pool).

h-turn1-conn (2026-10-06): live turn 1 still handshook after a ``kept=1``
pre-connect (Neko ``c1cfc36c`` ``tls_done_ms=1378``, ``3e412f30`` 1070), while
every later turn rode a pooled connection. Turn 1 is the only turn with TWO
requesters on the pool at once: ``agent/turn_context.py::_maybe_title_session_at_turn_start``
starts the title upgrade on a thread before the model request, and the
auxiliary client's keep-alive client mounts the SAME process-shared transport
(``agent/auxiliary_client.py::_openai_http_client_kwargs``). The title thread
reached the pool first (``title_generation`` 14:34:14.413, the turn's TLS done
14:34:14.525) and took the one warm socket. So the pre-connect opens
:data:`PRECONNECT_CONNECTIONS` connections, each ``HEAD`` held open while the
next is sent so the pool cannot hand the first back, and a keep-warm timer
re-uses them every :data:`KEEPWARM_INTERVAL_SECONDS` (under the transport's
20 s ``keepalive_expiry``) until the actor's first request, at most
:data:`KEEPWARM_MAX_REFRESHES` times -- an operator who reads before typing
still finds them warm.

h-prep-contention (2026-10-06): the keep-warm also stops once ANY turn in the process has
sent its request (:func:`note_process_request_sent`, marked with ``request_sent``). Live
19:03 the open's prewarm pass warmed eight actors, and their chains (8 x 15 s, two ``HEAD``
each) fired 30 refreshes in the minute the operator chatted with ONE of them -- three inside
one turn's anchor -> ``request_sent`` window (``elapsed_ms`` up to 667 on a pooled
connection: the thread starved beside the turn). The first-in-process handshake the
pre-connect exists to move has been paid by then, and a chatting operator's own turns keep the
process-shared pool warm.

h-idle-turn (2026-10-07): once the keep-warm has stopped, the pool reaps the last connection 20 s
after a turn, and the first turn after a pause handshook (``conn=new``). The pre-connect remembers
each actor's client, URL and identity (:func:`_remember_idle_target`), and between turns the idle
keeper (``agent_runtime.idle_turn_keeper``) sends ONE ``HEAD`` on the most recently active chat's
connection (:func:`refresh_idle_connection`).

What it does not do: send a body, call a model, or carry a credential (the SDK
and the SDK-free client both add auth per request, never on the ``httpx.Client``,
and :data:`IDENTITY_HEADERS` admits no other header);
change the transport's own ``keepalive_expiry`` (upstream's value, unchanged by
ruling A4-r1 -- the keep-warm re-uses the connections inside it, and stops at
the actor's first request); touch a loopback provider (a local router has
no handshake worth moving). Fail-open: a refusal or a timeout is a receipt, never
an error, and the turn opens its own connection exactly as before.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import threading
import time
import weakref
from typing import Any
from urllib.parse import urlsplit

__layer__ = "policy"

logger = logging.getLogger(__name__)

PRECONNECT_RECEIPT = "persona_chat_actor_prewarm_connect host=%s status=%s kept=%d elapsed_ms=%d"
KEEPWARM_RECEIPT = "persona_chat_actor_prewarm_keepwarm host=%s refresh=%d status=%s kept=%d elapsed_ms=%d"

#: Connections turn 1 needs at once: its model request and its title upgrade.
PRECONNECT_CONNECTIONS = 2

#: Under the shared transport's ``keepalive_expiry`` (20 s,
#: ``agent/process_bootstrap.py::build_keepalive_http_client``).
KEEPWARM_INTERVAL_SECONDS = 15.0

#: About two minutes of an opened chat waiting for its first message.
KEEPWARM_MAX_REFRESHES = 8

#: The only headers the pre-connect copies from the actor's client: who is
#: calling, never on whose account. Lower-case names; matched case-insensitively.
IDENTITY_HEADERS = ("user-agent", "originator")

#: ``profile_timing`` key the prewarm writes when it opened a connection.
PREWARM_CONNECT_MS = "prewarm_connect_ms"

PRECONNECT_TIMEOUT_SECONDS = 3.0

STATUS_NO_CLIENT = "no_client"
STATUS_NO_URL = "no_base_url"
STATUS_LOOPBACK = "skipped_loopback"
STATUS_FAILED = "failed"


#: Set by the first ``request_sent`` in this process; every keep-warm chain stops on it.
_PROCESS_REQUEST_SENT = threading.Event()


def note_process_request_sent() -> None:
    """A turn's request left this process: no actor's keep-warm refreshes again."""

    _PROCESS_REQUEST_SENT.set()


#: API modes whose turn sends on ``agent._create_request_openai_client``'s cached client.
REQUEST_CLIENT_API_MODES = frozenset({"codex_responses", "chat_completions"})


def _turn_client(agent: Any) -> Any:
    """The provider client the turn's request will go through.

    For :data:`REQUEST_CLIENT_API_MODES`, the per-request client, built here and
    released with a reuse reason so the turn's checkout finds it cached; any
    failure falls back to the primary ``agent.client``.
    """

    create = getattr(agent, "_create_request_openai_client", None)
    release = getattr(agent, "_close_request_openai_client", None)
    if str(getattr(agent, "api_mode", "") or "") in REQUEST_CLIENT_API_MODES and callable(create) and callable(release):
        try:
            client = create(reason="prewarm_preconnect")
            release(client, reason="request_complete")
            return client
        except Exception:
            logger.debug("prewarm pre-connect could not check out the request client", exc_info=True)
    return getattr(agent, "client", None)


def _http_client(agent: Any) -> Any:
    """The ``httpx.Client`` under the turn's provider client, or None.

    ``openai.OpenAI._client`` and ``SdkFreeClient._client`` (``agent/transports/
    httpx_client.HttpCore``) are both the client the turn's request goes through.
    """

    try:
        import httpx
    except Exception:
        return None
    http = getattr(_turn_client(agent), "_client", None)
    return http if isinstance(http, httpx.Client) else None


def _base_url(agent: Any) -> str:
    url = str(getattr(agent, "base_url", "") or "").strip()
    if not url:
        url = str(getattr(getattr(agent, "client", None), "base_url", "") or "").strip()
    return url


def _identity_headers(agent: Any) -> dict[str, str]:
    """The actor client's :data:`IDENTITY_HEADERS`, from the first source that has them.

    ``agent._client_kwargs["default_headers"]`` is what every client of the actor
    is built from (the turn's per-request client included); the SDK's own
    ``_custom_headers`` / the SDK-free ``_default_headers`` and the SDK's
    ``user_agent`` cover an actor built some other way.
    """

    client = getattr(agent, "client", None)
    kwargs = getattr(agent, "_client_kwargs", None)
    sources = (
        kwargs.get("default_headers") if isinstance(kwargs, dict) else None,
        getattr(client, "_custom_headers", None),
        getattr(client, "_default_headers", None),
    )
    headers: dict[str, str] = {}
    for source in sources:
        if not isinstance(source, dict):
            continue
        for name, value in source.items():
            key = str(name).lower()
            if key in IDENTITY_HEADERS and key not in headers and isinstance(value, str) and value:
                headers[key] = value
    user_agent = getattr(client, "user_agent", None)
    if "user-agent" not in headers and isinstance(user_agent, str) and user_agent:
        headers["user-agent"] = user_agent
    return headers


def _is_loopback(host: str) -> bool:
    if host in ("localhost", "") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _first_request_seen(agent: Any) -> tuple[int, int]:
    """The actor's request counters: they move when its first turn reaches the provider."""

    return (int(getattr(agent, "session_api_calls", 0) or 0), int(getattr(agent, "_api_call_count", 0) or 0))


def _open_connections(http: Any, url: str, headers: dict[str, str],
                      count: int = PRECONNECT_CONNECTIONS) -> tuple[str, int]:
    """``count`` (:data:`PRECONNECT_CONNECTIONS`) ``HEAD`` requests, each held open until all are answered.

    A held response keeps its connection checked out, so each ``HEAD`` takes a
    connection of its own (an idle one first, then a new one). Returns the first
    status and how many connections the server left open.
    """

    statuses: list[str] = []
    kept = 0
    with contextlib.ExitStack() as held:
        for _ in range(count):
            response = held.enter_context(
                http.stream("HEAD", url, headers=headers, timeout=PRECONNECT_TIMEOUT_SECONDS)
            )
            # Drain the (empty) body through the raw stream: h11 reaches DONE so the
            # close below returns the connection to the pool, while ``read()`` would
            # close -- and free -- it before the next ``HEAD`` is sent.
            for _ in response.stream:
                pass
            statuses.append(str(response.status_code))
            kept += int(str(response.headers.get("connection", "")).strip().lower() != "close")
    return statuses[0], kept


def _keep_warm(agent: Any, http: Any, url: str, host: str, headers: dict[str, str], seen: tuple[int, int],
               refresh: int = 1) -> None:
    """Arm one keep-warm refresh; it re-arms itself until the first request or the cap."""

    def fire() -> None:
        if getattr(http, "is_closed", False) or _first_request_seen(agent) != seen or _PROCESS_REQUEST_SENT.is_set():
            return
        started = time.perf_counter()
        try:
            status, kept = _open_connections(http, url, headers)
        except Exception:
            logger.debug("prewarm keep-warm failed for %s", host, exc_info=True)
            status, kept = STATUS_FAILED, 0
        logger.info(KEEPWARM_RECEIPT, host, refresh, status, kept,
                    max(0, int((time.perf_counter() - started) * 1000)))
        if status != STATUS_FAILED and refresh < KEEPWARM_MAX_REFRESHES:
            _keep_warm(agent, http, url, host, headers, seen, refresh + 1)

    timer = threading.Timer(KEEPWARM_INTERVAL_SECONDS, fire)
    timer.daemon = True
    timer.name = "persona-chat-preconnect-keepwarm"
    timer.start()


def preopen_provider_connection(agent: Any, timing: dict[str, Any]) -> str:
    """Credential-free ``HEAD`` requests to ``agent``'s base URL, under the actor's identity. Returns a status.

    The status is the first response code as a string, or one of the
    ``STATUS_*`` tokens. Writes :data:`PREWARM_CONNECT_MS` only when a request
    was sent; arms the keep-warm timer when the server kept a connection.
    """

    http = _http_client(agent)
    if http is None:
        return STATUS_NO_CLIENT
    url = _base_url(agent)
    host = (urlsplit(url).hostname or "").lower()
    if not url or not host:
        return STATUS_NO_URL
    if _is_loopback(host):
        return STATUS_LOOPBACK
    headers = _identity_headers(agent)
    _remember_idle_target(agent, http, url, host, headers)
    started = time.perf_counter()
    kept = 0
    try:
        status, kept = _open_connections(http, url, headers)
    except Exception:
        logger.debug("prewarm provider pre-connect failed for %s", host, exc_info=True)
        status = STATUS_FAILED
    elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
    timing[PREWARM_CONNECT_MS] = elapsed_ms
    logger.info(PRECONNECT_RECEIPT, host, status, kept, elapsed_ms)
    if kept:
        _keep_warm(agent, http, url, host, headers, _first_request_seen(agent))
    return status


#: h-idle-turn: what the pre-connect resolved for each prewarmed actor, ``id(agent) -> (agent ref,
#: http, url, host, headers)``, so the idle keeper re-uses the same connection without
#: checking out the actor's request client again.
_IDLE_TARGETS: dict[int, tuple[Any, Any, str, str, dict[str, str]]] = {}
_IDLE_TARGETS_LOCK = threading.Lock()
IDLE_KEEPWARM_RECEIPT = "persona_chat_idle_keepwarm host=%s status=%s kept=%d elapsed_ms=%d"
STATUS_NO_TARGET = "no_target"


def _remember_idle_target(agent: Any, http: Any, url: str, host: str, headers: dict[str, str]) -> None:
    try:
        ref = weakref.ref(agent)
    except TypeError:
        return
    with _IDLE_TARGETS_LOCK:
        for key in [k for k, v in _IDLE_TARGETS.items() if v[0]() is None or getattr(v[1], "is_closed", False)]:
            _IDLE_TARGETS.pop(key, None)
        _IDLE_TARGETS[id(agent)] = (ref, http, url, host, headers)


def _idle_target(agent: Any) -> tuple[Any, ...] | str:
    """``(ref, http, url, host, headers)`` for ``agent``, or the status saying why there is none.

    The pre-connect's record when it reached this actor; otherwise derived now, from the client
    the actor's turns send on (:func:`_http_client`), and remembered. h-idle-socket (live
    2026-10-07 12:07, w19): the chat the operator typed in was never pre-connected -- its prewarm
    read ``skipped_turn_active`` -- so every keeper tick logged ``socket=no_target``.
    """

    with _IDLE_TARGETS_LOCK:
        target = _IDLE_TARGETS.get(id(agent))
    if target is not None and target[0]() is agent and not getattr(target[1], "is_closed", False):
        return target
    http = _http_client(agent)
    if http is None:
        return STATUS_NO_CLIENT
    url = _base_url(agent)
    host = (urlsplit(url).hostname or "").lower()
    if not url or not host:
        return STATUS_NO_URL
    if _is_loopback(host):
        return STATUS_LOOPBACK
    _remember_idle_target(agent, http, url, host, _identity_headers(agent))
    with _IDLE_TARGETS_LOCK:
        return _IDLE_TARGETS.get(id(agent)) or STATUS_NO_TARGET


def refresh_idle_connection(agent: Any) -> str:
    """h-idle-turn: ONE ``HEAD`` on the connection ``agent``'s turns ride, between turns. Returns a status.

    The client is the one the actor's last turn sent on, pre-connected or not (:func:`_idle_target`);
    a loopback provider is never kept. One connection: an after-idle turn has no title upgrade racing it.
    """

    target = _idle_target(agent)
    if isinstance(target, str):
        return target
    _ref, http, url, host, headers = target
    started = time.perf_counter()
    try:
        status, kept = _open_connections(http, url, headers, count=1)
    except Exception:
        logger.debug("idle keep-warm failed for %s", host, exc_info=True)
        status, kept = STATUS_FAILED, 0
    logger.info(IDLE_KEEPWARM_RECEIPT, host, status, kept, max(0, int((time.perf_counter() - started) * 1000)))
    return status


__all__ = [
    "IDLE_KEEPWARM_RECEIPT",
    "IDENTITY_HEADERS",
    "KEEPWARM_INTERVAL_SECONDS",
    "KEEPWARM_MAX_REFRESHES",
    "KEEPWARM_RECEIPT",
    "PRECONNECT_CONNECTIONS",
    "REQUEST_CLIENT_API_MODES",
    "PRECONNECT_RECEIPT",
    "PREWARM_CONNECT_MS",
    "note_process_request_sent",
    "preopen_provider_connection",
    "refresh_idle_connection",
]
