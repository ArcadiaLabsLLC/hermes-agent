"""Provider stream timing receipts, read off upstream's stream observer hooks.

Upstream brackets every streamed provider call — the Codex passthrough included
(``agent.chat_completion_helpers._stream_codex_passthrough``) — with
``on_stream_start`` / ``on_stream_end`` and fires ``on_stream_delta`` per text
delta, all enqueued OFF the token path onto a dispatcher thread. The
eternia-harness plugin registers the three observers below; they write two
receipts into the persona agent's ``status_callback``:

* ``provider_stream_first_delta`` — ``on_stream_start`` to the first text delta
  (time to first token);
* ``provider_stream_consume`` — the first text delta to ``on_stream_end`` (start
  to end when no text arrived; ``provider_stream_text_delta_count`` is then 0).

The dispatch total is the plugin's ``llm_execution`` span
(``conversation_observability.time_provider_dispatch``). Two limits are the
price of the hook form: each instant is taken when the dispatcher DELIVERS the
event, not when upstream enqueued it (upstream runs one dispatcher per callback,
so a slow co-consumer does not delay ours, but a busy box can); and the
per-attempt split and the client-resolve stamp are gone (plugin-fit §4 Q4).

The observers run on the dispatcher thread, where the turn's ContextVar binding
(``persona_turn_binding``) is not visible, so the plugin's ``llm_execution``
middleware — which runs in the turn's thread — names the bound agent for its
session first (``remember_stream_agent``). An unbound session gets no receipt.

The observers are registered only while a persona turn runs
(``stream_observers_armed``, entered by the profile runner around the bound turn).
Upstream reads "any ``on_stream_*`` callback registered" as "this agent has a stream
consumer" (``_has_stream_consumers``), which flips its streaming, spinner and
post-response-mute decisions; registered at plugin load, the observers made every
agent in the process a streaming consumer. The plugin hands its ``register_hook``
over at load (``install_stream_observers``); the first armed turn registers the
three, the last one out disposes them.
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator

__layer__ = "stores"

logger = logging.getLogger(__name__)

#: Open streams kept at most; an ``on_stream_end`` the dispatcher dropped
#: (drop-oldest queue) must not grow this without bound.
_MAX_OPEN_STREAMS = 256

_LOCK = threading.Lock()
_AGENTS: "weakref.WeakValueDictionary[str, Any]" = weakref.WeakValueDictionary()
_STREAMS: "OrderedDict[tuple, _OpenStream]" = OrderedDict()


@dataclass
class _OpenStream:
    started: float
    first_delta: float | None = None
    text_deltas: int = 0


def _emit_provider_timing(
    agent: Any,
    step: str,
    duration_ms: int,
    *,
    status: str = "completed",
    timing_values: Dict[str, int] | None = None,
    **extra: Any,
) -> None:
    callback = getattr(agent, "status_callback", None)
    if callback is None:
        return
    try:
        callback(
            {
                "type": "run.progress",
                "phase": "timing",
                "step": f"provider_{step}",
                "status": status,
                "summary": f"Provider {step.replace('_', ' ')} {status} in {duration_ms}ms.",
                "duration_ms": max(0, int(duration_ms)),
                "timing_key": f"provider_{step}_ms",
                "timing_values": timing_values or {},
                "provider": getattr(agent, "provider", None),
                "model": getattr(agent, "model", None),
                "api_mode": getattr(agent, "api_mode", None),
                **extra,
            }
        )
    except Exception:
        logger.debug("provider timing callback failed", exc_info=True)


def _ms(seconds: float) -> int:
    return max(0, int(seconds * 1000))


def _key(session_id: Any, turn_id: Any, iteration: Any) -> tuple:
    return (str(session_id or ""), str(turn_id or ""), str(iteration or 0))


def remember_stream_agent(agent: Any = None) -> None:
    """Name the persona agent for its session, so the observers can reach its sink.

    Called in the turn's thread (``llm_execution``) before the provider call; with no
    argument it reads the turn's binding. Weakly held: a finished agent drops out."""
    if agent is None:
        from agent_runtime.persona_turn_binding import current_persona_turn_agent

        agent = current_persona_turn_agent()
    session_id = str(getattr(agent, "session_id", "") or "") if agent is not None else ""
    if not session_id:
        return
    with _LOCK:
        _AGENTS[session_id] = agent


def on_stream_start(*, session_id: Any = "", turn_id: Any = "", iteration: Any = 0, **_kwargs: Any) -> None:
    """``on_stream_start`` observer: open the stream's clock (named sessions only)."""
    now = time.perf_counter()
    with _LOCK:
        if str(session_id or "") not in _AGENTS:
            return
        _STREAMS[_key(session_id, turn_id, iteration)] = _OpenStream(started=now)
        while len(_STREAMS) > _MAX_OPEN_STREAMS:
            _STREAMS.popitem(last=False)


def on_stream_delta(
    *, session_id: Any = "", turn_id: Any = "", iteration: Any = 0, kind: str = "text", **_kwargs: Any,
) -> None:
    """``on_stream_delta`` observer: the first TEXT delta stamps time-to-first-token."""
    if kind != "text":
        return
    now = time.perf_counter()
    with _LOCK:
        stream = _STREAMS.get(_key(session_id, turn_id, iteration))
        if stream is None:
            return
        if stream.first_delta is None:
            stream.first_delta = now
        stream.text_deltas += 1


def on_stream_end(
    *, session_id: Any = "", turn_id: Any = "", iteration: Any = 0,
    finished: Any = True, error: Any = None, **_kwargs: Any,
) -> None:
    """``on_stream_end`` observer: write the first-delta and consume receipts."""
    now = time.perf_counter()
    with _LOCK:
        stream = _STREAMS.pop(_key(session_id, turn_id, iteration), None)
        agent = _AGENTS.get(str(session_id or ""))
    if stream is None or agent is None:
        return
    status = "completed" if finished and not error else "failed"
    values = {"provider_stream_text_delta_count": stream.text_deltas}
    if stream.first_delta is not None:
        _emit_provider_timing(agent, "stream_first_delta", _ms(stream.first_delta - stream.started))
    consume_from = stream.first_delta if stream.first_delta is not None else stream.started
    _emit_provider_timing(agent, "stream_consume", _ms(now - consume_from), status=status, timing_values=values)


_ARM_LOCK = threading.Lock()
_ARM: Dict[str, Any] = {"register_hook": None, "turns": 0, "leases": []}


def install_stream_observers(register_hook: Callable[[str, Callable[..., Any]], Any]) -> None:
    """The plugin's ``ctx.register_hook``, kept for the persona lane to arm with; nothing
    is registered here. A reload hands a fresh one; turns already armed keep their leases."""
    with _ARM_LOCK:
        _ARM["register_hook"] = register_hook


@contextmanager
def stream_observers_armed() -> Iterator[None]:
    """Register the three observers for as long as at least one persona turn is inside."""
    with _ARM_LOCK:
        _ARM["turns"] += 1
        if _ARM["turns"] == 1 and _ARM["register_hook"] is not None:
            register = _ARM["register_hook"]
            for name, observer in (("on_stream_start", on_stream_start), ("on_stream_delta", on_stream_delta),
                                   ("on_stream_end", on_stream_end)):
                try:
                    _ARM["leases"].append(register(name, observer))
                except Exception:  # a turn without receipts still runs
                    logger.warning("stream observer %s could not be registered", name, exc_info=True)
    try:
        yield
    finally:
        with _ARM_LOCK:
            _ARM["turns"] -= 1
            leases = _ARM["leases"] if _ARM["turns"] == 0 else []
            if _ARM["turns"] == 0:
                _ARM["leases"] = []
        for lease in leases:
            dispose = getattr(lease, "dispose", None)
            if dispose is not None:
                dispose()


def reset_for_tests() -> None:
    with _LOCK:
        _AGENTS.clear()
        _STREAMS.clear()
    with _ARM_LOCK:
        leases, _ARM["leases"], _ARM["turns"] = _ARM["leases"], [], 0
    for lease in leases:
        getattr(lease, "dispose", lambda: None)()
