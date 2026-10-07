"""Is a chat turn ADMITTED right now? One counter, one authority.

**The gap this closes.** ``profile_runner.agent_runs_in_flight()`` counts real
agent runs: ``_counted_agent_run`` increments at ``ProfileAgentRunner.run()``'s
entry and decrements at its exit. Two consumers take decisions on it — the
snapshot demote deferral (``stream._defer_demote_build_for_active_turns``) and
the chat-actor prewarm's yield (``persona_chat_actor_prewarm.prewarm_chat_actor``,
two reads) — and both were written when "a turn is happening" and "a run is in
flight" looked like the same fact.

They are not. A mission-chat turn is admitted at the handler's monotonic anchor
and does its whole pre-admit assembly — config, persona, instance store, the
chat-lane visibility bundle, the turn context, the prompt-observability row, the
write-ahead persist — before any runner exists. Measured on this PC 2026-09-07
(``planned/chat-turn-prep-cost.md`` §0.1): that span was 906 ms on the one turn
nothing else was running and 2,796–3,172 ms on the two turns a led core build
and a 5,750 ms actor prewarm overlapped it. Both of those overlaps are things
that YIELD to a live turn, and neither could see one, because the span is
invisible to ``_ACTIVE_RUNS`` by construction. Turn 3's three
``snapshot_build_deferred`` receipts prove the mechanism works where it can see;
turns 1 and 2 prove where it cannot.

**CP-2, stated:** an ADMITTED turn owns the GIL, not only a RUNNING one. This
module is that counter — incremented where the turn's :class:`TurnPhaseMarks`
is constructed at the handler anchor, decremented when the handler exits by any
path. ``agent_runs_in_flight()`` keeps its meaning and its callers unchanged;
the two consumers above will read ``admitted() or running()``.

**What Stage 6 does with it, and what it does NOT.** Stage 6 builds this as an
INSTRUMENT and nothing more: the deferral logs ``admitted_at_exit=`` beside its
existing ``runs_in_flight_at_exit=``, and the turn record gains
``prewarm_overlapped``. No decision anywhere reads this counter yet — that is
Stage 7, and keeping the two landings apart is what lets Stage 7's numbers be
read against receipts this stage already put on the record.

**Why a module and not a flag on the marks object.** The readers are a stream
hub thread and a prewarm worker thread; neither holds the turn's marks, and
neither may. The counter is therefore process-scoped, exactly as
``_ACTIVE_RUNS`` is, and for the same reason: the question is "is this PROCESS
inside a turn", asked by something that is about to spend the same GIL.

**Cost.** One lock acquisition on entry and one on exit, per TURN.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

__layer__ = "policy"

_logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_ADMITTED = 0
#: Is THIS context inside an admitted turn? A build that stands aside for live
#: turns (``snapshot_turn_yield``) must never wait on the turn that is running it.
_IN_TURN: ContextVar[bool] = ContextVar("hermes_in_admitted_turn", default=False)


def inside_admitted_turn() -> bool:
    """True on the thread (context) of an admitted turn's own handler."""

    return _IN_TURN.get()


# ── the latency-critical windows (h-chatperf, 2026-10-03) ─────────────────────
#
# An admitted turn is not uniformly sensitive. Its operator waits on two spans:
# the pre-admit assembly (anchor -> the published start row) and each provider
# call (``request_assembled`` -> ``provider_returned``). Cold turn ``1e4c06ba`` spent
# 1.3 s in the first and 9.0 s in the second with a core build beside it. The
# rest of a turn -- the agent bootstrap, a tool round of minutes -- is where the
# stream lane's builds carry the turn's OWN start row and running-work state to
# every subscriber, so standing aside for the whole admitted window would hide
# the turn from the board it is running on. A HOT window is the span a build
# must not share; :func:`hot_turn_windows` counts the open ones.

_HOT = 0
_HOT_WINDOW: ContextVar["HotWindow | None"] = ContextVar("hermes_turn_hot_window", default=None)


class HotWindow:
    """One turn's latency-critical window: open or closed, idempotently.

    Opened at the turn's anchor, closed once the start row is published,
    reopened at each provider dispatch and closed when it returns; always closed when the
    turn exits, whatever the path, so a window can never leak into the process.
    """

    __slots__ = ("_open",)

    def __init__(self) -> None:
        self._open = False

    def open(self) -> None:
        global _HOT
        with _LOCK:
            if not self._open:
                self._open = True
                _HOT += 1

    def close(self) -> None:
        global _HOT
        with _LOCK:
            if self._open:
                self._open = False
                _HOT -= 1

    @property
    def is_open(self) -> bool:
        with _LOCK:
            return self._open


def hot_turn_windows() -> int:
    """How many turns are inside a latency-critical window RIGHT NOW."""

    with _LOCK:
        return _HOT


def current_hot_window() -> "HotWindow | None":
    """The admitted turn's window, on its handler's own thread; else ``None``."""

    return _HOT_WINDOW.get()


def chat_turns_admitted() -> int:
    """How many mission-chat turns this process is inside RIGHT NOW.

    ``0`` is a measurement: no turn is admitted. There is no "unknown" here —
    the counter is this module's own and always answerable. Callers that reach
    it across an import boundary they cannot assume (``agent_runtime.stream``,
    the harness command parts) turn an unreachable module
    into ``None`` at THEIR seam, so an absence stays distinguishable from a
    zero on the record.
    """

    with _LOCK:
        return _ADMITTED


# ── accepted, not yet anchored (h-prewarm-order, 2026-10-06) ──────────────────
#
# A turn exists before its handler's anchor: the serve ACCEPTS it (the method
# lane acks, the argv lane takes the request) and puts it on the pool, and only
# the handler's first instruction admits it. Turn ``5377d205`` was accepted at
# 01:25:04.23 and anchored at 04.909; a prewarm reading ``chat_turns_admitted()``
# at 04.73 saw nothing. :class:`AcceptedTurn` is that window: counted from the
# pool submit until :func:`admitted_turn` takes the turn over (or the request
# ends without reaching a handler), and it carries the stamps the
# accept-to-anchor receipt reads.

#: Live holds. Weak, so a request that never reached a worker (a cancelled
#: future, a test's fake pool) stops counting once it is collected.
_ACCEPTED: "weakref.WeakSet[AcceptedTurn]" = weakref.WeakSet()
_CURRENT_ACCEPT: ContextVar["AcceptedTurn | None"] = ContextVar("hermes_accepted_turn", default=None)

#: One INFO line per anchored turn that came through the serve's pool: where the
#: span between the accept and the handler's ``TurnPhaseMarks()`` went.
#: ``queue`` is submit -> the worker's first instruction, ``link`` the Launcher
#: app-function bind (a wire round trip when the connection's catalog is not
#: held yet), ``dispatch`` the rest (argv parse, the handler's own imports).
#: ``turn`` is the client message id, the key the turn record and the Launcher's
#: ``[MissionChatTiming]`` line carry (``observe turn-timing`` joins on it).
ACCEPT_TO_ANCHOR_RECEIPT = (
    "chat_turn_accept_to_anchor request=%s queue_ms=%d link_ms=%d dispatch_ms=%d total_ms=%d turn=%s"
)


class AcceptedTurn:
    """One chat turn from its pool submit to its anchor. ``release`` is idempotent."""

    __slots__ = ("request_id", "submitted", "started", "link_bound", "_held", "__weakref__")

    def __init__(self, request_id: str = "") -> None:
        self.request_id = request_id
        self.submitted = time.monotonic()
        self.started: float | None = None
        self.link_bound: float | None = None
        with _LOCK:
            self._held = True
            _ACCEPTED.add(self)

    def release(self) -> None:
        with _LOCK:
            self._release_locked()

    def _release_locked(self) -> None:
        self._held = False
        _ACCEPTED.discard(self)

    def receipt_args(self, anchored: float) -> tuple:
        started = self.started if self.started is not None else self.submitted
        bound = self.link_bound if self.link_bound is not None else started

        def ms(a: float, b: float) -> int:
            return max(0, int((b - a) * 1000))

        return (
            self.request_id or "-", ms(self.submitted, started), ms(started, bound),
            ms(bound, anchored), ms(self.submitted, anchored),
        )


def _turn_name(turn_id) -> str:
    """``admitted_turn``'s ``turn_id`` (a string or a zero-argument callable) as a receipt value."""

    try:
        value = turn_id() if callable(turn_id) else turn_id
    except Exception:
        value = None
    return str(value).split()[0] if value and str(value).strip() else "-"


def chat_turns_accepted() -> int:
    """How many chat turns are accepted and not yet anchored (or ended) RIGHT NOW."""

    with _LOCK:
        return len(_ACCEPTED)


@contextmanager
def accepted_turn_scope(accepted: "AcceptedTurn | None") -> Iterator[None]:
    """Bind *accepted* for the worker's run; release it on the way out, whatever the path."""

    token = _CURRENT_ACCEPT.set(accepted)
    try:
        yield
    finally:
        _CURRENT_ACCEPT.reset(token)
        if accepted is not None:
            accepted.release()


# ── which turns a span overlapped (h-snap-worker, 2026-10-06) ─────────────────
#
# The counters above answer "is a turn admitted"; a build receipt also has to
# say WHICH turns it shared the process with. Same owner, same lock: each
# admitted turn is an entry for its life, and an open watch collects every
# entry admitted at its start or at any moment until it closes -- a turn that
# began and ended inside a build is overlapped just as much as one that spans
# it. The id is read LAZILY: the mission-chat handler mints a missing
# ``client_message_id`` a few statements after the anchor, and the receipt is
# rendered after the build, when the minted id exists.

_ENTRIES: dict[int, "str | Callable[[], object] | None"] = {}
_WATCHES: list["TurnOverlapWatch"] = []
_ENTRY_TOKENS = itertools.count(1)
#: The most ids one receipt names; the rest are counted, never dropped silently.
TURN_IDS_SHOWN = 8


def _render_turn_id(source) -> str:
    try:
        value = source() if callable(source) else source
    except Exception:
        value = None
    text = str(value or "").strip()
    if not text:
        return "?"
    # One whitespace-free, comma-free token: the receipt is ``key=value`` pairs.
    return "".join(ch if (ch.isalnum() or ch in "-_.:") else "_" for ch in text)[:120]


class TurnOverlapWatch:
    """The admitted turns one span overlapped: those in flight at its start, plus
    every turn admitted before it closes."""

    __slots__ = ("_entries",)

    def __init__(self) -> None:
        self._entries: dict[int, object] = {}

    def turn_ids(self) -> list[str]:
        """Distinct ids in admission order; an anonymous turn reads ``?``."""

        with _LOCK:
            sources = [self._entries[token] for token in sorted(self._entries)]
        ids: list[str] = []
        for source in sources:
            rendered = _render_turn_id(source)
            if rendered == "?" or rendered not in ids:
                ids.append(rendered)
        return ids

    def receipt_value(self) -> str:
        """``id1,id2`` (``-`` for none, ``+N`` when more than :data:`TURN_IDS_SHOWN`)."""

        ids = self.turn_ids()
        if not ids:
            return "-"
        shown = ",".join(ids[:TURN_IDS_SHOWN])
        hidden = len(ids) - TURN_IDS_SHOWN
        return f"{shown},+{hidden}" if hidden > 0 else shown


@contextmanager
def turn_overlap_watch() -> Iterator[TurnOverlapWatch]:
    """Collect the admitted turns that overlap the ``with`` body. Never raises."""

    watch = TurnOverlapWatch()
    with _LOCK:
        watch._entries.update(_ENTRIES)
        _WATCHES.append(watch)
    try:
        yield watch
    finally:
        with _LOCK:
            try:
                _WATCHES.remove(watch)
            except ValueError:  # pragma: no cover - only this function removes
                pass


@contextmanager
def admitted_turn(turn_id=None):
    """Hold the admitted count for the life of one turn.

    Entered at the handler anchor — the same statement that constructs the
    turn's :class:`~agent_runtime.mission_chat_phases.TurnPhaseMarks`, so the
    counted window and the measured window are the same window by construction
    rather than by two call sites agreeing.

    ``turn_id`` names the turn to every :func:`turn_overlap_watch` open during
    it: a string, or a zero-argument callable read when a receipt is rendered.

    Released in a ``finally``: the mission-chat handler has fourteen terminal
    transitions in its commit phase and a dozen refusals above them, and a count
    that leaked on any one of them would — once Stage 7 reads it — wedge the
    snapshot demote lane for the life of the process.
    """

    global _ADMITTED
    token = next(_ENTRY_TOKENS)
    accepted = _CURRENT_ACCEPT.get()
    anchored = time.monotonic()
    with _LOCK:
        _ADMITTED += 1
        _ENTRIES[token] = turn_id
        for watch in _WATCHES:
            watch._entries[token] = turn_id
        # The hand-over: admitted is counted before accepted is released, under
        # one lock, so a reader never sees the turn in neither count.
        if accepted is not None:
            accepted._release_locked()
    if accepted is not None:
        _CURRENT_ACCEPT.set(None)
        _logger.info(ACCEPT_TO_ANCHOR_RECEIPT, *accepted.receipt_args(anchored), _turn_name(turn_id))
    in_turn = _IN_TURN.set(True)
    window = HotWindow()
    window.open()
    window_token = _HOT_WINDOW.set(window)
    try:
        yield window
    finally:
        _HOT_WINDOW.reset(window_token)
        window.close()
        _IN_TURN.reset(in_turn)
        with _LOCK:
            _ADMITTED -= 1
            _ENTRIES.pop(token, None)


__all__ = [
    "ACCEPT_TO_ANCHOR_RECEIPT",
    "AcceptedTurn",
    "HotWindow",
    "accepted_turn_scope",
    "admitted_turn",
    "chat_turns_accepted",
    "chat_turns_admitted",
    "current_hot_window",
    "hot_turn_windows",
    "inside_admitted_turn",
    "TurnOverlapWatch",
    "turn_overlap_watch",
]
