"""Downstream process-registry policy: checkpoint home and the mission-chat wait ceiling.

The durable-completion restore that used to live here was deleted 2026-09-27 (lane
CARRY-DELETE, door-fit #125256): upstream's ``ProcessRegistry.__init__`` restores at the
singleton's first construction.

The late ``process notify`` request that used to live here was deleted 2026-09-24 (owner
ruling): completion is decided once at spawn, where the eternia-harness plugin turns
``notify`` on by default through ``tool_request`` middleware.
"""
from __future__ import annotations
import logging
import os

__layer__ = "wiring"

logger = logging.getLogger("tools.process_registry")
MISSION_CHAT_WAIT_MAX_SECONDS = 600


def checkpoint_path():
    """Path to the crash-recovery checkpoint, resolved at call time."""

    from agent_runtime.profile_home import get_hermes_background_work_home

    return get_hermes_background_work_home() / "processes.json"


def _configured_wait_ceiling() -> int:
    """``TERMINAL_TIMEOUT`` as an int, or the historical 180 s default."""

    try:
        return int(os.getenv("TERMINAL_TIMEOUT", "180"))
    except (ValueError, TypeError):
        return 180


def wait_ceiling_seconds() -> int:
    """The longest ``process wait`` this lane may block for.

    Two inputs, and the mission-chat one can only ever RAISE the answer:

    * ``TERMINAL_TIMEOUT`` — the deployment-wide configuration, unchanged, and
      the only input on every lane that is not mission-chat.
    * :data:`MISSION_CHAT_WAIT_MAX_SECONDS` — a FLOOR for the governed
      mission-chat lane, applied with ``max()`` so an operator who configured a
      longer ``TERMINAL_TIMEOUT`` keeps it and nobody's window is shortened.

    Lane identity comes from ``agent_runtime.terminal_envelope``'s run scope —
    the same ContextVar the terminal tool already resolves its envelope from, so
    a wait issued inside a mission-chat turn is recognised without a second
    notion of "which lane am I on". Any failure to resolve it (the import
    missing on a lean install, an odd scope object) degrades to the configured
    ceiling, i.e. to exactly today's behaviour.
    """

    ceiling = _configured_wait_ceiling()
    try:
        from agent_runtime.terminal_envelope import (
            LANE_MISSION_CHAT,
            current_terminal_envelope_scope,
        )

        scope = current_terminal_envelope_scope()
        on_lane = scope is not None and str(getattr(scope, "lane", "")) == LANE_MISSION_CHAT
    except Exception:  # pragma: no cover - defensive; a clamp must never fail a wait
        logger.debug("terminal envelope lane unavailable for the wait ceiling", exc_info=True)
        return ceiling
    return max(ceiling, MISSION_CHAT_WAIT_MAX_SECONDS) if on_lane else ceiling

