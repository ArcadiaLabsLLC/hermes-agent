"""``stream_frames`` — the session that owns a tail: the stale-first paint, the
boot build, the tail loop — and the scope fingerprint the watchdog takes per
pass."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from .. import core_cache, paths
from ..events import EventLog
from ..models import Event
from ..parity import events_watermark
from ..patch_coverage import normalize_fold_entities
from ..request_control import request_cancelled
from ..state_patches.emit import delta_patches_enabled

from .build import _SnapshotBuildJob, _batch_frames_with_liveness, _bounded_sleep, _build_with_liveness, _is_one_shot
from .build_policy import _log_snapshot_build
from .frames import _append_state_reconciled, _resume_offset, heartbeat_frame, hydrate_frame
from .vocabulary import DEFAULT_STREAM_CALLER, _DELTA_BATCH_CAP

__layer__ = "wiring"


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

    log = event_log or EventLog()
    delta_patches = delta_patches_enabled()
    declared_entities = normalize_fold_entities(fold_entities)
    # Resolved ONCE beside the floor and for the same reason. ``None`` collapses
    # to the floor, so every caller but the hub produces exactly the frames it
    # produced before this parameter existed.
    promote_entities = (
        declared_entities
        if promote_fold_entities is None
        else normalize_fold_entities(promote_fold_entities)
    )

    def _room() -> tuple[frozenset[str], frozenset[str]]:
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

        if fold_room is None:
            return declared_entities, promote_entities
        try:
            floor, union = fold_room()
        except Exception:
            # A room that cannot be read is answered with the pair this
            # generator was BUILT with — the conservative direction, and the
            # same one every other ambiguity in this module takes.
            return declared_entities, promote_entities
        return normalize_fold_entities(floor), normalize_fold_entities(union)

    resync_pending = bool(resync)
    emitted = 0
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
        core_cache.take_stale_first_core(caller=caller)
        if wants_stale_first and not _is_one_shot(max_frames)
        else None
    )
    if stale_core is not None:
        yield hydrate_frame(
            snapshot=stale_core,
            delta_patches=delta_patches,
            fold_entities=declared_entities,
            caller=caller,
        )
        emitted += 1
        if max_frames is not None and emitted >= max_frames:
            return
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
    boot_job = _SnapshotBuildJob(caller=caller, accept_inflight=True)
    for liveness in _build_with_liveness(
        boot_job,
        # No applied core exists yet, so there is no position to advertise. See
        # ``heartbeat_frame``: liveness without a position must not be stamped 0.
        heartbeat_offset=None,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        # A one-shot is answered with a CORE or with nothing — see
        # ``_is_one_shot``. Suppressed rather than merely uncounted so the
        # frames a one-shot consumer sees stay exactly what it asked for.
        emit_liveness=not _is_one_shot(max_frames),
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
        return
    if boot_job.error is not None:
        raise boot_job.error
    if boot_job.snapshot is None:
        raise RuntimeError("snapshot build completed without a result")
    hydrate = hydrate_frame(
        snapshot=boot_job.snapshot,
        delta_patches=delta_patches,
        fold_entities=declared_entities,
        caller=caller,
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
    offset = _resume_offset(hydrate)
    if offset is None:
        # Cannot resume from an unknown position. Re-baseline the client on the
        # first batch and re-measure the tail below until the log is readable.
        resync_pending = True
    # Memoize BEFORE the first yield: a generator body pauses at yield, so a
    # memo taken after it would absorb any write racing the consumer's first
    # pull — exactly the writes the watchdog exists to catch.
    known_fingerprint = _scope_fingerprint()
    yield hydrate
    emitted += 1
    if max_frames is not None and emitted >= max_frames:
        return

    last_heartbeat = time.monotonic()
    while True:
        if request_cancelled():
            return
        if offset is None:
            # Still no readable tail. Emit liveness (with an honestly null
            # position) and retry the measurement — never fall back to 0, which
            # would tail the whole log from its head as if it were new.
            if events_watermark().get("event_offset") is None:
                if time.monotonic() - last_heartbeat >= heartbeat_interval_seconds:
                    yield heartbeat_frame(offset=None)
                    emitted += 1
                    last_heartbeat = time.monotonic()
                    if max_frames is not None and emitted >= max_frames:
                        return
                _bounded_sleep(poll_interval_seconds)
                continue
            # The tail is readable again, but the client's baseline predates
            # whatever landed while it was not — and there is no cursor to
            # replay that span from. Re-baseline explicitly (the "explicit
            # resync" this lane exists for): a fresh full core, tailed from ITS
            # OWN measured offset, so the recovery leaves neither a gap nor a
            # replay. Resuming from the newly measured tail alone would silently
            # drop the span; resuming from 0 would re-render the whole log.
            rebaseline = hydrate_frame(
                delta_patches=delta_patches,
                fold_entities=declared_entities,
                caller=caller,
            )
            offset = _resume_offset(rebaseline)
            if offset is None:
                continue
            batch_base = offset
            resync_pending = True
            known_fingerprint = _scope_fingerprint()
            yield rebaseline
            emitted += 1
            last_heartbeat = time.monotonic()
            if max_frames is not None and emitted >= max_frames:
                return
        # Fingerprint BEFORE reading events. A delta batch rebuilds one full
        # snapshot per BATCH (W1 coalescing — it was per event, ~9MB a time);
        # a memo taken AFTER the batch would absorb any event-less write that
        # raced the batch — swallowing forever the exact violations the
        # watchdog exists to catch (found by live proof). Taken before the
        # read, a racing write always lands in a LATER iteration's candidate
        # and reconciles at the next heartbeat.
        fingerprint_candidate = _scope_fingerprint()
        # The room, re-read once per drain pass. See ``_room``: a restart-free
        # join is only safe when the producer can NOTICE it, and this is where it
        # does. Read beside the fingerprint and for a sibling reason — both are
        # facts about the world that must be taken before the events are, so a
        # change racing the drain lands in a later pass rather than being missed
        # by this one.
        batch_floor, batch_promote = _room()
        emitted_delta = False
        pending: list[tuple[int, Event]] = []
        # The offset a flushed batch applies FROM (S6 gap detection): the cursor
        # before the batch's first entry. Advanced to the flushed offset after
        # every emit so contiguous batches chain base→watermark→base with no gap.
        batch_base = offset
        for next_offset, event in log.iter_from_offset(offset):
            offset = int(next_offset)
            pending.append((offset, event))
            if len(pending) >= _DELTA_BATCH_CAP:
                for frame in _batch_frames_with_liveness(
                    pending,
                    base_offset=batch_base,
                    delta_patches=delta_patches,
                    resync=resync_pending,
                    heartbeat_interval_seconds=heartbeat_interval_seconds,
                    fold_entities=batch_floor,
                    promote_fold_entities=batch_promote,
                    caller=caller,
                ):
                    yield frame
                    emitted += 1
                    last_heartbeat = time.monotonic()
                    if frame.get("type") != "heartbeat":
                        emitted_delta = True
                    if max_frames is not None and emitted >= max_frames:
                        return
                resync_pending = False
                batch_base = offset
                pending = []
        if pending and delta_debounce_seconds > 0:
            # Settle window: an event burst usually lands over a few tens of
            # milliseconds — one bounded sleep lets the tail join the SAME
            # frame instead of costing a full core each. 200ms sits well
            # inside the declared ≤2×heartbeat staleness SLO.
            time.sleep(delta_debounce_seconds)
            for next_offset, event in log.iter_from_offset(offset):
                offset = int(next_offset)
                pending.append((offset, event))
                if len(pending) >= _DELTA_BATCH_CAP:
                    for frame in _batch_frames_with_liveness(
                        pending,
                        base_offset=batch_base,
                        delta_patches=delta_patches,
                        resync=resync_pending,
                        heartbeat_interval_seconds=heartbeat_interval_seconds,
                        fold_entities=batch_floor,
                        promote_fold_entities=batch_promote,
                        caller=caller,
                    ):
                        yield frame
                        emitted += 1
                        last_heartbeat = time.monotonic()
                        if frame.get("type") != "heartbeat":
                            emitted_delta = True
                        if max_frames is not None and emitted >= max_frames:
                            return
                    resync_pending = False
                    batch_base = offset
                    pending = []
        if pending:
            for frame in _batch_frames_with_liveness(
                pending,
                base_offset=batch_base,
                delta_patches=delta_patches,
                resync=resync_pending,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                fold_entities=batch_floor,
                promote_fold_entities=batch_promote,
                caller=caller,
            ):
                yield frame
                emitted += 1
                last_heartbeat = time.monotonic()
                if frame.get("type") != "heartbeat":
                    emitted_delta = True
                if max_frames is not None and emitted >= max_frames:
                    return
            resync_pending = False
        if emitted_delta:
            # Evented mutations legitimately move the fingerprint; adopt the
            # pre-batch candidate so the watchdog only fires on offset-less
            # changes. (An evented write landing between the candidate and the
            # batch read can cause one spurious reconcile — harmless: it is
            # just an extra full-core delta.)
            known_fingerprint = fingerprint_candidate

        if not emitted_delta and time.monotonic() - last_heartbeat >= heartbeat_interval_seconds:
            if fingerprint_candidate != known_fingerprint and _append_state_reconciled(log, fingerprint_candidate):
                known_fingerprint = fingerprint_candidate
                # Skip the sleep: the next iteration reads the appended event
                # and emits the reconcile delta (which resets the heartbeat).
                continue
            yield heartbeat_frame(offset=offset)
            emitted += 1
            last_heartbeat = time.monotonic()
            if max_frames is not None and emitted >= max_frames:
                return

        # Cancellation latency is bounded even when a caller chooses a long
        # poll interval; the production default remains 250ms.
        _bounded_sleep(poll_interval_seconds)


def _scope_fingerprint() -> str:
    """Cheap mtime/size fingerprint of scope/catalog state (Stage 12 backstop).

    Covers exactly the state whose writers have historically slipped the
    event rule or sit outside ``agent_runtime/store/``: the active-scope
    pointer files, the workspace/realm/persona stores, the blueprint
    catalog, and the head-home SessionDB. Evented, high-churn stores
    (tasks/runs/proofs/incidents) are guarded by the store/event CI
    invariant instead — fingerprinting them here would only mask violations
    that test already prevents.

    The SessionDB matters because the persona-chat directory (Chat History)
    is derived from it and its writers emit no EventLog events: with the S6
    patch lane on, a chat-session mint never appears in any patch frame, so
    watermark-gated consumers kept their hydrate-time chat list for the
    stream's whole lifetime (live incident 2026-07-25: the Launcher's Chat
    History froze for ~36h until a restart re-hydrated). The per-session
    turn-element files are deliberately NOT statted here: element flushes
    land many times per second during a streaming turn and would make the
    watchdog append a reconcile (= one full-core delta) every heartbeat.

    The ``running_work`` durable stores (``processes.json`` + the
    background-work ``state.db``) are the same class as the SessionDB: a
    background process starting or exiting rewrites the checkpoint, and a
    delegation dispatch/finalize writes ``async_delegations`` — with NO
    EventLog event either way. The serve read-model cache adopted them on
    2026-08-03 (``_runtime_state_fingerprint``); this backstop did not, so a
    stream consumer rendered the last pre-exit ``running_work`` row forever
    (live incident 2026-08-11: a 20-second terminal task showed
    "Terminal · running" in the Launcher's Activity panel minutes after the
    durable side had settled). Resolved through the writers' own path
    authority, ``running_work_store_paths`` — never a second path list free
    to drift. Note the background-work ``state.db`` can be a DIFFERENT file
    from the chat SessionDB statted above: the chat scope consults a durable
    head-home pointer the background-work writers do not.

    Both SQLite stores are keyed through ``core_cache.sqlite_fingerprint_triples``
    — the same masked triple the boot-cache lane keys them by — and NOT by a raw
    stat of the three siblings, which is what this function did until
    2026-08-21. The mask collapses "no ``-wal`` on disk" and "a zero-length
    ``-wal`` on disk" into one triple, because SQLite deletes the WAL on a clean
    last-close and re-creates it EMPTY on the next open: the difference between
    those two states is the lifetime of somebody's connection, never content.
    Under the raw stat a poll landing while any process merely HELD the database
    open read a fresh ``mtime_ns``, and a poll landing at rest read ``absent`` —
    so a database nobody was writing flapped the fingerprint twice per open, and
    each flap costs one synthetic ``state.reconciled``, which ``patch_coverage``
    classifies UNCOVERED, which demotes the whole batch to a full core rebuild.
    Measured on the operator's runtime over the 22.16 h to 2026-08-21 09:06:
    2 433 ``snapshot_build reason=demote`` against 35 hydrates (median build_ms
    3 083, max 37 266 — 2.29 h of CPU), and 1 239 ``state.reconciled`` — 96.9 %
    of every event appended in the window — at a median 9.0 s spacing, i.e. the
    watchdog reconciling on roughly every other heartbeat, indefinitely, with
    nothing to reconcile. 3 338 distinct fingerprints over 4 597 reconciles
    against a recurring at-rest anchor is that flip's signature and not a
    write's: real writes do not come back to the same value.

    The narrowing is a NARROWING, not a disabling, and the line it holds is the
    same one the turn-element exclusion above holds. A committed write still
    moves this fingerprint within one poll, by one of two paths that SQLite's
    durability rules leave no gap between: uncheckpointed, the ``-wal`` sibling
    is non-empty and is keyed in full (mask suspended); checkpointed, the frames
    are in ``state.db``, whose own mtime and size are the FIRST triple here. So
    the ≤2×heartbeat staleness SLO that 2026-07-25 and 2026-08-11 bought is
    intact — ``test_scope_fingerprint_covers_head_home_session_db`` and
    ``test_scope_fingerprint_covers_running_work_stores`` still pin those two
    incidents, and ``test_scope_fingerprint_moves_on_committed_chat_write``
    pins the direction a constant fingerprint would trivially break.

    ``PRAGMA data_version`` was evaluated first and REJECTED, recorded here so
    it is not re-proposed as the obvious answer it looks like. Measured on
    SQLite 3.45.3: (a) its value is only comparable WITHIN one connection — a
    fresh connection per poll, which is the only shape a stateless fingerprint
    can take, returns a constant and detects nothing; (b) making it work
    therefore means the stream process holding a SessionDB connection open for
    its whole lifetime, which is the exact shape of MCF-27 (every full snapshot
    build leaked a chat SessionDB connection) two days after that was found;
    (c) it is NOT checkpoint-immune as its reputation suggests — a
    ``wal_checkpoint(TRUNCATE)`` with no data change bumps it, so it does not
    even buy a clean answer for the case the mask leaves uncovered; and (d) it
    buys nothing here anyway. Scenario-by-scenario against this mask — read-only
    open/close, write-capable open/close with no write, WAL creation, WAL
    deletion, ``utime`` on the WAL, uncommitted write, rollback, PASSIVE
    checkpoint, committed write from another PROCESS — the two agree on every
    state except the PASSIVE checkpoint, which cannot occur without a preceding
    commit that both already reported.
    """

    parts: list[str] = []
    for path in (paths.active_realm_path(), paths.active_workspace_path()):
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
        except OSError:
            parts.append(f"{path.name}:absent")
    directories = [paths.workspaces_dir(), paths.realms_dir(), paths.agents_dir()]
    for directory in directories:
        try:
            entries = [
                entry
                for pattern in ("*.json", "*.yaml", "*.yml")
                for entry in directory.glob(pattern)
            ]
        except OSError:
            continue
        for entry in sorted(entries):
            try:
                stat = entry.stat()
                parts.append(f"{entry.name}:{stat.st_mtime_ns}:{stat.st_size}")
            except OSError:
                continue
    try:
        from ..chat_session_scope import chat_session_db_path

        db_path = chat_session_db_path()
        for suffix, mtime_ns, size in core_cache.sqlite_fingerprint_triples(db_path):
            parts.append(f"{db_path.name}{suffix}:{mtime_ns}:{size}")
    except Exception:  # noqa: BLE001 — chat persistence absence is itself stable
        parts.append("session_db:unresolved")
    try:
        from ..running_work import running_work_store_paths

        store_paths = running_work_store_paths()
        if not store_paths:
            # An empty tuple means "the home could not be resolved", not
            # "nothing to watch" — same sentinel rule as the serve cache: the
            # part is stable, so an unresolvable home never flaps the
            # fingerprint, but the absence is recorded rather than silent.
            parts.append("running_work_stores:unresolved")
        for store_path in store_paths:
            # The checkpoint is plain JSON; the delegation store is SQLite,
            # whose mutations can land in the WAL without moving the main
            # file's mtime — key the siblings through the shared authority like
            # the chat DB above.
            if store_path.suffix == ".db":
                for suffix, mtime_ns, size in core_cache.sqlite_fingerprint_triples(
                    store_path
                ):
                    parts.append(f"bgwork:{store_path.name}{suffix}:{mtime_ns}:{size}")
                continue
            try:
                stat = store_path.stat()
                parts.append(
                    f"bgwork:{store_path.name}:{stat.st_mtime_ns}:{stat.st_size}"
                )
            except OSError:
                parts.append(f"bgwork:{store_path.name}:absent")
    except Exception:  # noqa: BLE001 — same posture as the chat DB above
        parts.append("running_work_stores:unresolved")
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
