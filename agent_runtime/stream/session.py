"""``stream_frames`` — the session that owns a tail: the stale-first paint, the
boot build, the tail loop (:class:`StreamSession`)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from ..core_cache import lane as cache_lane
from ..events import EventLog
from ..models import Event
from ..parity import events_watermark
from ..patch_coverage import normalize_fold_entities
from ..request_control import request_cancelled
from ..state_patches.emit import delta_patches_enabled

from .build import _SnapshotBuildJob, _batch_frames_with_liveness, _bounded_sleep, _build_with_liveness, _is_one_shot
from .build_policy import _log_snapshot_build
from .fingerprint import _scope_fingerprint
from .frames import _append_state_reconciled, _resume_offset, heartbeat_frame, hydrate_frame
from .vocabulary import DEFAULT_STREAM_CALLER, FRAME_HEARTBEAT, _DELTA_BATCH_CAP

__layer__ = "lanes"


def stream_frames(
    *,
    event_log: EventLog | None = None,
    poll_interval_seconds: float = 0.25,
    heartbeat_interval_seconds: float = 5.0,
    delta_debounce_seconds: float = 0.2,
    max_frames: int | None = None,
    resync: bool = False,
    fold_entities: Iterable[str] | None = None,
    promote_fold_entities: Iterable[str] | None = None,
    fold_room: Callable[[], tuple[Any, Any]] | None = None,
    caller: str = DEFAULT_STREAM_CALLER,
    wants_stale_first: bool = False,
) -> Iterator[dict[str, Any]]:
    """Yield hydrate, delta/patch, and heartbeat frames for ``hermes harness stream``.

    Freshness backstop (Stage 12): every store mutation is supposed to append
    an EventLog event (enforced by test_store_event_invariant), but a write
    that slips the rule would freeze watermark-gated consumers FOREVER — they
    drop same-offset re-hydrates, so only an offset advance converges them.
    At heartbeat cadence this loop fingerprints the scope/catalog state that
    isn't guarded by evented stores at runtime; if the fingerprint changed
    while the offset did not, it appends a synthetic ``state.reconciled``
    event, which flows out as an ordinary full-core delta. Declared SLO:
    client staleness ≤ 2× heartbeat interval for ANY write. Every
    ``state.reconciled`` in the log names a producer bug to fix at source.

    S6: when ``read_model.delta_patches`` is on, a fully-coverable batch ships
    as a sub-4KB v2 ``patch`` frame instead of a full-core delta; uncovered
    batches keep the full-core lane. Each
    batch carries the ``base_offset`` it applies from so the launcher's fold can
    detect a gap. ``resync=True`` forces the FIRST post-hydrate batch to a full
    core — the "explicit resync request" a reconnecting client makes to re-baseline
    before folding. Flag off → every batch is the byte-identical full-core frame.

    ``fold_entities`` is the CLIENT's declaration of which entity classes it can
    fold in place; a batch naming any other entity is demoted to the full core
    (see :mod:`agent_runtime.patch_coverage`). ``None`` — nothing declared, which
    is what every client in the field sends today — resolves to the historical
    ``{persona_instance, incident}``, so an un-updated launcher gets exactly the
    wire it gets now. Resolved ONCE, here: what "absent" means must not be
    re-decided per batch on a hot path, and the hydrate must echo the same answer
    the promotion decision uses.

    ``promote_fold_entities`` is what SOME subscriber can fold when the room
    disagrees — the UNION where ``fold_entities`` is the intersection. It exists
    for one caller, the serve hub, whose fan-out can hand each subscriber a
    different half of a :func:`fold_variants_frame` envelope; every other caller
    leaves it ``None``, which collapses it onto ``fold_entities`` and makes the
    split branch in ``_batch_frames_with_liveness`` unreachable. The hydrate
    keeps echoing ``fold_entities`` — the ROOM'S FLOOR — because one hydrate is
    fanned to N subscribers and the floor is the only value true for every
    recipient; a subscriber may then be handed patches ABOVE that floor, which
    it can fold by definition (the fan-out only routes a patch to a declaration
    that covers it), so the echo is a guarantee and never a ceiling. With one
    subscriber the floor IS its own declaration and the echoed bytes do not
    move.

    **An unknown resume position is not byte 0.** ``or 0`` folded BOTH a missing
    watermark key and an explicitly unknown one (``events_watermark`` returns
    ``None`` when the log's end offset could not be stat'ed) into 0, and then
    tailed from there — replaying the entire event log as fresh activity at the
    root of every Mission Control surface. Unknown now takes the resync lane
    this function already has: the first batch ships as a full core, and the
    tailer waits to learn a real tail instead of inventing one.

    ``caller`` is who this generator produces for — ``hub`` for the serve hub's
    shared producer, ``cli`` for ``hermes harness stream``. It reaches
    ``build_snapshot``'s ``build_info`` and lands on every build/wait line this
    generator emits, so a boot's log says WHICH attachment paid for a build
    instead of leaving the census to be reconstructed from timestamps.

    ``wants_stale_first`` is whether anyone this generator feeds will PAINT the
    boot's one stale-labelled core (EG-3.1's mismatch half, MC-4 / P6). It is a
    property of the ROOM, which is why it is stated by the caller and cannot be
    re-derived here: the serve hub is one producer for N subscribers, and the
    subscriber that attaches FIRST at boot is the RPC office lane, whose
    ``office_patch_sink`` discards every row that is not an ``office_actor``.
    Measured 2026-08-18: two boots in three handed the stale paint to that sink
    and the launcher watched an empty canvas for the length of a full build.
    ``serve/subscriptions.py::_room_wants_stale_first`` derives the hub's answer from its two
    subscriber tables at producer-build time; ``_cmd_stream`` states ``True``
    because the argv lane exists to feed a painting consumer. The default is
    ``False`` — the SAFE direction, and deliberately so: a caller that has not
    said it paints gets exactly the pre-EG-3.1 wire (one authoritative hydrate),
    whereas a ``True`` default would let a third, non-painting caller silently
    eat the boot's single stale core again. ``test_stream_stale_first_routing``
    pins by AST that both production call sites state it rather than inheriting
    it.
    """

    yield from StreamSession(
        event_log=event_log,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        delta_debounce_seconds=delta_debounce_seconds,
        max_frames=max_frames,
        resync=resync,
        fold_entities=fold_entities,
        promote_fold_entities=promote_fold_entities,
        fold_room=fold_room,
        caller=caller,
        wants_stale_first=wants_stale_first,
    ).frames()


#: A pass's verdict to the tail loop: stop the generator, or run the next pass
#: at once (skipping the poll sleep). ``None`` is the ordinary end of a pass.
_STOP = object()
_AGAIN = object()


class StreamSession:
    """One ``stream_frames`` request: the room it folds for and the tail it owns.

    Phases, in order — :meth:`stale_first` → :meth:`boot` → :meth:`tail`, whose
    loop runs :meth:`_pass` = :meth:`measure` (only while the position is
    unknown) → the fingerprint → :meth:`room` → :meth:`drain` → :meth:`settle` →
    :meth:`flush` → :meth:`beat`. Every phase that yields is a generator whose
    RETURN value says whether the frame budget is spent (``_STOP``) or the next
    pass must start now (``_AGAIN``); :meth:`emit` is the one place a frame is
    counted. The parameters are ``stream_frames``' own; its docstring is the
    contract.
    """

    def __init__(
        self,
        *,
        event_log: EventLog | None,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        delta_debounce_seconds: float,
        max_frames: int | None,
        resync: bool,
        fold_entities: Iterable[str] | None,
        promote_fold_entities: Iterable[str] | None,
        fold_room: Callable[[], tuple[Any, Any]] | None,
        caller: str,
        wants_stale_first: bool,
    ) -> None:
        self.log = event_log or EventLog()
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.delta_debounce_seconds = delta_debounce_seconds
        self.max_frames = max_frames
        self.fold_room = fold_room
        self.caller = caller
        self.wants_stale_first = wants_stale_first
        self.delta_patches = delta_patches_enabled()
        self.declared_entities = normalize_fold_entities(fold_entities)
        # Resolved ONCE beside the floor and for the same reason. ``None`` collapses
        # to the floor, so every caller but the hub produces exactly the frames it
        # produced before this parameter existed.
        self.promote_entities = (
            self.declared_entities
            if promote_fold_entities is None
            else normalize_fold_entities(promote_fold_entities)
        )
        self.resync_pending = bool(resync)
        self.emitted = 0
        self.offset: int | None = None
        self.known_fingerprint = ""
        self.last_heartbeat = 0.0
        # One drain pass's state, reset at the top of every pass.
        self.pending: list[tuple[int, Event]] = []
        self.batch_base: int | None = None
        self.batch_floor = self.declared_entities
        self.batch_promote = self.promote_entities
        self.emitted_delta = False

    def frames(self) -> Iterator[dict[str, Any]]:
        if (yield from self.stale_first()):
            return
        if (yield from self.boot()):
            return
        yield from self.tail()

    def emit(self, frame: dict[str, Any], *, beat: bool = True):
        """Yield one frame, count it, and answer whether the budget is now spent.

        ``beat=False`` for the boot's frames: the heartbeat clock starts at the
        tail, after the authoritative hydrate.
        """

        yield frame
        self.emitted += 1
        if beat:
            self.last_heartbeat = time.monotonic()
        return self.max_frames is not None and self.emitted >= self.max_frames

    def heartbeat_due(self) -> bool:
        return time.monotonic() - self.last_heartbeat >= self.heartbeat_interval_seconds

    def room(self) -> tuple[frozenset[str], frozenset[str]]:
        """The (floor, union) this drain pass promotes against.

        ``fold_room`` is the serve hub's live reading of its two subscriber
        tables; everyone else gets the pair resolved once above, which is
        exactly the behaviour that existed before either parameter did.

        **Why the hub reads it per pass rather than once per producer.** A
        restart-free join — the office lane's, and now a watermark resume's —
        adds a subscriber the running producer never counted. If the floor is
        frozen at build time, a batch inside the OLD floor still ships as a BARE
        patch, and a joiner that folds less than that floor is handed a frame it
        answers with a re-hydrate: the promotion regression the negotiation
        exists to prevent, arriving through the door built to avoid a restart.
        Re-read, the very next pass sees the narrowed floor and splits instead.
        The cost is two small set derivations per DRAIN PASS, not per event and
        not per frame.

        It also makes a LEAVE re-widen for free, which the old comment on
        ``serve/subscriptions.py::_accepted_fold_entities`` had to decline because re-widening
        meant restarting the producer and charging every remaining subscriber a
        fresh core.

        The hydrate's echo is deliberately NOT re-read: it is resolved once,
        above, so the frame a client re-baselines on and the answer it was given
        on its ack cannot disagree about a set that moved between them.
        """

        if self.fold_room is None:
            return self.declared_entities, self.promote_entities
        try:
            floor, union = self.fold_room()
        except Exception:
            # A room that cannot be read is answered with the pair this
            # generator was BUILT with — the conservative direction, and the
            # same one every other ambiguity in this module takes.
            return self.declared_entities, self.promote_entities
        return normalize_fold_entities(floor), normalize_fold_entities(union)

    def stale_first(self):
        # EG-3.1's mismatch half. A persisted core whose fingerprint does NOT match
        # is not authority — but it is also not nothing, and the alternative is
        # showing the operator an empty canvas for the length of a full build. So it
        # goes out FIRST, wearing the stale label
        # (``parity.freshness.state = "stale"``, the field the launcher's envelope
        # already maps to ``MissionSnapshotHealth.stale``), and the authoritative
        # hydrate below replaces it when the build completes.
        #
        # It is an ordinary ``hydrate`` frame, not a new type: the hydrate's own
        # contract is "apply this exactly like a fresh snapshot", so a second one
        # re-baselines a client with no new wire vocabulary. The stale frame's
        # watermark is deliberately NOT used to seed ``offset`` — the tail is
        # resumed from the AUTHORITATIVE frame below, so nothing between the two is
        # skipped.
        #
        # TWO conditions, and they are different questions. ``wants_stale_first``
        # asks whether anybody in this generator's room paints (see the parameter).
        # ``_is_one_shot`` asks whether this request has room for a second frame at
        # all: the stale frame is yielded at the HEAD and the budget check below
        # returns immediately after it, so a one-shot that took the stale core would
        # answer with a core that is by definition NOT authoritative — and the
        # launcher's forced-refresh lane
        # (``mission_control_bridge.dart::_loadSnapshotFromStreamHydrate``, read
        # 2026-08-18) scans that stdout for a ``type == "hydrate"`` line and applies
        # whatever it finds through ``applyForcedSnapshot``, i.e. PAST its own
        # sequence gate. Refusing here is what keeps "force a refresh" from meaning
        # "re-paint the projection you were already unhappy with".
        stale_core = (
            cache_lane.take_stale_first_core(caller=self.caller)
            if self.wants_stale_first and not _is_one_shot(self.max_frames)
            else None
        )
        if stale_core is None:
            return False
        return (
            yield from self.emit(
                hydrate_frame(
                    snapshot=stale_core,
                    delta_patches=self.delta_patches,
                    fold_entities=self.declared_entities,
                    caller=self.caller,
                ),
                beat=False,
            )
        )

    def boot(self):
        # The boot's authoritative core, built with the stream SAYING SO while it
        # runs (MC-4 / P6, evidence A-x2). This used to be a bare synchronous
        # ``hydrate_frame()``: on 2026-08-18 that build took 29,560 ms and the lane
        # emitted nothing for the whole of it, so the launcher's watchdog fired
        # ``stream_teardown cause=liveness_deadline`` 0.67 s before the frame
        # arrived, and the finished core was delivered to a retired request and
        # discarded with no receipt. A batch build has heartbeat through its build
        # since ``_full_core_batch_frames`` shipped; the BOOT build — the longest one
        # any consumer ever waits on — was the one lane that stayed silent.
        #
        # ``accept_inflight=True`` is carried deliberately and is the whole reason
        # the job grew the flag: ``hydrate_frame``'s own build sets it (the serve
        # prewarms a build right after ``ready``, and this frame is allowed to ride
        # it because its watermark comes from the snapshot itself and the tail below
        # resumes from exactly that offset). A job without it would make every boot
        # wait for the prewarm and THEN pay a second full build.
        boot_job = _SnapshotBuildJob(caller=self.caller, accept_inflight=True)
        for liveness in _build_with_liveness(
            boot_job,
            # No applied core exists yet, so there is no position to advertise. See
            # ``heartbeat_frame``: liveness without a position must not be stamped 0.
            heartbeat_offset=None,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            # A one-shot is answered with a CORE or with nothing — see
            # ``_is_one_shot``. Suppressed rather than merely uncounted so the
            # frames a one-shot consumer sees stay exactly what it asked for.
            emit_liveness=not _is_one_shot(self.max_frames),
        ):
            # NOT counted toward ``emitted``, and this is the deliberate half of the
            # ``max_frames`` decision. These frames are emitted while the FIRST
            # content frame is still being built, so counting them would let a
            # budget be spent before any core existed — a ``--max-frames 1`` request
            # returning a heartbeat and no core. That is not hypothetical for the
            # consumer: the launcher's forced-refresh lane
            # (``mission_control_bridge.dart::_loadSnapshotFromStreamHydrate``, read
            # 2026-08-18) scans stdout for a ``type == "hydrate"`` line and silently
            # returns null when it finds none, so the refresh would no-op with no
            # receipt. The budget counts CONTENT; the tail loop's own heartbeats
            # below still count, because by then a core has been delivered and the
            # consumer is being kept alive rather than kept waiting.
            yield liveness
        if request_cancelled():
            return True
        return (yield from self.boot_hydrate(boot_job))

    def boot_hydrate(self, boot_job: _SnapshotBuildJob):
        """The boot build's result as the authoritative hydrate, and its receipt."""

        if boot_job.error is not None:
            raise boot_job.error
        if boot_job.snapshot is None:
            raise RuntimeError("snapshot build completed without a result")
        hydrate = hydrate_frame(
            snapshot=boot_job.snapshot,
            delta_patches=self.delta_patches,
            fold_entities=self.declared_entities,
            caller=self.caller,
        )
        if boot_job.elapsed_ms is not None:
            # The receipt ``hydrate_frame`` would have billed itself, billed here
            # because the build moved out from under it. Byte-shaped identically —
            # same reason, same fields, same order — and ``waited_ms`` comes from the
            # job's own measurement, taken ON the build thread: measuring around the
            # wait here would round every build up by as much as one
            # ``_SNAPSHOT_CANCEL_POLL_SECONDS``, which is the exact reason
            # ``_SnapshotBuildJob.elapsed_ms`` exists.
            _log_snapshot_build(
                reason="hydrate",
                waited_ms=boot_job.elapsed_ms,
                offset=(hydrate.get("watermark") or {}).get("event_offset"),
                snapshot=boot_job.snapshot,
                build_info=boot_job.build_info,
            )
        self.offset = _resume_offset(hydrate)
        if self.offset is None:
            # Cannot resume from an unknown position. Re-baseline the client on the
            # first batch and re-measure the tail below until the log is readable.
            self.resync_pending = True
        # Memoize BEFORE the first yield: a generator body pauses at yield, so a
        # memo taken after it would absorb any write racing the consumer's first
        # pull — exactly the writes the watchdog exists to catch.
        self.known_fingerprint = _scope_fingerprint()
        return (yield from self.emit(hydrate, beat=False))

    def tail(self):
        self.last_heartbeat = time.monotonic()
        while True:
            if request_cancelled():
                return
            outcome = yield from self._pass()
            if outcome is _STOP:
                return
            if outcome is _AGAIN:
                continue
            # Cancellation latency is bounded even when a caller chooses a long
            # poll interval; the production default remains 250ms.
            _bounded_sleep(self.poll_interval_seconds)

    def _pass(self):
        if self.offset is None:
            outcome = yield from self.measure()
            if outcome is not None:
                return outcome
        # Fingerprint BEFORE reading events. A delta batch rebuilds one full
        # snapshot per BATCH (W1 coalescing — it was per event, ~9MB a time);
        # a memo taken AFTER the batch would absorb any event-less write that
        # raced the batch — swallowing forever the exact violations the
        # watchdog exists to catch (found by live proof). Taken before the
        # read, a racing write always lands in a LATER iteration's candidate
        # and reconciles at the next heartbeat.
        fingerprint_candidate = _scope_fingerprint()
        # The room, re-read once per drain pass. See :meth:`room`: a restart-free
        # join is only safe when the producer can NOTICE it, and this is where it
        # does. Read beside the fingerprint and for a sibling reason — both are
        # facts about the world that must be taken before the events are, so a
        # change racing the drain lands in a later pass rather than being missed
        # by this one.
        self.batch_floor, self.batch_promote = self.room()
        self.emitted_delta = False
        self.pending = []
        # The offset a flushed batch applies FROM (S6 gap detection): the cursor
        # before the batch's first entry. Advanced to the flushed offset after
        # every emit so contiguous batches chain base→watermark→base with no gap.
        self.batch_base = self.offset
        if (yield from self.drain()) or (yield from self.settle()):
            return _STOP
        if self.pending and (yield from self.flush()):
            return _STOP
        if self.emitted_delta:
            # Evented mutations legitimately move the fingerprint; adopt the
            # pre-batch candidate so the watchdog only fires on offset-less
            # changes. (An evented write landing between the candidate and the
            # batch read can cause one spurious reconcile — harmless: it is
            # just an extra full-core delta.)
            self.known_fingerprint = fingerprint_candidate
        return (yield from self.beat(fingerprint_candidate))

    def measure(self):
        """The position is unknown: wait for a readable tail, then re-baseline."""

        if events_watermark().get("event_offset") is None:
            # Still no readable tail. Emit liveness (with an honestly null
            # position) and retry the measurement — never fall back to 0, which
            # would tail the whole log from its head as if it were new.
            if self.heartbeat_due() and (yield from self.emit(heartbeat_frame(offset=None))):
                return _STOP
            _bounded_sleep(self.poll_interval_seconds)
            return _AGAIN
        # The tail is readable again, but the client's baseline predates
        # whatever landed while it was not — and there is no cursor to
        # replay that span from. Re-baseline explicitly (the "explicit
        # resync" this lane exists for): a fresh full core, tailed from ITS
        # OWN measured offset, so the recovery leaves neither a gap nor a
        # replay. Resuming from the newly measured tail alone would silently
        # drop the span; resuming from 0 would re-render the whole log.
        rebaseline = hydrate_frame(
            delta_patches=self.delta_patches,
            fold_entities=self.declared_entities,
            caller=self.caller,
        )
        self.offset = _resume_offset(rebaseline)
        if self.offset is None:
            return _AGAIN
        self.resync_pending = True
        self.known_fingerprint = _scope_fingerprint()
        if (yield from self.emit(rebaseline)):
            return _STOP
        return None

    def drain(self):
        """Read the log from the cursor; a batch that reaches the cap flushes MID-pass."""

        for next_offset, event in self.log.iter_from_offset(self.offset):
            self.offset = int(next_offset)
            self.pending.append((self.offset, event))
            if len(self.pending) >= _DELTA_BATCH_CAP and (yield from self.flush()):
                return True
        return False

    def settle(self):
        """Settle window: an event burst usually lands over a few tens of
        milliseconds — one bounded sleep lets the tail join the SAME frame
        instead of costing a full core each. 200ms sits well inside the declared
        ≤2×heartbeat staleness SLO."""

        if not self.pending or self.delta_debounce_seconds <= 0:
            return False
        time.sleep(self.delta_debounce_seconds)
        return (yield from self.drain())

    def flush(self):
        """Ship the pending batch (with liveness while its core builds)."""

        for frame in _batch_frames_with_liveness(
            self.pending,
            base_offset=self.batch_base,
            delta_patches=self.delta_patches,
            resync=self.resync_pending,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            fold_entities=self.batch_floor,
            promote_fold_entities=self.batch_promote,
            caller=self.caller,
        ):
            spent = yield from self.emit(frame)
            if frame.get("type") != FRAME_HEARTBEAT:
                self.emitted_delta = True
            if spent:
                return True
        self.resync_pending = False
        self.batch_base = self.offset
        self.pending = []
        return False

    def beat(self, fingerprint_candidate: str):
        """No delta this pass and a heartbeat is due: reconcile a silent write, or beat."""

        if self.emitted_delta or not self.heartbeat_due():
            return None
        if fingerprint_candidate != self.known_fingerprint and _append_state_reconciled(
            self.log, fingerprint_candidate
        ):
            self.known_fingerprint = fingerprint_candidate
            # Skip the sleep: the next iteration reads the appended event
            # and emits the reconcile delta (which resets the heartbeat).
            return _AGAIN
        if (yield from self.emit(heartbeat_frame(offset=self.offset))):
            return _STOP
        return None
