"""h-idle-turn: the first turn after an idle pause reads warm memos and rides a warm socket (2026-10-07).

**What it cost.** Live 2026-10-07 00:44-00:45 (``dev_agent_8b319ebf``, serve w18) the first turn
after 35 s and after 2.5 min idle took 1139 / 1729 ms anchor -> ``request_sent`` and opened a new
connection; the next turn, 10 s later, 481 ms on a pooled one. Two causes, both reproduced offline
(``tests/agent_runtime/test_idle_turn_guard_downstream.py``):

* **Expired memos rebuilt inside the window.** The installed-skill catalog memo
  (``prompt_observability.skills_resolver``, 15 s TTL) answered stale and started its refresh walk
  on a thread at the turn's read -- the walk (upstream ``_find_all_skills``, a frontmatter parse per
  skill) then held the GIL beside the turn through ``turn_context_built``; offline, 180 skills,
  ``cpu_ms`` 484 over a 386 ms window. The runtime-resolve memo (``profile_runner.execute``, 30 s
  TTL) re-resolved inline in ``agent_ready``.
* **The socket expired.** The shared transport reaps an idle connection after 20 s
  (``keepalive_expiry``, ``agent/process_bootstrap.py``) and the prewarm's keep-warm stops at the
  process's first send (``provider_preconnect``), so after any pause over 20 s a turn handshook.

**What this module does.** It knows when a turn is between its anchor and ``request_sent``
(:func:`note_window_opened` / :func:`note_window_closed`, from
``mission_chat_phases.TurnPhaseMarks``), and holds ONE daemon thread, armed by every
``request_sent`` in a process that keeps resident chats (a serve). Every
:data:`KEEPER_INTERVAL_SECONDS`, at most :data:`KEEPER_MAX_TICKS` times after the last send, a tick
that finds no turn window open runs every registered refresh (each refreshes its own memo only
when it is old enough to lapse before the next tick) and sends one ``HEAD`` on the most recently
active chat's connection. A turn reads the last value; a memo past its TTL inside a window is
refreshed after that turn's ``request_sent``, never inside it.

**Why 15 s and not a minute.** The pool's ``keepalive_expiry`` is 20 s (upstream's value; reverse
proxies close at 30-60 s): a refresh less often than that finds no connection to keep. At most
:data:`KEEPER_MAX_TICKS` (five minutes) per pause; a longer pause pays as before.

The thread stops when the resident registry is switched off, on :func:`stop` (the serve's drain)
and at its tick cap. Observability is one log receipt per tick, never a parity-envelope key.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from typing import Any, Callable

__layer__ = "policy"

logger = logging.getLogger(__name__)

KEEPER_RECEIPT = "idle_turn_keeper tick=%d refreshed=%s socket=%s elapsed_ms=%d"
KEEPER_THREAD_NAME = "idle-turn-keeper"

#: Under the pool's 20 s ``keepalive_expiry``; the same cadence as the prewarm's keep-warm.
KEEPER_INTERVAL_SECONDS = 15.0

#: Five minutes of one pause; every ``request_sent`` starts the count again.
KEEPER_MAX_TICKS = 20

#: A window older than this never reached ``request_sent`` (the turn failed first): not open.
WINDOW_MAX_SECONDS = 240.0

_LOCK = threading.Lock()
_WINDOWS: "weakref.WeakKeyDictionary[Any, float]" = weakref.WeakKeyDictionary()
_REFRESHES: dict[str, Callable[[], Any]] = {}
_STATE: dict[str, Any] = {"thread": None, "ticks": 0, "agent": None, "stop": threading.Event()}


# ── turn windows ────────────────────────────────────────────────────────────

def note_window_opened(marks: Any) -> None:
    """A turn took its anchor."""

    try:
        with _LOCK:
            _WINDOWS[marks] = time.monotonic()
    except TypeError:  # not weak-referenceable: not a turn this module can track
        pass


def note_window_closed(marks: Any) -> None:
    """The turn's request left (``request_sent``): its window is shut, and the keeper is re-armed."""

    with _LOCK:
        _WINDOWS.pop(marks, None)
    arm()


def turn_window_open() -> bool:
    """True while any turn in this process is between its anchor and ``request_sent``."""

    now = time.monotonic()
    with _LOCK:
        return any(now - anchored < WINDOW_MAX_SECONDS for anchored in _WINDOWS.values())


# ── what a tick refreshes ───────────────────────────────────────────────────

def register_refresh(key: str, refresh: Callable[[], Any]) -> None:
    """Run ``refresh`` on every idle tick (latest registration per ``key`` wins).

    ``refresh`` decides for itself whether its memo is old enough to rebuild, carries the
    context it must run in, and never raises (a failure is logged at debug and skipped).
    """

    with _LOCK:
        _REFRESHES[key] = refresh


def note_active_agent(agent: Any) -> None:
    """The actor of the turn that is starting: the chat whose connection the keeper keeps."""

    try:
        _STATE["agent"] = weakref.ref(agent)
    except TypeError:
        _STATE["agent"] = None


# ── the thread ──────────────────────────────────────────────────────────────

#: Whether this process keeps resident chats (a serve). Injected by the layer that owns the
#: registry (``persona_chat_continuity.runtime_registry.initialize_persona_chat_runtime_registry``)
#: so this policy module never imports a store.
_LIVE: dict[str, Callable[[], bool] | None] = {"check": None}


def bind_registry_live(check: Callable[[], bool] | None) -> None:
    """Set the callable that answers "is the resident chat registry on?" (None: off)."""

    _LIVE["check"] = check


def _enabled() -> bool:
    check = _LIVE["check"]
    try:
        return bool(check()) if check is not None else False
    except Exception:
        return False


def arm() -> threading.Thread | None:
    """Restart the tick count; start the thread when none runs. Never raises."""

    try:
        if not _enabled():
            return None
        with _LOCK:
            _STATE["ticks"] = 0
            thread = _STATE["thread"]
            if thread is not None and thread.is_alive():
                return thread
            stop_event = threading.Event()
            thread = threading.Thread(target=_keeper_loop, args=(stop_event,), name=KEEPER_THREAD_NAME, daemon=True)
            _STATE.update(thread=thread, stop=stop_event)
        thread.start()
        return thread
    except Exception:
        logger.debug("idle turn keeper not started", exc_info=True)
        return None


def stop() -> None:
    """Stop the thread (the serve's drain, a test's teardown)."""

    with _LOCK:
        _STATE["stop"].set()
        _STATE["thread"] = None


def _keeper_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(KEEPER_INTERVAL_SECONDS):
        with _LOCK:
            if _STATE["ticks"] >= KEEPER_MAX_TICKS or not _enabled():
                if _STATE["thread"] is threading.current_thread():
                    _STATE["thread"] = None
                return
            _STATE["ticks"] += 1
            tick = _STATE["ticks"]
        if turn_window_open():
            continue
        tick_once(tick)


def tick_once(tick: int = 0) -> tuple[list[str], str]:
    """One idle tick: every refresh, then the socket. Returns ``(refreshed keys, socket status)``."""

    started = time.perf_counter()
    with _LOCK:
        refreshes = dict(_REFRESHES)
    refreshed: list[str] = []
    for key, refresh in refreshes.items():
        if turn_window_open():  # a turn arrived mid-tick: the rest waits for the next idle tick
            break
        try:
            if refresh():
                refreshed.append(key)
        except Exception:
            logger.debug("idle refresh %s failed", key, exc_info=True)
    socket = "none"
    ref = _STATE.get("agent")
    agent = ref() if ref is not None else None
    if agent is not None and not turn_window_open():
        from agent_runtime.provider_preconnect import refresh_idle_connection

        socket = refresh_idle_connection(agent)
    kinds = sorted({key.split(":", 1)[0] for key in refreshed})  # the key's tail is a home path
    logger.info(KEEPER_RECEIPT, tick, ",".join(kinds) or "none", socket,
                max(0, int((time.perf_counter() - started) * 1000)))
    return refreshed, socket


def keeper_thread_for_tests() -> threading.Thread | None:
    return _STATE["thread"]


def reset_for_tests() -> None:
    stop()
    with _LOCK:
        _WINDOWS.clear()
        _REFRESHES.clear()
        _STATE.update(ticks=0, agent=None)


__all__ = [
    "KEEPER_INTERVAL_SECONDS", "KEEPER_MAX_TICKS", "KEEPER_RECEIPT", "KEEPER_THREAD_NAME", "arm",
    "bind_registry_live",
    "keeper_thread_for_tests", "note_active_agent", "note_window_closed", "note_window_opened",
    "register_refresh", "reset_for_tests", "stop", "tick_once", "turn_window_open",
]
