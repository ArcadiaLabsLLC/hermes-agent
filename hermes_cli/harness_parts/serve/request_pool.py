"""The serve's request workers, and the one-handler rule for a chat turn (lane h-pool-starve).

**Two lanes, one pool object.** Every request ran on one four-worker pool, so a
chat turn queued behind whatever held the workers. On 2026-10-06 12:04 four
``harness stream`` hydrates parked on a snapshot build held all four for 83 s;
Neko turn ``b00deebf`` waited 24 s for a worker
(``chat_turn_accept_to_anchor … queue_ms=24111``), the launcher declared the
request hung and re-sent it. A reserved slot cannot be built on a
``ThreadPoolExecutor`` (a request that waits for permission still holds the
worker it waits on), and teaching every hydrate to wait without a worker is a
rewrite of the stream lane; a second executor that only chat turns use is the
smallest change that makes the guarantee unconditional: a chat turn queues
behind other chat turns and nothing else. :class:`RequestPool` keeps the one
``submit`` / ``shutdown`` face every caller already uses (the drain joins both
lanes) and adds :meth:`RequestPool.submit_turn`.

**One turn, one handler.** A turn the launcher re-sent (same
``--client-message-id``) while the first presentation still waited for a worker
used to run TWO handlers: the re-send anchored at 12:04:45.700 and the original
anchored again at 12:04:47.297. The turn journal kept that correct (the loser is
answered ``chat_turn_duplicate_in_flight`` after the lease) but only after the
second handler had paid the turn's whole preparation beside the first.
:class:`TurnClaims` refuses the second at the worker's door instead: the first
presentation of a ``(verb, client_message_id)`` to reach a worker claims it
until its exit frame; another one reaching a worker meanwhile runs no handler
and is answered ``chat_turn_duplicate_in_flight`` (re-present this id; the
journal answers once the turn settles). A presentation after the turn ended is
the journal's to answer, exactly as before.

**A standing stream has a lane of its own (lane w1015b-con-x).** ``harness stream``
never returns: the launcher holds two to four of them per attachment, and on the
shared lane each one held a worker for the life of its connection. The deferred
method replies (``RpcContext.spawn_reply`` -- ``history.pending``, settings,
models, every console inspection) ran on what was left. Live 2026-10-15 a QA
serve held three streams (``serve_stream_worker_reclaimed`` req-1, req-2, req-7)
on four workers, and an earlier boot attached four at once, so ``history.pending``
queued behind them and the launcher logged ``rpc_timeout`` twice per new chat.
:meth:`RequestPool.submit_stream` takes them off the shared lane; its width
(:data:`STREAM_LANE_WORKERS`) is a ceiling on threads, not a reservation.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: ``chat_turn_duplicate_refused``: a second presentation that ran no handler.
DUPLICATE_REFUSED_RECEIPT = (
    "chat_turn_duplicate_refused request=%s twin=%s verb=%s client_message_id=%s"
)
#: The code the journal's own duplicate-in-flight answer exits with.
DUPLICATE_IN_FLIGHT_EXIT_CODE = 2
_CLIENT_MESSAGE_ID_FLAG = "--client-message-id"
#: Threads the standing-stream lane may grow to. Streams are infinite, so this
#: bounds how many may run at once; a closed connection's are reclaimed.
STREAM_LANE_WORKERS = 32
#: Workers of the read lane (:meth:`RequestPool.submit_read`): reads only, so a few are enough.
READ_LANE_WORKERS = 4
#: A shared-lane wait or run at least this long is logged (:data:`SHARED_LANE_SLOW_RECEIPT`).
SHARED_LANE_SLOW_MS = 1000
SHARED_LANE_SLOW_RECEIPT = "shared_lane_slow lane=%s label=%s queue_ms=%d run_ms=%d busy_at_submit=%d origin=%s"
#: Turn first (owner 2026-11-23, lane w1123q-replytimings): a shared- or read-lane job that would
#: START while a chat turn is between its accept and its ``request_sent`` waits for that turn's
#: request to leave, at most this long. Read live on the owner's serve: a Home turn's own work was
#: 453-625 ms of CPU, yet its accept -> ``request_sent`` took 8.1-11.2 s, because the reads the new
#: chat set off (``conversation.read`` x15, ``.list``, ``.models``, ``provider.list``; 0.2-12 s each)
#: held the GIL beside it (``send_prep_receipt own_cpu_ms`` / ``top_threads``). Bounded, so a read
#: is late by at most this, never starved; a job a turn submits itself is never held.
TURN_PREP_HOLD_MAX_S = 2.0
_TURN_PREP_POLL_S = 0.025
#: One line per held job (``held_ms`` >= :data:`TURN_PREP_HOLD_RECEIPT_MS`).
TURN_PREP_HOLD_RECEIPT = "lane_held_for_turn lane=%s label=%s held_ms=%d origin=%s"
TURN_PREP_HOLD_RECEIPT_MS = 50
#: The typed refusal a 33rd standing stream gets (never a silent queue behind 32 infinite ones).
STREAM_LANE_FULL = "stream_lane_full"


class StreamLaneFull(RuntimeError):
    """The standing-stream lane already runs :data:`STREAM_LANE_WORKERS` streams."""

    code = STREAM_LANE_FULL


#: The rollup's window: one ``lane_rollup`` line per lane per this many seconds of traffic.
LANE_ROLLUP_WINDOW_S = 60.0
#: How many methods and origins a rollup line names (the busiest; the rest are counted in the totals).
LANE_ROLLUP_TOP = 8
LANE_ROLLUP_RECEIPT = (
    "lane_rollup lane=%s window_s=%d requests=%d queue_ms=%d run_ms=%d max_queue_ms=%d methods=%s origins=%s"
)


class LaneRollup:
    """Every shared- and read-lane job, counted (RT-FU-EVERY-REQUEST-SAYS-WHO-IN-ETERNIA-ASKED-AND-HOW-LONG-IT-WAITED).

    ``shared_lane_slow`` names only the jobs that waited or ran a second; this counts all of them:
    per lane, requests by method and by origin, and the queued and run totals. A lane's window
    closes at the first job that ends :data:`LANE_ROLLUP_WINDOW_S` after the window opened, which
    logs ONE :data:`LANE_ROLLUP_RECEIPT` line for it — no timer thread, no line for an idle lane,
    no line per request. A record is two dict increments under one lock."""

    def __init__(self, window_s: float = LANE_ROLLUP_WINDOW_S) -> None:
        self.window_s = float(window_s)
        self._lock = threading.Lock()
        self._windows: dict[str, dict[str, Any]] = {}

    def record(self, lane: str, label: str, origin: str, queue_ms: int, run_ms: int, *, now: float) -> None:
        with self._lock:
            window = self._windows.get(lane)
            if window is None:
                window = self._windows[lane] = _open_window(now)
            window["requests"] += 1
            window["queue_ms"] += queue_ms
            window["run_ms"] += run_ms
            window["max_queue_ms"] = max(window["max_queue_ms"], queue_ms)
            window["methods"][label] = window["methods"].get(label, 0) + 1
            window["origins"][origin] = window["origins"].get(origin, 0) + 1
            if now - window["opened"] < self.window_s:
                return
            self._windows[lane] = _open_window(now)
        logger.info(LANE_ROLLUP_RECEIPT, lane, int(round(now - window["opened"])), window["requests"],
                    window["queue_ms"], window["run_ms"], window["max_queue_ms"],
                    _top(window["methods"]), _top(window["origins"]))


def _open_window(now: float) -> dict[str, Any]:
    return {"opened": now, "requests": 0, "queue_ms": 0, "run_ms": 0, "max_queue_ms": 0, "methods": {}, "origins": {}}


def _top(counts: dict[str, int]) -> str:
    """``name:count`` of the busiest :data:`LANE_ROLLUP_TOP`, comma-joined (``-`` when none)."""

    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:LANE_ROLLUP_TOP]
    return ",".join(f"{name}:{count}" for name, count in ranked) or "-"


class RequestPool:
    """The shared request lane and the chat-turn lane, each ``size`` workers, the
    standing-stream lane (:data:`STREAM_LANE_WORKERS`) and the read lane
    (:data:`READ_LANE_WORKERS`)."""

    def __init__(self, size: int) -> None:
        workers = max(1, int(size))
        self.shared = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="harness-serve")
        self.turns = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="harness-serve-turn")
        self.streams = ThreadPoolExecutor(
            max_workers=STREAM_LANE_WORKERS, thread_name_prefix="harness-serve-stream")
        self._stream_lock = threading.Lock()
        self._streams_running = 0
        self.reads = ThreadPoolExecutor(max_workers=READ_LANE_WORKERS, thread_name_prefix="harness-serve-read")
        self._shared_lock = threading.Lock()
        self._running = {"shared": 0, "read": 0}
        #: Every shared- and read-lane job counted, one line per lane per minute (``lane_rollup``).
        self.rollup = LaneRollup()

    def submit(self, fn: Callable[..., Any], *args: Any, label: str = "-", origin: str = "-") -> Future:
        """Work on the shared lane, timed: a wait or a run past :data:`SHARED_LANE_SLOW_MS` logs
        ``shared_lane_slow`` (its label, queue_ms, run_ms and the workers busy when it was
        submitted), so a deferred reply the client gave up on (``rpc_timeout``) names what held
        the lane (lane w1123k-chatissues)."""

        return self._timed_submit(self.shared, "shared", fn, args, label, origin)

    def submit_read(self, fn: Callable[..., Any], *args: Any, label: str = "-", origin: str = "-") -> Future:
        """A bounded read a person waits on (``serve_rpc.protocol.defer_read``: the chat list, a
        console inspection, history recovery) on the read lane (:data:`READ_LANE_WORKERS`), which no
        argv request or turn ever takes, so work parked on a busy chat cannot starve it. Timed like
        :meth:`submit` (``lane=read``)."""

        return self._timed_submit(self.reads, "read", fn, args, label, origin)

    def _timed_submit(self, lane: ThreadPoolExecutor, name: str, fn: Callable[..., Any],
                      args: tuple[Any, ...], label: str, origin: str = "-") -> Future:
        submitted = time.monotonic()
        with self._shared_lock:
            busy = self._running[name]
        from agent_runtime.turn_activity import inside_admitted_turn

        own_turn = inside_admitted_turn()

        def _timed() -> Any:
            if not own_turn:
                _hold_for_turn_prep(name, label, origin)
            started = time.monotonic()
            with self._shared_lock:
                self._running[name] += 1
            try:
                return fn(*args)
            finally:
                ended = time.monotonic()
                with self._shared_lock:
                    self._running[name] -= 1
                queue_ms = int((started - submitted) * 1000)
                run_ms = int((ended - started) * 1000)
                # MUTATION: drop this receipt and
                # test_a_reply_queued_behind_busy_workers_names_its_wait reddens.
                if queue_ms >= SHARED_LANE_SLOW_MS or run_ms >= SHARED_LANE_SLOW_MS:
                    logger.info(SHARED_LANE_SLOW_RECEIPT, name, label, queue_ms, run_ms, busy, origin)
                # MUTATION: drop this record and test_the_rollup_counts_every_request reddens.
                self.rollup.record(name, label, origin, queue_ms, run_ms, now=ended)

        return lane.submit(_timed)

    def submit_turn(self, fn: Callable[..., Any], *args: Any) -> Future:
        return self.turns.submit(fn, *args)

    def submit_stream(self, fn: Callable[..., Any], *args: Any) -> Future:
        """A standing stream, counted: past :data:`STREAM_LANE_WORKERS` it is REFUSED
        (:class:`StreamLaneFull`), because a stream never returns and a queued one would
        wait forever behind the 32 that hold the threads."""

        with self._stream_lock:
            if self._streams_running >= STREAM_LANE_WORKERS:
                logger.warning("stream_lane_full running=%d ceiling=%d", self._streams_running, STREAM_LANE_WORKERS)
                raise StreamLaneFull(f"{self._streams_running} standing streams already run")
            self._streams_running += 1
            running = self._streams_running
        logger.info("stream_lane_occupancy running=%d ceiling=%d", running, STREAM_LANE_WORKERS)

        def _counted() -> Any:
            try:
                return fn(*args)
            finally:
                with self._stream_lock:
                    self._streams_running -= 1

        try:
            return self.streams.submit(_counted)
        except BaseException:
            with self._stream_lock:
                self._streams_running -= 1
            raise

    def shutdown(self, wait: bool = True) -> None:
        """Stop every lane taking work, then (``wait``) join them all."""

        lanes = (self.shared, self.turns, self.streams, self.reads)
        for lane in lanes:
            lane.shutdown(wait=False)
        if wait:
            for lane in lanes:
                lane.shutdown(wait=True)


def _hold_for_turn_prep(lane: str, label: str, origin: str = "-") -> int:
    """Wait while any chat turn is before its ``request_sent`` (:data:`TURN_PREP_HOLD_MAX_S` at most).

    "Before its request_sent" is the two existing authorities: a turn ACCEPTED and not yet anchored
    (``turn_activity.chat_turns_accepted``) or anchored and not yet sent
    (``idle_turn_keeper.turn_window_open``). Returns the milliseconds held.
    """

    from agent_runtime.idle_turn_keeper import turn_window_open
    from agent_runtime.turn_activity import chat_turns_accepted

    started = time.monotonic()
    deadline = started + TURN_PREP_HOLD_MAX_S
    # MUTATION: return 0 here and test_a_read_waits_for_a_preparing_turn_to_send reddens.
    while (chat_turns_accepted() > 0 or turn_window_open()) and time.monotonic() < deadline:
        time.sleep(_TURN_PREP_POLL_S)
    held_ms = int((time.monotonic() - started) * 1000)
    if held_ms >= TURN_PREP_HOLD_RECEIPT_MS:
        logger.info(TURN_PREP_HOLD_RECEIPT, lane, label, held_ms, origin)
    return held_ms


def turn_claim_key(argv: Any) -> tuple[str, str] | None:
    """``(verb, client_message_id)`` of a chat-turn argv, or ``None`` when it names no id."""

    tail = [str(item) for item in argv or ()]
    if tail and tail[0] == "harness":
        tail = tail[1:]
    verb = " ".join(tail[:2])
    for index, item in enumerate(tail):
        if item == _CLIENT_MESSAGE_ID_FLAG and index + 1 < len(tail):
            value = tail[index + 1]
        elif item.startswith(_CLIENT_MESSAGE_ID_FLAG + "="):
            value = item.split("=", 1)[1]
        else:
            continue
        return (verb, value) if value else None
    return None


class TurnClaims:
    """Which request is running each ``(verb, client_message_id)`` in this serve."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[tuple[str, str], str] = {}

    def claim(self, key: tuple[str, str] | None, rid: str) -> str | None:
        """Claim ``key`` for ``rid``; the twin's rid when another request holds it."""

        if key is None:
            return None
        with self._lock:
            holder = self._running.get(key)
            if holder is not None and holder != rid:
                return holder
            self._running[key] = rid
            return None

    def release(self, key: tuple[str, str] | None, rid: str) -> None:
        if key is None:
            return
        with self._lock:
            if self._running.get(key) == rid:
                del self._running[key]
