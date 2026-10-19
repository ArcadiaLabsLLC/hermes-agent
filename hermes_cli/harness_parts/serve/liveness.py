"""The serve's liveness: the ``busy`` frame, the liveness pump, and the per-request
silence report.

The pump runs on its own thread for the life of the serve
(``ServeSession._start_background_workers``); ``ping`` answers with
:meth:`LivenessPump._busy_frame` (``handle_message``).
"""

from __future__ import annotations

import time
from typing import Any

from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest
from hermes_cli.harness_parts.serve.constants import _REQUEST_SILENCE_SECONDS

__layer__ = "lanes"

__all__ = ["LivenessPump"]


class LivenessPump:
    """The liveness half of :class:`~hermes_cli.harness_parts.serve.session.ServeSession`."""

    def _busy_frame(self) -> dict[str, Any]:
        from .idle_drain import native_pending_count

        with self.inflight_lock:
            pending = len(self.inflight)
            chat_turns = sum(1 for item in self.inflight.values() if item.is_chat_turn)
            long_runs = sum(1 for item in self.inflight.values() if item.is_long_run)
            subscriptions = sum(
                1 for item in self.inflight.values() if item.is_runtime_stream
            )
        # ``long_runs`` and ``subscriptions``/``work`` are ADDITIVE.
        # ``chat_turns`` and ``pending`` keep their exact meanings and their
        # exact names because the launcher decodes them by those names
        # (`mission_control_serve_session_io.dart`, the `busy` case →
        # `MissionServeBusySignal.chatTurns`), and a supervisor that learned to
        # read a renamed key would be a supervisor that stopped reading the old
        # one mid-upgrade.
        #
        # ``subscriptions`` counts the STANDING requests — `harness stream`,
        # infinite by design, which the launcher holds two of for the life of
        # the attachment. ``work`` is everything else. The distinction is not
        # cosmetic: an attached launcher used to make an IDLE runtime answer
        # `pending: 2` forever (measured 2026-09-05), so `pending > 0` — the
        # only "is it working?" test the frame offered — was true on a service
        # doing nothing at all. ``work`` is the number that goes back to zero,
        # and it is what the liveness pump keys on.
        native = native_pending_count(self.conversation_owner)
        discussions = native_pending_count(self.discussion_owner)
        return {
            "event": "busy",
            "chat_turns": chat_turns,
            "long_runs": long_runs,
            "pending": pending,
            "subscriptions": subscriptions,
            "work": pending - subscriptions + native + discussions,
            "native_conversations": native,
            "discussions": discussions,
        }

    def _report_quiet_requests(self, pending: list[_ArgvRequest]) -> None:
        """Describe every request that has gone quiet, to the lane that asked.

        ``busy`` says the SERVICE is alive and carries a count. It cannot
        answer the question a waiting client actually has, which is about ONE
        request: has mine started, or is it behind the pool? This does, by id,
        on that request's own sink — so the answer arrives on the connection
        that is waiting for it rather than on stdout, where a socket client
        cannot see it.

        The budget is read from the module on every lap, so a test lowers it.

        ``harness stream`` is deliberately excluded: it is the infinite
        subscription, it is silent between events BY DESIGN, and it has the
        stream lane's own liveness. Everything else that produces nothing for
        this long is a fact an operator wants.
        """

        budget = max(0.0, float(_REQUEST_SILENCE_SECONDS))
        now = time.monotonic()
        depth = len(pending)
        for request in pending:
            if request.is_runtime_stream:
                continue
            waited = now - request.submitted_monotonic
            if waited < budget:
                continue
            last = request.progress_monotonic
            if last is not None and (now - last) < budget:
                continue
            request.progress_monotonic = now
            started = request.started_monotonic
            frame = {
                "id": request.rid,
                "event": "request_progress",
                # The one field that matters. "queued" means no handler code
                # has run, so nothing has been mutated and a retry is free;
                # "running" means side effects may already have landed.
                "state": "running" if started is not None else "queued",
                "waited_ms": int(waited * 1000),
                "running_ms": (
                    0 if started is None else int((now - started) * 1000)
                ),
                "pending": depth,
                "pool_size": self.pool_size,
            }
            target = request.sink if request.sink is not None else self.frames
            try:
                target.emit(frame)
            except Exception:
                # Same contract as the pump that calls this: telemetry must
                # never take down the loop it describes.
                pass

    def _liveness_pump(self) -> None:
        while not self.liveness_stop.wait(self.liveness_pump_interval_seconds):
            with self.inflight_lock:
                pending = list(self.inflight.values())
            if not pending:
                continue
            busy_frame = self._busy_frame()
            # STANDING SUBSCRIPTIONS ARE NOT WORK. `harness stream` never
            # ends by design, so an attached launcher keeps two of them in
            # `inflight` for the life of the attachment — and this pump,
            # which only ever asked "is anything pending?", therefore
            # announced `busy` every 5s to a runtime that was doing
            # NOTHING (measured 2026-09-05: `chat_turns: 0, long_runs: 0,
            # pending: 2`, forever). `_report_quiet_requests` had already
            # learned to exclude them, and says why; this is the same
            # exclusion applied to the frame the launcher actually reads.
            # `ping` is untouched — a supervisor that ASKS still gets every
            # count, because silence is the pump's rule, not the frame's.
            if busy_frame["work"] > 0:
                try:
                    self.frames.emit(busy_frame)
                except Exception:
                    # Writer gone — the main loop is on its way down too.
                    return
                # And to every SOCKET client, for the identical reason the
                # comment above gives for stdout. This lane was left behind
                # when the drain path learned the same lesson: "the socket
                # client IS such a watchdog: it reads with a finite timeout
                # and reports `transport_failed` on silence" (see the
                # drain's `_broadcast_lanes(progress)`). Measured
                # 2026-08-27: an authenticated socket connection waiting on
                # a `characters list` read ZERO frames for >120s while this
                # pump was emitting `busy` the whole time — to stdout,
                # where that client could not see it.
                #
                # Best-effort and never fatal: `_broadcast_lanes` is a later
                # local of this loop, so an early tick can find it unbound,
                # and a broadcast failing must not stop the liveness the
                # launcher keys on.
                try:
                    self._broadcast_lanes(busy_frame)
                except Exception:
                    pass
            # The per-request half: `busy` is a count, and a client waiting
            # on ONE id needs to know whether that id has started. It gets
            # the FULL pending list — it does its own stream exclusion, and
            # a subscription-only lap can still be the lap on which an
            # argv request crosses the silence budget.
            self._report_quiet_requests(pending)
