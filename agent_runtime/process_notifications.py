"""Downstream process-registry policy: checkpoint home, mission-chat wait ceiling, durable restore.

The late ``process notify`` request that used to live here was deleted 2026-09-24 (owner
ruling): completion is decided once at spawn, where the eternia-harness plugin turns
``notify`` on by default through ``tool_request`` middleware.
"""
from __future__ import annotations
import logging
import os
import threading
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


class ProcessNotificationMixin:
    def restore_durable_completions(self) -> int:
        """Rehydrate durable pending delegation completions into the queue.

        Called explicitly, once, by the entry points that OWN a completion
        drain (the gateway, the interactive CLI, the TUI gateway, harness
        serve) — the same explicit-at-startup contract MCP discovery moved to
        for #16856. It used to run inside ``__init__``, which made it an
        IMPORT side effect of the module-scope singleton: any module that
        touched the tool tree — including read-only projections — opened (and
        created) ``state.db`` and ran ``recover_abandoned_delegations()``, a
        real mutation, before a single verb executed. See
        ``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/eager-tool-discovery-audit-2026-08-09.md``.

        Idempotent per process: a second call returns 0 without touching the
        store, because re-running the restore would re-enqueue every pending
        completion (delivery attempts are only deduped at claim time). The
        guard is set before the restore runs, so a failed restore is warned
        about and NOT retried — the same once-at-startup semantics the
        constructor provided.

        Returns the number of completions enqueued (0 on the guarded or
        failed path).
        """
        with self._durable_restore_lock:
            if self._durable_completions_restored:
                return 0
            self._durable_completions_restored = True
        try:
            from tools.async_delegation import restore_undelivered_completions
            return restore_undelivered_completions(self.completion_queue)
        except Exception as exc:
            logger.warning("Could not restore async delegation completions: %s", exc)
            return 0
