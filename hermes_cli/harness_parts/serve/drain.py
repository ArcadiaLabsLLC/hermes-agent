"""The drain: the ``_DrainState`` record, the deadline policy, and the session's
drain lane (the monitor thread, the ONE terminal frame, the exit watchdog).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from hermes_cli.harness_parts.serve.constants import (
    _DRAIN_DEADLINE_FLOOR_SECONDS,
    _DRAIN_DEADLINE_MAX_SECONDS,
    _DRAIN_EXIT_DEADLINE_SECONDS,
    _DRAIN_PROGRESS_INTERVAL_SECONDS,
    DRAIN_TIMEOUT_EXIT_CODE,
)
from hermes_cli.harness_parts.serve.end_reason import EndReason

__layer__ = "lanes"

__all__ = [
    "DrainLane",
    "_DrainState",
    "_drain_deadline_seconds",
]


class _DrainState:
    """One drain in progress, and everything its terminal frame must account for.

    The counters are the point. A `drain_complete` that only said "done" would
    be a frame with the right NAME and no evidence — it could not distinguish a
    drain that let three turns land from one that refused them all, which is
    the difference between a safe restart and lost work.
    """

    __slots__ = (
        "started_monotonic",
        "deadline_seconds",
        "refused",
        "completed",
        "deadline_holds",
        "lock",
    )

    def __init__(self, deadline_seconds: float):
        self.started_monotonic = time.monotonic()
        self.deadline_seconds = deadline_seconds
        self.refused = 0
        self.completed = 0
        #: How many times the deadline expired and was NOT allowed to end the
        #: process because a chat turn was still in flight. Counted because
        #: "this restart is taking a while" and "this restart has been held
        #: open by recording safety four times" are different operator facts.
        self.deadline_holds = 0
        self.lock = threading.Lock()

    def note_refused(self) -> int:
        with self.lock:
            self.refused += 1
            return self.refused

    def note_completed(self) -> None:
        with self.lock:
            self.completed += 1

    def note_deadline_held(self) -> int:
        with self.lock:
            self.deadline_holds += 1
            return self.deadline_holds

    def counters(self) -> dict[str, Any]:
        with self.lock:
            return {
                "requests_refused": self.refused,
                "requests_completed": self.completed,
                "deadline_holds": self.deadline_holds,
            }

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_monotonic) * 1000)


def _drain_deadline_seconds(
    raw: Any, default: float, *, minimum: float = _DRAIN_DEADLINE_FLOOR_SECONDS
) -> float:
    """The EFFECTIVE deadline: the client's ask, floored by the server's.

    A client may lengthen a drain (up to the hard ceiling) and may not shorten
    it below the floor the caller passes for its TRANSPORT: the sanity floor on
    stdio (unchanged — that asker owns the process), the socket minimum on the
    socket lane. The floor is a parameter rather than a constant read in here
    precisely so the two lanes can differ and so the loop's own tests can run a
    drain in milliseconds; it is a SERVER-side parameter either way, and no
    field a client sends can lower it.
    """

    floor = max(0.0, float(minimum))
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return max(floor, float(default))
    return max(floor, min(float(raw), _DRAIN_DEADLINE_MAX_SECONDS))


class DrainLane:
    """The drain half of :class:`~hermes_cli.harness_parts.serve.session.ServeSession`:
    the monitor thread, the one terminal frame, and the exit watchdog."""

    def _finish_drain(self, code: int, frame: dict[str, Any]) -> None:
        """Emit the drain's terminal frame, then get the process out.

        Order is the contract: the frame is written and flushed BEFORE any
        exit path, because a drain that took the process down without
        accounting for what it refused and what it completed is
        indistinguishable from the crash the drain exists to replace.
        """

        # A drain has ONE terminal frame. The latch is taken before
        # anything is published, so a mid-drain EOF racing a completing
        # drain cannot follow ``drain_complete`` with ``drain_abandoned``.
        with self.drain_terminal_lock:
            if self.drain_terminal_published.is_set():
                return
            self.drain_terminal_published.set()
        self.drain_exit_code = code
        if code != 0:
            # Stuck workers: do NOT let the pool's context manager join
            # them (it would hang exactly as long as "forever"), and do not
            # trust a plain return either — concurrent.futures' atexit hook
            # joins worker threads on the way out of the interpreter.
            self.pool_shutdown_wait = False
        # THE WATCHDOG IS THE FIRST ACT, before the frame, the broadcast,
        # and the teardown — because every one of those can block. It used
        # to be armed after them, so the very steps most likely to hang ran
        # unwatched: broadcasting to a wedged reader parks a ``sendall``
        # for IO_TIMEOUT, and the hub's joins were a per-subscriber budget
        # that SUMMED. And the wakeup itself can block: observed live on
        # Windows (2026-08-13), closing the protocol descriptor a reader is
        # parked on does not return until that read does, and the child
        # outlived its own completed drain. From here to process exit
        # everything is inside one deadline.
        if self.hard_exit is not None:
            threading.Thread(
                target=self._force_exit_after_drain,
                args=(code,),
                name="harness-serve-drain-exit",
                daemon=True,
            ).start()
        self.frames.emit(frame)
        # Socket clients are owed the SAME terminal frame: a client that
        # asked for the drain over the socket, and every client that was
        # merely attached, learns how it ended on the transport it is on.
        # Broadcast before teardown — after ``_close_socket_lane`` there is
        # nobody left to tell.
        self._broadcast_lanes(frame)
        self._close_socket_lane(reason="drain")
        self._unregister_instance(reason="drain")
        # RL-16, and it has to be HERE rather than in an ``atexit`` hook:
        # the clean-drain tail can end in ``hard_exit``, which is
        # ``os._exit``, and the timeout tail always does — neither runs an
        # interpreter shutdown, so the fallback hook never fires on the one
        # path the launcher's restart verb actually takes.
        #
        # One word for all three drain outcomes (complete, timeout,
        # abandoned) on purpose: the sidecar answers *why did this runtime
        # end*, and the answer is "somebody drained it". HOW the drain went
        # is already on the wire, in the terminal frame this function just
        # published, with the counters that make it meaningful.
        self._note_end(EndReason.DRAINED)
        self._write_end()
        self.drain_finished.set()
        # The service park's wakeup, set at the SAME instant and for the
        # same reason as the reader's below: in service mode the main thread
        # is parked on this event rather than blocked on a pipe, so THIS is
        # what ``{"op":"drain","force":true}`` over the socket actually
        # pulls. Untouched and unread on every non-service boot.
        self.service_stop.set()
        if self.drain_wakeup is not None:
            try:
                self.drain_wakeup()
            except Exception:
                pass
        if self.hard_exit is None:
            # Unit-test path: the loop returns ``drain_exit_code`` and the
            # caller observes the frames. No process-level lever is pulled.
            return
        if code != 0:
            self.hard_exit(code)
            return
        # Clean drain: the reader gets its chance to unwind normally
        # (closed sockets, flushed writer, restored stdio) and the watchdog
        # above forces the exit if it does not. Nothing is waited on here.

    def _force_exit_after_drain(self, code: int) -> None:
        """Force the process down if the drain does not finish getting out.

        Armed at the START of ``_finish_drain``, so its deadline covers the
        WHOLE tail: publishing the terminal frame, broadcasting it, closing
        the socket lane (hub joins, connection closes, lock release),
        unregistering, waking the reader, and the reader unwinding. The
        normal case returns in milliseconds; anything else is a drained
        runtime that is still running, which is the state this exists to
        make impossible.

        Read from the module at call time on purpose — a test lowers it.
        """

        deadline = time.monotonic() + _DRAIN_EXIT_DEADLINE_SECONDS
        while time.monotonic() < deadline:
            if self.drain_finished.is_set() and self.reader_unwound.is_set():
                return
            time.sleep(0.02)
        if self.hard_exit is not None:
            self.hard_exit(code)

    def _drain_monitor(self, state: _DrainState) -> None:
        deadline = state.started_monotonic + state.deadline_seconds
        last_progress = state.started_monotonic
        while True:
            with self.inflight_lock:
                remaining = sorted(self.inflight)
                # Read in the SAME critical section as the pending set: a
                # timeout that decided "no chat turns" from a second,
                # later read could kill the turn that started in between.
                chat_turn_ids = sorted(
                    key for key, item in self.inflight.items() if item.is_chat_turn
                )
                # Read in the SAME critical section for the same reason,
                # one line later: a generation that started between two
                # reads would be killed by a timeout that had already
                # decided nothing was holding.
                long_run_ids = sorted(
                    key for key, item in self.inflight.items() if item.is_long_run
                )
            if not remaining:
                self._finish_drain(
                    0,
                    {
                        "event": "drain_complete",
                        "pid": os.getpid(),
                        "boot_id": self.boot_id,
                        **state.counters(),
                        "drain_ms": state.elapsed_ms(),
                    },
                )
                return
            now = time.monotonic()
            if now >= deadline:
                expiry = {
                    "event": "drain_timeout",
                    "pid": os.getpid(),
                    "boot_id": self.boot_id,
                    **state.counters(),
                    "drain_ms": state.elapsed_ms(),
                    "deadline_seconds": state.deadline_seconds,
                    # WHICH requests are stuck, by id — a timeout that
                    # only reported a count would leave the operator
                    # with nothing to correlate against the stack dump.
                    "stuck_request_ids": remaining,
                    # And WHY it is allowed to be stuck. A chat turn in
                    # flight is recording-safety work: this file's own
                    # contract says a supervisor must never recycle serve
                    # while ``chat_turns`` > 0, and a drain deadline firing
                    # `hard_exit` (which is `os._exit`) over one is that
                    # recycle by another name.
                    "held_by_chat_turns": len(chat_turn_ids),
                    "chat_turn_request_ids": chat_turn_ids,
                    # ADDITIVE, beside the two above rather than folded into
                    # them. `held_by_chat_turns` keeps its name and its
                    # meaning — a reader that only knows that key still
                    # reads a true number about chat turns, it just is not
                    # the whole reason the drain is being held any more.
                    # And the split is what the frame is FOR: "held by 1
                    # chat turn" and "held by 1 `characters rows`" are the
                    # same terminal:false with very different waits behind
                    # them, and an operator watching a restart deserves to
                    # know which.
                    "held_by_long_runs": len(long_run_ids),
                    "long_run_request_ids": long_run_ids,
                    "terminal": not (chat_turn_ids or long_run_ids),
                }
                if chat_turn_ids or long_run_ids:
                    # NOT terminal: say so, keep serving, re-arm. The frame
                    # is emitted every time the deadline lapses, so a
                    # supervisor watching a drain that is being held open
                    # sees each hold rather than silence.
                    state.note_deadline_held()
                    expiry.update(state.counters())
                    self.frames.emit(expiry)
                    self._broadcast_lanes(expiry)
                    deadline = now + state.deadline_seconds
                    last_progress = now
                    time.sleep(max(0.0, self.drain_poll_interval_seconds))
                    continue
                self._finish_drain(DRAIN_TIMEOUT_EXIT_CODE, expiry)
                return
            if now - last_progress >= _DRAIN_PROGRESS_INTERVAL_SECONDS:
                progress = {
                    "event": "drain_progress",
                    "pending": len(remaining),
                    "request_ids": remaining,
                    "drain_ms": state.elapsed_ms(),
                }
                self.frames.emit(progress)
                # The ONE drain frame that reached stdio and nothing else.
                # Its entire purpose is that "a draining service never looks
                # dead to a watchdog" — and the socket client IS such a
                # watchdog: it reads with a finite timeout and reports
                # `transport_failed` on silence. With the socket lane's
                # minimum deadline, a drain holding a chat turn open puts
                # the first socket-visible frame 30s out, so a healthy,
                # completing drain reported a transport failure and exit 6.
                self._broadcast_lanes(progress)
                last_progress = now
            time.sleep(max(0.0, min(self.drain_poll_interval_seconds, deadline - now)))
