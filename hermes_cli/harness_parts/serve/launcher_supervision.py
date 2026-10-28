"""The serve's half of launcher supervision: the ``launcher_beat`` op and the parent-watch hook.

Plan ``docs/agent-runtime-harness/planned/launcher-mutual-supervision-2026-10-27.md`` slice W1. The
watchdog (``agent_runtime.launcher_supervision``) owns the watch and the table; this mixin answers
the op, routes a closed connection to it, and carries out its two effects — latch an end reason,
drain — through the serve's existing drain path (``ServeSession._on_parent_gone``).
"""

from __future__ import annotations

import threading
from typing import Any

from hermes_cli.harness_parts.serve.manifest import _is_gateway

__layer__ = "lanes"

__all__ = ["LauncherSupervision"]

#: One serve per process, so one lock: two lanes' first beats must not mint two watchdogs.
_WATCHDOG_LOCK = threading.Lock()


class _ServeEffects:
    """:class:`agent_runtime.launcher_supervision.SupervisionEffects` over one serve session."""

    def __init__(self, session: Any) -> None:
        self._session = session

    def note_end(self, word: str) -> None:
        self._session._note_end(word)

    def drain(self, word: str, pid: int | None) -> None:
        self._session._on_parent_gone(word)


class LauncherSupervision:
    """Mixed into ``ServeSession``; ``launcher_watchdog`` is created at boot or by the first beat."""

    launcher_watchdog: Any = None

    def _launcher_watchdog(self) -> Any:
        with _WATCHDOG_LOCK:
            if self.launcher_watchdog is None:
                from agent_runtime.launcher_supervision import LauncherWatchdog

                self.launcher_watchdog = LauncherWatchdog(parent_pid=self.parent_pid,
                                                          effects=_ServeEffects(self)).start()
            return self.launcher_watchdog

    def _arm_launcher_supervision(self) -> None:
        """``--parent-pid``: watch it now; without the flag nothing is armed until a launcher beats."""
        if self.parent_pid is not None:
            self._launcher_watchdog()

    def _launcher_connection_closed(self, connection: Any) -> None:
        if self.launcher_watchdog is not None:
            self.launcher_watchdog.connection_closed(connection)

    def _op_launcher_beat(self, message: dict[str, Any], sink: Any, connection: Any) -> str | None:
        """``{"op":"launcher_beat",…}`` → ``launcher_beat_ok {seq, watching}``. Local transports only."""

        if _is_gateway(connection):
            sink.emit({
                "event": "error",
                "error": "op_not_available_on_gateway",
                "detail": "launcher_beat supervises the local launcher; a paired device never sends it",
            })
            return None
        from agent_runtime.launcher_supervision import BeatRefused, parse_beat

        beat = parse_beat(message)
        if isinstance(beat, BeatRefused):
            sink.emit({"id": message.get("id"), "event": "error", "error": "invalid_launcher_beat",
                       "field": beat.field, "detail": beat.detail})
            return None
        watching = self._launcher_watchdog().beat(beat, connection=connection)
        sink.emit({"id": message.get("id"), "event": "launcher_beat_ok", "seq": beat.seq, "watching": watching})
        return None
