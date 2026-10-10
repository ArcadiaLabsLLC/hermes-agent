"""The settle push: every chat-turn settle, pushed to the launcher until it acks.

Contract: ``docs/agent-runtime-harness/planned/settle-push-2026-10-10.md``. The
durable outbox is ``agent_runtime.chat_turn_settles``; this mixin is the serve's
half — record the settle in the worker's ``finally``, push it on the CONTROL
channel (the stdio frame writer and the loopback socket's broadcast, the channel
the drain announcements ride), never through the stream hub, so a raising stream
producer cannot cost a settle; re-send on the outbox's backoff; retire on
``settle_ack``.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from hermes_cli.harness_parts.serve.manifest import _is_gateway

__layer__ = "lanes"

__all__ = ["SettlePush", "SETTLE_PUSH_TICK_SECONDS"]

logger = logging.getLogger(__name__)

#: How often the pusher looks for due settles when nothing woke it.
SETTLE_PUSH_TICK_SECONDS = 1.0
#: Acked records are kept this long for idempotency, then pruned.
SETTLE_ACKED_RETENTION_SECONDS = 7 * 24 * 3600.0
_PRUNE_EVERY_SECONDS = 3600.0
_SESSION_ID_FLAG = "--session-id"


def _argv_flag(argv: Any, flag: str) -> str | None:
    items = [str(item) for item in argv or ()]
    for index, item in enumerate(items):
        if item == flag and index + 1 < len(items):
            return items[index + 1] or None
        if item.startswith(flag + "="):
            return item.split("=", 1)[1] or None
    return None


class SettlePush:
    """The settle-push half of :class:`~hermes_cli.harness_parts.serve.session.ServeSession`."""

    def _settle_store_scope(self) -> Any:
        from agent_runtime.profile_context import process_home_scope

        return process_home_scope(self.serve_request_home)

    def _record_turn_settle(self, request: Any, lines: Any, exit_code: int) -> None:
        """Durable BEFORE the exit frame; never raises (worker ``finally``)."""

        try:
            from agent_runtime.chat_turn_settles import (
                outcome_from_result_lines,
                record_settle,
            )
            from hermes_cli.harness_parts.serve.request_pool import turn_claim_key

            key = turn_claim_key(request.argv)
            if key is None:
                return
            with self._settle_store_scope():
                record = record_settle(
                    client_message_id=key[1],
                    session_id=_argv_flag(request.argv, _SESSION_ID_FLAG),
                    request_id=request.rid,
                    exit_code=exit_code,
                    outcome=outcome_from_result_lines(list(lines or ())),
                )
        except Exception:
            logger.warning("chat-turn settle could not be recorded", exc_info=True)
            self._service_log(
                {"event": "serve_settle_record_failed", "boot_id": self.boot_id,
                 "request_id": getattr(request, "rid", None)}
            )
            return
        if record is not None:
            self._wake_settle_pusher()

    def _wake_settle_pusher(self) -> None:
        wake = getattr(self, "settle_wake", None)
        if wake is not None:
            wake.set()

    def _start_settle_pusher(self) -> None:
        self.settle_wake = threading.Event()
        threading.Thread(
            target=self._settle_pusher_loop,
            name="harness-serve-settle-push",
            daemon=True,
        ).start()

    def _settle_pusher_loop(self) -> None:
        stop = self.liveness_stop
        last_prune = 0.0
        import time

        while not stop.is_set():
            try:
                self._push_due_settles()
                if time.monotonic() - last_prune >= _PRUNE_EVERY_SECONDS:
                    last_prune = time.monotonic()
                    self._prune_acked_settles()
            except Exception:
                logger.warning("settle push pass failed", exc_info=True)
            self.settle_wake.wait(SETTLE_PUSH_TICK_SECONDS)
            self.settle_wake.clear()

    def _push_due_settles(self) -> int:
        """One pass: push every due pending settle. Returns how many were pushed."""

        from agent_runtime.chat_turn_settles import (
            STATE_UNDELIVERED,
            due_settles,
            note_push,
        )

        pushed = 0
        with self._settle_store_scope():
            for record in due_settles():
                delivered = self._deliver_settle_frame(record.frame())
                updated = note_push(record.settle_id, delivered_to=delivered)
                pushed += 1 if delivered else 0
                if updated is not None and updated.state == STATE_UNDELIVERED:
                    self._service_log(
                        {
                            "event": "serve_settle_undelivered",
                            "boot_id": self.boot_id,
                            "settle_id": updated.settle_id,
                            "client_message_id": updated.client_message_id,
                            "session_id": updated.session_id,
                            "exit_code": updated.exit_code,
                            "attempts": updated.attempts,
                            "reason": updated.undelivered_reason,
                        }
                    )
        return pushed

    def _prune_acked_settles(self) -> None:
        from agent_runtime.chat_turn_settles import prune_acked

        with self._settle_store_scope():
            prune_acked(older_than_seconds=SETTLE_ACKED_RETENTION_SECONDS)

    def _deliver_settle_frame(self, frame: dict[str, Any]) -> int:
        """Send a settle *frame* on the control channel. Returns how many sinks took it."""

        return self._deliver_control_frame(frame)

    def _deliver_control_frame(self, frame: dict[str, Any]) -> int:
        """Send *frame* on the control channel. Returns how many sinks took it.

        Also the transport of a queued chat turn's stream
        (``serve.queued_turns``), which has no request of its own to answer.

        Stdio counts only when a launcher can be reading it: not detached, and
        not ``--service`` (whose stdio is the launcher's ``DEVNULL``). The
        socket's count is ``broadcast``'s own. The gateway door is excluded on
        purpose — a paired device is not the launcher the ruling names.
        """

        delivered = 0
        if not self.service and not getattr(self.frames, "detached", False):
            try:
                self.frames.emit(frame)
                delivered += 1
            except Exception:
                pass
        with self.lane_lock:
            server = self.socket_server
        if server is not None:
            try:
                delivered += int(server.broadcast(frame) or 0)
            except Exception:
                pass
        return delivered

    def _op_settle_ack(
        self, message: dict[str, Any], sink: Any, connection: Any
    ) -> str | None:
        """``{"op":"settle_ack","settle_id":…}`` — retire a pushed settle. Idempotent."""

        if _is_gateway(connection):
            sink.emit(
                {
                    "event": "error",
                    "error": "op_not_available_on_gateway",
                    "detail": "settles are pushed to the local launcher; only it acks them",
                }
            )
            return None
        from agent_runtime.chat_turn_settles import ack_settle, settle_id_for

        settle_id = message.get("settle_id")
        cmid = message.get("client_message_id")
        if not isinstance(settle_id, str) or not settle_id.strip():
            if isinstance(cmid, str) and cmid.strip():
                session = message.get("session_id")
                settle_id = settle_id_for(
                    session if isinstance(session, str) else None, cmid.strip()
                )
            else:
                sink.emit(
                    {
                        "id": message.get("id"),
                        "event": "error",
                        "error": "invalid_settle_ack",
                        "detail": "settle_ack names a settle_id, or a client_message_id (+ session_id)",
                    }
                )
                return None
        with self._settle_store_scope():
            retired = ack_settle(settle_id.strip())
        sink.emit(
            {
                "id": message.get("id"),
                "event": "settle_acked",
                "settle_id": settle_id.strip(),
                "retired": retired,
            }
        )
        return None
