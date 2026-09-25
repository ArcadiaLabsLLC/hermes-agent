"""The process-level cache lane: armed until this process completes its own
build, the per-boot consult memo, and every function that rebinds that state
(``take_stale_first_core`` and ``claim_shadow_slot`` live here for that reason:
a ``global`` rebinding has exactly one module).
"""

from __future__ import annotations

import json
import threading
from typing import Any

from agent_runtime.parity import events_position

from agent_runtime.core_cache.vocabulary import (
    CORE_FILENAME,
    CORE_SOURCE_CACHE,
    DEMOTE_ABSENT,
    SIDECAR_FILENAME,
    logger,
)
from agent_runtime.core_cache.models import (
    CacheRead,
    CoreFingerprint,
    FingerprintEntry,
    _ConsultMemo,
    _ConsultStamp,
)
from agent_runtime.core_cache.walk import _stat_entry
from agent_runtime.core_cache.home import reset_fingerprint_home
from agent_runtime.core_cache.fingerprint import build_input_fingerprint
from agent_runtime.core_cache.generations import _live_generation_dir, pointer_path
from agent_runtime.core_cache.convergence import _reset_convergence_state
from agent_runtime.core_cache.read import _judge_persisted_pair, _read_pair, label_core

__layer__ = "lanes"

__all__ = [
    "REFUSAL_CORE_BEHIND_FRAME",
    "_LANE",
    "_armed_window_read",
    "_consult_memo",
    "_consult_stamp",
    "_drop_consult_memo",
    "_lane_armed",
    "_lane_lock",
    "_memo_lock",
    "_pair_stamp",
    "_shadow_done",
    "_stamp_still_stands",
    "_store_position",
    "claim_shadow_slot",
    "close_cache_lane",
    "lane_armed",
    "note_full_build_completed",
    "pre_build_fingerprint",
    "reset_process_state",
    "shadow_build_scope",
    "take_stale_first_core",
]


# --------------------------------------------------------------------------- #
# The process-level lane
# --------------------------------------------------------------------------- #
#: The cache lane is ARMED until this process has completed a full default-store
#: build of its own. That is the honest generalization of the plan's "first build
#: of a process": a serve boot issues several builds (prewarm, hydrate, status
#: polls) within seconds of each other, and gating on the literal first
#: CONSULTATION would have served the prewarm from the cache and then made the
#: hydrate — the one the launcher is actually waiting on — pay the full build
#: anyway, buying nothing the operator can see.
#:
#: An armed lane is never a stale-serve window: it is "this process has not yet
#: built its own truth, and the store says the persisted one is still current".
#: The fingerprint behind that answer is computed ONCE per armed window rather
#: than once per asker — see :data:`_consult_memo` for the window, its
#: invalidation, and what the sharing does and does not widen.
#:
#: Disarming on the first completed build also means no test can accidentally be
#: served from a cache: a fresh isolated root has no persisted core, so the
#: first consult always demotes, and the build that follows it disarms the lane.
_LANE = threading.local()


_lane_lock = threading.Lock()


_lane_armed = True


_shadow_done = False


_memo_lock = threading.Lock()


_consult_memo: _ConsultMemo | None = None


def _pair_stamp() -> tuple[FingerprintEntry, ...]:
    """The pointer and the pair it names — half of the memo's invalidation rule.

    The POINTER is in the stamp, and it is the load-bearing third stat. A
    generation flip is already visible in the other two — a
    :class:`FingerprintEntry` carries its path and the generation name is in it —
    but that leaves the memo's invalidation depending on a naming convention. The
    pointer's own mtime moves on every publish by the same ``os.replace`` argument
    the whole module rests on, so the memo drops on a republish whatever the
    generations are called.

    The OTHER half is :func:`_store_position`; the two are taken together by
    :func:`_consult_stamp`, which is what every memo comparison uses.
    """

    generation = _live_generation_dir()
    return (
        _stat_entry(pointer_path()),
        _stat_entry(generation / SIDECAR_FILENAME),
        _stat_entry(generation / CORE_FILENAME),
    )


def _store_position() -> int | None:
    """The event log's LOGICAL tail — the store's own position, right now.

    =========================================================================
    THIS IS NOT AN EVENT-OFFSET CACHE KEY (read the module header first)
    =========================================================================

    The header's standing rule is absolute and unchanged: **the fingerprint
    decides validity, full stop** — ``event_offset`` is never an input to the
    MATCH decision, there is no event-tail replay, and there must never be a
    second validity authority beside the walk. Nothing here decides that a
    persisted pair matches or does not.

    What this decides is narrower by one whole layer: whether a judgement
    computed for an EARLIER ask may be reused to answer THIS one without looking
    again. That is a memoisation question, not a validity question, and the two
    have opposite failure directions — a dropped memo costs a walk (~300–355 ms
    measured, and only on a boot whose store is moving under it), while a memo
    kept too long serves an answer about a store that has since changed. The
    fingerprint walk still runs and still decides; this only stops the memo from
    speaking for a walk that was never taken.

    **Why the store's position and not the pair's stat.** The pair's stat can
    only see the cache writing itself back. It is blind by construction to the
    thing the cache is a projection OF, so a memo keyed on it alone answers
    ``matched=True`` for as long as nobody republishes — measured 2026-08-21: a
    cache-hit boot filled the memo at 15:24 with a 14:56 core, an agent was
    created at 15:33, and the memo answered "current" four more times because
    the pair had not moved. Appends move the log; the log is in the stamp; the
    memo drops.

    **Cost, stated precisely because the audit bounded it at "one stat per
    ask".** ``event_rotation.log_end_offset`` reads no EVENT bytes and scans no
    log: on a pristine store it is one ``exists`` probe of the absent rotation
    manifest plus one ``stat`` of the live slice. On a ROTATED store it also
    reads and parses the manifest — a few KB of JSON listing the sealed slices,
    not the log — so the honest bound is "two stats, plus a small JSON read once
    the store has rotated", per ask, on a path that already pays three stats and
    (on a miss) a full store walk.

    ``None`` is the typed unknown, exactly as ``parity.events_watermark``
    defines it, and :func:`_stamp_still_stands` refuses to answer from a memo on
    either side of one: a position that could not be read cannot vouch that the
    store stood still. That is the same direction the whole module takes — a
    missing answer is "never cache", never "nothing changed".
    """

    return events_position().get("event_offset")


def _consult_stamp() -> _ConsultStamp:
    """Both halves, taken together — the only stamp a memo is ever compared on."""

    return _ConsultStamp(_pair_stamp(), _store_position())


def _stamp_still_stands(memo_stamp: _ConsultStamp, now_stamp: _ConsultStamp) -> bool:
    """May a memo taken at ``memo_stamp`` answer an ask at ``now_stamp``?

    Equality of both halves is required. The store half additionally refuses an
    UNKNOWN position on either side rather than letting two unknowns compare
    equal: ``None == None`` would read as "the log did not move" when what it
    actually says is "nobody could tell", which is the fail-quiet default
    ``events_watermark``'s own docstring exists to forbid. An install whose log
    cannot be stat'd re-walks per ask — the expensive direction, deliberately.
    """

    if memo_stamp.event_offset is None or now_stamp.event_offset is None:
        return False
    return memo_stamp == now_stamp


def _drop_consult_memo() -> None:
    global _consult_memo
    with _memo_lock:
        _consult_memo = None


def _armed_window_read() -> CacheRead:
    """The boot lane's shared judgement: computed once, answered many times.

    Every caller gets its OWN decoded core, re-parsed from the memoised bytes.
    The build coalescer already deep-copies its result for exactly this reason:
    :func:`label_core` stamps provenance IN PLACE, so one shared dict would let
    the third rider's label land on the first rider's already-emitted frame.

    The stamp is taken OUTSIDE the memo lock and both halves come from
    :func:`_consult_stamp`, so an append that lands between the boot's stale-read
    and its riders' consults drops the memo and the next asker walks the store
    again. It re-CONSULTS; it does not force a rebuild. The walk it pays for is
    the content check, and if the fingerprint still matches the answer is still a
    cache hit — the append simply no longer gets to be answered by a judgement
    taken before it.
    """

    global _consult_memo
    stamp = _consult_stamp()
    with _memo_lock:
        memo = _consult_memo
        if memo is not None and _stamp_still_stands(memo.stamp, stamp):
            return memo.read._replace(core=json.loads(memo.raw_core))
        pair = _read_pair()
        if pair is None:
            _consult_memo = None
            return CacheRead(None, False, DEMOTE_ABSENT, None, {})
        read = _judge_persisted_pair(pair[0], pair[1], fingerprint=None)
        # A judgement that produced no core has nothing to re-parse and nothing
        # worth holding: the pair is unreadable or unbound, and the next asker
        # should see that for itself rather than inherit a refusal.
        _consult_memo = (
            _ConsultMemo(stamp, pair[1], read) if read.core is not None else None
        )
        return read


def pre_build_fingerprint() -> CoreFingerprint | None:
    """The key a build persists — the consult's, when the consult still stands.

    The leader used to take a SECOND full walk here, milliseconds after its own
    consult had taken one over the same store. Reusing the consult's key keeps
    the direction ``write_back`` requires: a key stat'd BEFORE the build is at
    worst OLDER than the core it describes, which can only cost the next process
    a rebuild it did not strictly need. The unsafe direction — a key stat'd after
    the build, absorbing a write the core does not contain — is not reachable
    from here, because the memo is filled before the build starts and dropped
    when it completes.

    Falls through to a full walk whenever there is no standing consult: a cold
    store (nothing to consult), a disarmed lane (every later build in the
    process), a pair that moved since, or a STORE that moved since. The last one
    is new with R1 and costs this caller a walk it used to skip — which is the
    direction this function's own rule already demanded: a key that predates the
    build is safe, and a key inherited from a judgement taken before an append
    would describe a store the build is no longer reading.
    """

    with _memo_lock:
        memo = _consult_memo
    if (
        memo is not None
        and memo.read.fingerprint is not None
        and _stamp_still_stands(memo.stamp, _consult_stamp())
    ):
        return memo.read.fingerprint
    return build_input_fingerprint()


def reset_process_state() -> None:
    """Re-arm the lane, as a fresh process would. Tests only.

    Same shape and same reason as ``build_stamp.reset_build_stamp_cache``: a
    property of the PROCESS has to be resettable for a test to be able to
    exercise a second process's behaviour without spawning one.

    The convergence history (ML-10) is process state by the same definition and
    is reset here too — a case that left a streak behind would hand the next case
    a process that had already half-declared non-convergence. So is the boot
    lane's shared consult: a memo surviving into the next case would answer it
    with the previous case's store. So is the captured fingerprint home (MC-2):
    a capture surviving into the next case would resolve its closure through the
    previous case's home, which the sandbox has already deleted.
    """

    global _lane_armed, _shadow_done
    with _lane_lock:
        _lane_armed = True
        _shadow_done = False
    _reset_convergence_state()
    _drop_consult_memo()
    reset_fingerprint_home()


def lane_armed() -> bool:
    with _lane_lock:
        return _lane_armed


def note_full_build_completed() -> None:
    """The process now owns its own truth — the cache lane closes.

    A no-op inside a shadow build: that build is a VALIDATION of the cache, not
    the process's answer, and letting it disarm the lane would make the next
    boot caller pay a full build for the privilege of having validated the one
    it just avoided.

    The armed window's shared consult ends here with the lane. Dropped OUTSIDE
    the lane lock on purpose: the memo lock is taken while judging, and judging
    never takes the lane lock, so the two locks must never nest in the other
    order either.
    """

    if getattr(_LANE, "shadow", False):
        return
    global _lane_armed
    with _lane_lock:
        _lane_armed = False
    _drop_consult_memo()


#: The one reason :func:`close_cache_lane` is called with today: a core this
#: lane served reaches an offset EARLIER than the one a frame was about to stamp
#: it with. Its own constant so the channel table can name it and a census can
#: count it, rather than a sentence assembled at the call site.
REFUSAL_CORE_BEHIND_FRAME = "core_behind_frame"


def close_cache_lane(*, reason: str, caller: str, detail: str = "") -> None:
    """Stop serving the persisted core in this process, with a reason on the log.

    :func:`note_full_build_completed` says "this process now owns its own truth".
    This says something different and rarer: **a core this lane served has been
    shown to be unusable by the consumer that asked for it**, so the lane stops,
    whatever the fingerprint thinks. It exists for exactly one caller — the
    stream's full-core batch lane, which is the one place that holds a core AND
    the offset that core is about to be stamped with, and can therefore see a
    content-vs-position violation the cache cannot see from the inside.

    Not a second validity authority (the module header's standing rule): nothing
    here decides that a persisted pair MATCHES. It can only refuse, and only
    after a core has already been served and found wanting.

    Idempotent, and the receipt is emitted whether or not the lane was still
    armed — "we asked for this to stop" is the fact worth reading, and gating the
    line on the lane's state would make the second of two racing frames silent.

    ``reason`` is a TYPED token, and ``detail`` carries the numbers behind it, so
    the line is countable by family+reason exactly like every other receipt on
    this logger (C22). Free text in the reason field would put a fourth
    vocabulary on one logger, which is the defect the channel table exists to
    have retired.
    """

    logger.warning(
        "snapshot_core_cache_lane_closed caller=%s reason=%s %s — a served core "
        "could not answer for the offset it was about to be stamped with; this "
        "process will rebuild from here.",
        caller,
        reason,
        detail or "-",
    )
    global _lane_armed
    with _lane_lock:
        _lane_armed = False
    _drop_consult_memo()


class shadow_build_scope:
    """Marks the calling thread's build as the shadow validation build."""

    def __enter__(self) -> None:
        _LANE.shadow = True

    def __exit__(self, *exc: Any) -> None:
        _LANE.shadow = False


def take_stale_first_core(*, caller: str) -> dict | None:
    """A persisted core to paint IMMEDIATELY, LABELED stale — or ``None``.

    The mismatch half of the design: rather than showing the operator nothing
    for the length of a full build, serve what the store last projected and say
    out loud that it is not validated. The replacement arrives on the next frame
    when the build completes.

    **The one-shot is the SUBSCRIBER's, not the process's (MC-4 / P6).** It used
    to be a module-global ``_stale_served``, and that made the stale paint a race
    rather than a delivery: a boot starts TWO ``stream_frames`` generators — the
    hub producer, which the office ``runtime.office.subscribe`` attaches 0.1–0.2s
    before the launcher asks for anything, and the launcher's own argv stream —
    and whichever reached this function first consumed the process's single
    allowance. Measured 2026-08-18: it went to ``caller=hub`` on two of three
    boots, where ``serve_office_subscriptions.office_patch_sink`` discards every
    row that is not an ``office_actor`` — i.e. the one stale paint the design
    exists to deliver was thrown away, and the operator watched an empty canvas
    for the length of a full build. The rule is now stated where the room is
    known (``stream_frames``' ``wants_stale_first``, derived at producer-build
    time by ``serve/subscriptions.py::_room_wants_stale_first``), and the one-shot is
    structural: :func:`agent_runtime.stream.stream_frames` asks this ONCE, at its
    head, before its tail loop.

    **What still bounds it, and why that bound is the sound one.** Only while the
    lane is armed. The lane disarms at :func:`note_full_build_completed`, so the
    window is the BOOT — the span in which this process has not yet built its own
    truth — not the session. A resubscribe long after that can never re-paint an
    old projection, which is the property the process-global flag was reaching
    for and got by over-tightening: it also refused the SECOND generator of a
    boot, which is the one the launcher is usually on.
    """

    with _lane_lock:
        if not _lane_armed:
            return None
    # The same shared judgement the riders will get. This read is FIRST in the
    # boot, so on the ordinary shape it is the one that pays for the walk and
    # every consult behind it is answered for free.
    read = _armed_window_read()
    if read.core is None or read.matched:
        # Nothing to paint, or the core MATCHES — in which case the ordinary
        # cache-hit path above will serve it authoritative and painting a stale
        # copy first would be a lie in the pessimistic direction.
        return None
    logger.info(
        "snapshot_core_cache core_source=%s stale=true caller=%s reason=%s",
        CORE_SOURCE_CACHE,
        caller,
        read.reason,
    )
    return label_core(read.core, source=CORE_SOURCE_CACHE, stale=True)


def claim_shadow_slot() -> bool:
    """Take the process's ONE shadow-validation slot, or report it taken.

    Once, not per cache hit: a boot issues several builds and spawning a full
    build behind each of them would cost the process more than the cache saved —
    four boot hits would buy four rebuilds.

    Separated from the thread start so the claim is testable as a claim. A gate
    whose only witness has to observe a background thread is a gate tested
    through a race.
    """

    global _shadow_done
    with _lane_lock:
        if _shadow_done:
            return False
        _shadow_done = True
    return True
