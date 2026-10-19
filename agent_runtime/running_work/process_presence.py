"""A terminal background process publishes its own START and END on the stream lane.

Row ``RT-EMIT-RUNNING-WORK-CHAT``, plan ``docs/agent-runtime-harness/planned/p10-turn-2026-10-19.md``
§2 S2. The terminal ``running_work`` rows are a read-time projection
(:class:`~agent_runtime.running_work.lanes_process.TerminalLane` reads the
``processes.json`` checkpoint and the live registry), and nothing appended an
EventLog event when a process spawned or exited — so the stream hub learned of it
only from the freshness backstop or an unrelated write, and then as a FULL core.

This is :mod:`agent_runtime.chat_turn_presence` one lane over: the registry's
two chokepoints (``ProcessRegistry._track_started`` and the first
``_publish_finished``) call :func:`_on_lifecycle` through the additive upstream
seam ``ProcessRegistry.add_lifecycle_listener`` (a held PR row in
``upstream-footprint-ledger.md``), AFTER the checkpoint write, so a projection
read taken on the event sees the row. Each append is fail-safe exactly as
``ChatTurnPresence._append`` is: a notification is not the process, and a
failure returns ``False`` while the process proceeds untouched.

Installed from the plugin's ``register(ctx)`` (owner decision, recommended
path): every hermes process that hosts a ``ProcessRegistry`` writes the
checkpoint the projection reads, so every one is a writer of the row. The
install is idempotent (a module flag) and lazy (``tools.process_registry`` is
imported on install, never at module import).
"""

from __future__ import annotations

import threading
from typing import Any

from .rows import _iso, bounded_operator_text, work_id_of
from .vocabulary import KIND_TERMINAL

__layer__ = "lanes"

__all__ = [
    "EVENT_PROCESS_ENDED",
    "EVENT_PROCESS_STARTED",
    "PROCESS_PRESENCE_EVENT_TYPES",
    "install_process_presence",
]

#: Registered in :mod:`agent_runtime.decision_contract_registry` in the same
#: commit as this emitter, per S55.
EVENT_PROCESS_STARTED = "running_work.process_started"
EVENT_PROCESS_ENDED = "running_work.process_ended"
PROCESS_PRESENCE_EVENT_TYPES = frozenset({EVENT_PROCESS_STARTED, EVENT_PROCESS_ENDED})

#: The registry's phase word -> the event it appends. A table, not a ladder.
_PHASE_EVENTS = {"started": EVENT_PROCESS_STARTED, "finished": EVENT_PROCESS_ENDED}

#: The terminal lane bounds its row's command at 400 and its id at 200; the
#: payload carries the same text the row will.
_COMMAND_LIMIT = 400
_ID_LIMIT = 200

_INSTALL_LOCK = threading.Lock()
_installed = False


def install_process_presence() -> bool:
    """Register the listener on the process-wide registry, once. Returns whether
    THIS call installed it (``False`` when already installed or the registry
    could not be imported — a CLI without the tool surface is not an error)."""

    global _installed
    with _INSTALL_LOCK:
        if _installed:
            return False
        try:
            from tools.process_registry import process_registry
        except Exception:
            return False
        process_registry.add_lifecycle_listener(_on_lifecycle)
        _installed = True
        return True


def _on_lifecycle(phase: str, session: Any) -> bool:
    """The registry's lifecycle callback: one bounded, fail-safe append."""

    event_type = _PHASE_EVENTS.get(str(phase))
    if event_type is None:
        return False
    try:
        payload = _payload(session, ended=event_type == EVENT_PROCESS_ENDED)
    except Exception:
        return False
    if not payload["process_session_id"]:
        return False
    # Each type named at its own append so the S55 emitter walk sees both.
    if event_type == EVENT_PROCESS_ENDED:
        return _append(EVENT_PROCESS_ENDED, payload)
    return _append(EVENT_PROCESS_STARTED, payload)


def _payload(session: Any, *, ended: bool) -> dict[str, Any]:
    process_session_id = bounded_operator_text(getattr(session, "id", ""), limit=_ID_LIMIT)
    payload: dict[str, Any] = {
        "process_session_id": process_session_id,
        "work_id": work_id_of(KIND_TERMINAL, process_session_id),
        "pid": _pid(getattr(session, "pid", None)),
        "command": _process_command(getattr(session, "command", "")),
        "owner_task_id": str(getattr(session, "owner_task_id", "") or "") or None,
        "started_at": _iso(getattr(session, "started_at", None)),
    }
    if ended:
        exit_code = getattr(session, "exit_code", None)
        payload["exit_code"] = exit_code if isinstance(exit_code, int) else None
        payload["completion_reason"] = str(getattr(session, "completion_reason", "") or "") or None
    return payload


def _pid(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _process_command(command: Any) -> str:
    """The checkpoint's redaction (``redact_sensitive_text(..., code_file=True)``),
    then the row's bound — so the event never carries text the row would not."""

    text = str(command or "")
    try:
        from agent.redact import redact_sensitive_text

        text = redact_sensitive_text(text, code_file=True)
    except Exception:
        return ""
    return bounded_operator_text(text, limit=_COMMAND_LIMIT)


def _append(event_type: str, payload: dict[str, Any]) -> bool:
    try:
        from hermes_time import now

        from ..events import EventLog
        from ..models import Event

        EventLog().append(
            Event(
                type=event_type,
                task_id=None,
                run_id=None,
                # A process has no persona binding of its own; the terminal
                # lane resolves its owner from the session key at read time.
                persona_id=None,
                ts=now(),
                payload=payload,
            )
        )
    except Exception:
        # A notification is not the process. See the module docstring.
        return False
    return True
