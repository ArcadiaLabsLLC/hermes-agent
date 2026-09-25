"""The process's warm transports, behind the door: the default registrar, the
transport classification, the SDK probe, the live-session and parked-server
reads, the parked wake and the warm re-registration."""

from __future__ import annotations

import time
from typing import Any, Iterable, Mapping, Sequence

from .._upstream_doors import (
    mcp_key_name,
    mcp_register_server_tools,
    mcp_resolve_server_key,
    mcp_sdk_available_flag,
    mcp_server_map,
    mcp_signal_reconnect,
    mcp_wait_for_session,
)

from .vocabulary import TRANSPORT_COLD, TRANSPORT_WARM, _PARKED_WAKE_TIMEOUT_SECONDS, logger

__layer__ = "stores"


def _default_registrar(servers: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Register the admitted subset ONLY, warm-aware.

    ``discover_mcp_tools()`` is never called: it would register everything in the
    profile's config, which is precisely the blast radius admission refuses.

    Since R2 tears the registry scope down after every run while leaving the
    transport warm, a server can be CONNECTED and yet have no registered tools —
    a state ``register_mcp_servers`` cannot repair, because it short-circuits on
    connected servers (``if not new_servers: return _existing_tool_names()``).
    So the admitted set is split: warm servers are re-registered off their live
    session (no spawn, no handshake, and this run's ``tools`` filter applied to
    the already-listed tools), cold ones go through ``register_mcp_servers``.

    THE THIRD STATE, and the one that cost turns their tools. A server can be
    cached in ``_servers`` with ``session is None`` — parked after a transport
    death, or mid-reconnect. That is not warm (there is no session to re-register
    off) and it is not cold either, and routing it to ``register_mcp_servers``
    hands it to a function that CANNOT register it: the name is already in
    ``_servers``, so ``new_servers`` is empty, so it fires a fire-and-forget
    ``_signal_reconnect`` and returns ``_existing_tool_names()`` — a stale list
    of tools it did not register. Nothing reaches the registry, the caller's
    honest re-read of ``registered_mcp_server_names()`` finds nothing, and the
    turn runs with no MCP surface while the reconnect it just asked for lands a
    second later. That is the 2026-08-27 3/0/3/0 alternation: the parked turn
    admits zero and cures the next one, which admits everything and parks it
    again.

    So a parked server is WOKEN here — nudged, then waited on for a bounded
    ``_PARKED_WAKE_TIMEOUT_SECONDS`` — and whatever comes back joins the warm
    set. Whatever does not falls through to the cold path exactly as before:
    this widens nothing and re-registers nothing off a dead session, it only
    stops discarding a turn's tools while the fix is in flight.
    """

    warm: dict[str, Mapping[str, Any]] = {}
    cold: dict[str, Any] = {}
    live = _live_mcp_sessions()
    parked = [name for name in servers if name not in live and _is_parked(name)]
    if parked:
        live = live | _wake_parked_servers(parked)
    for name, cfg in servers.items():
        (warm if name in live else cold)[name] = cfg

    names: list[str] = []
    for name, cfg in warm.items():
        names.extend(_reregister_warm_server(name, dict(cfg)))
    if cold:
        from tools.mcp_tool_discovery import register_mcp_servers

        names.extend(register_mcp_servers({name: dict(cfg) for name, cfg in cold.items()}) or [])
    return names


def classify_admission_transport(servers: Iterable[str] | None) -> dict[str, str]:
    """``{server: warm|cold}`` for an admitted set, read before registration.

    Pure observation over ``tools/mcp_tool._servers``: it decides nothing and
    changes nothing. It exists so a turn can SAY which of the two costs it paid
    instead of leaving a reader to infer it from a millisecond count — see
    :data:`TRANSPORT_WARM` for the measurements that make the distinction worth
    recording, and the analysis it corrects.

    Uses the same liveness predicate :func:`_default_registrar` starts from
    (``_live_mcp_sessions``), read at the same instant, so ``warm`` here is
    always a real live session and never a hopeful one.

    ONE label is a snapshot rather than an outcome, and it is worth saying which:
    a PARKED entry (cached, no session) reads ``cold`` here, and the registrar
    may then wake it and re-register it off the session it gets back. The label
    is honest about what was true when the turn started — which is the question
    it was added to answer, "what did this turn have to pay for" — and a wake is
    a cost on the cold side of that line either way. The registrar logs the
    parked names it woke; that is where the finer distinction lives.
    """

    names = [str(name).strip() for name in servers or () if str(name or "").strip()]
    if not names:
        return {}
    live = _live_mcp_sessions()
    return {name: (TRANSPORT_WARM if name in live else TRANSPORT_COLD) for name in names}


def mcp_sdk_available() -> bool:
    """Does this RUNTIME have an MCP client at all?

    The single place ``agent_runtime`` reads ``tools/mcp_tool._MCP_AVAILABLE``
    (through its door, ``_upstream_doors.mcp_sdk_available_flag``).
    That flag is set once at import from ``try: from mcp import ClientSession``,
    so it answers exactly one question — is the optional ``mcp`` pip extra in
    this venv — and it answers it for the life of the process. A pip install
    into a running serve does not change it; the runtime has to be restarted.

    Read HERE rather than inferred from an empty registration, because those two
    are the facts :data:`MCP_SDK_UNAVAILABLE` exists to separate. Fails to the
    pessimistic side: an unimportable ``tools.mcp_tool`` is a runtime that
    cannot register anything either, and reporting that as "the server did not
    connect" is the mislabelling this function was added to stop.
    """

    try:
        return mcp_sdk_available_flag()
    except Exception:  # pragma: no cover - tools.mcp_tool is importable in-process
        logger.debug("MCP admission could not read the SDK availability flag", exc_info=True)
        return False


def _current_mcp_servers() -> dict[str, Any]:
    """Read connections owned or adopted by the current profile only."""
    servers, lock = mcp_server_map()
    with lock:
        return {
            name: servers[key]
            for name in {mcp_key_name(key) for key in servers}
            if (key := mcp_resolve_server_key(name)) in servers
        }


def _live_mcp_sessions() -> frozenset[str]:
    """Admitted-server names already connected WITH a live session.

    A cached entry whose ``session`` is ``None`` is parked or mid-reconnect and
    is NOT live: there is nothing to re-register off. It is not left to
    ``register_mcp_servers`` any more, either — that function has a wake and no
    registration, which is what cost the measured turns their whole MCP surface.
    :func:`_default_registrar` wakes those itself and re-asks this question; see
    :func:`_wake_parked_servers`.
    """

    try:
        servers = _current_mcp_servers()
    except Exception:  # pragma: no cover - MCP SDK absent ⇒ nothing is warm
        return frozenset()
    try:
        return frozenset(
            str(name)
            for name, server in servers.items()
            if getattr(server, "session", None) is not None
        )
    except Exception:  # pragma: no cover - defensive
        logger.debug("MCP admission could not read the warm-server map", exc_info=True)
        return frozenset()


def _is_parked(name: str) -> bool:
    """Cached in ``tools/mcp_tool._servers`` but holding no session.

    The third state, and the only one worth waking: a name that is ABSENT from
    the cache is genuinely cold and belongs to ``register_mcp_servers``, which
    can and does spawn it.
    """

    try:
        server = _current_mcp_servers().get(str(name))
    except Exception:  # pragma: no cover - MCP SDK absent ⇒ nothing is cached
        return False
    return server is not None and getattr(server, "session", None) is None


def _wake_parked_servers(names: Sequence[str]) -> frozenset[str]:
    """Nudge parked servers, wait a bounded moment, report which came back.

    Every nudge goes out BEFORE the first wait, so three parked servers
    reconnect in parallel and the budget is paid roughly once rather than three
    times — the same reason the cold path connects with ``asyncio.gather``.

    Fails CLOSED and fails QUIET. A wake that raises, a seam that upstream drift
    has moved, or a session that never comes back all return the same thing: the
    name is not in the answer, so it routes cold exactly as it does today.
    Nothing here can register a tool or widen an admission — the only thing it
    changes is which of two existing paths a parked name takes.
    """

    wanted = [str(name) for name in names if str(name)]
    if not wanted:
        return frozenset()
    # The two reconnect seams are read through their doors at CALL time: a seam
    # upstream drift has moved raises inside the per-server guards below, and
    # the name routes cold — the same fail-closed answer as before.

    cache = _current_mcp_servers()
    parked = {name: cache[name] for name in wanted if name in cache}
    nudged: dict[str, Any] = {}
    for name, server in parked.items():
        try:
            if mcp_signal_reconnect(server):
                nudged[name] = server
        except Exception:  # pragma: no cover - defensive
            logger.debug("MCP admission could not nudge %r", name, exc_info=True)
    if not nudged:
        return frozenset()

    # ONE budget for the whole set, not one EACH. The nudges above all went out
    # before this loop, so the reconnects are already racing each other; a
    # per-server budget would multiply by N and could push the admission past
    # its own ``connect_timeout_seconds``, turning a park into a turn-long
    # timeout. Summed per-step budgets are not a bound.
    budget = max(0.0, float(_PARKED_WAKE_TIMEOUT_SECONDS))
    deadline = time.monotonic() + budget
    revived: set[str] = set()
    for name, server in nudged.items():
        # Cheap first: the earlier nudges have been landing while this loop ran,
        # so after the first wait the rest are normally already up and pay
        # nothing at all.
        if getattr(server, "session", None) is not None:
            revived.add(name)
            continue
        try:
            remaining = min(budget, max(0.0, deadline - time.monotonic()))
            if mcp_wait_for_session(server, remaining):
                revived.add(name)
        except Exception:  # pragma: no cover - defensive
            logger.debug("MCP admission could not wait for %r", name, exc_info=True)
    logger.info(
        "MCP admission woke %d/%d parked server(s): %s",
        len(revived),
        len(nudged),
        ", ".join(sorted(nudged)) or "-",
    )
    return frozenset(revived)


def _reregister_warm_server(name: str, config: dict[str, Any]) -> list[str]:
    """Re-register a connected server's tools under THIS run's tool filter.

    The upstream seam (``tools.mcp_tool_registration._register_server_tools``) is the same one
    dynamic ``notifications/tools/list_changed`` refresh uses to nuke-and-repave
    an MCP server's registry scope, which is exactly the operation R2 needs — it
    honours ``tools.include`` / ``tools.exclude``, re-registers the toolset alias,
    and touches no transport.

    Fails CLOSED. If the seam is gone (upstream drift) or the re-registration
    raises, this returns ``[]`` and the caller's registry read then reports the
    server as ``mcp_not_registered_on_lane`` — an honest "you have no tools this
    turn" rather than a silent fallback to whatever was registered before.
    """

    try:
        server = _current_mcp_servers().get(name)
        if server is None:  # pragma: no cover - raced against a disconnect
            return []
        registered = list(mcp_register_server_tools(name, server, config) or [])
        # Keep ``_existing_tool_names()`` consistent with what is really in the
        # registry, so a later cold registration of a DIFFERENT server does not
        # report this one's stale pre-teardown surface.
        try:
            server._registered_tool_names = list(registered)
        except Exception:  # pragma: no cover - exotic server stub
            pass
        return registered
    except Exception:
        logger.warning(
            "MCP admission could not re-register warm server %r; it will report as "
            "not registered for this run",
            name,
            exc_info=True,
        )
        return []
