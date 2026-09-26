"""One core build with liveness: the one-shot predicate, the daemon build job,
the liveness envelope around it, and the full-core batch frames."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Iterator
from typing import Any

from .. import demote_core_reuse
from ..core_cache.lane import REFUSAL_CORE_BEHIND_FRAME, close_cache_lane
from ..core_cache.shadow import shadow_validate
from ..models import Event
from ..parity import core_event_offset
from ..patch_coverage import batch_required_fold_tokens, normalize_fold_entities
from ..request_control import request_cancelled
from ..snapshot.build import build_snapshot
from ..snapshot.receipts import BUILD_ROLE_REUSED

from .build_policy import _defer_demote_build_for_active_turns, _log_snapshot_build
from .frames import batch_carries_patch_rows, delta_batch_frame, fold_variants_frame, heartbeat_frame, patch_batch_frame
from .vocabulary import BATCH_REASON_DEMOTE, DEFAULT_STREAM_CALLER, FRAME_HEARTBEAT, _SNAPSHOT_CANCEL_POLL_SECONDS

__layer__ = "lanes"


def _bounded_sleep(poll_interval_seconds: float) -> None:
    """Sleep the poll interval in cancellation-latency-bounded slices."""

    remaining = max(0.01, float(poll_interval_seconds))
    while remaining > 0 and not request_cancelled():
        interval = min(_SNAPSHOT_CANCEL_POLL_SECONDS, remaining)
        time.sleep(interval)
        remaining -= interval


def _is_one_shot(max_frames: int | None) -> bool:
    """Is this request's whole budget one frame?

    Its own predicate because two different boot-lane decisions turn on it and
    they must not drift apart: the stale-first core is refused for a one-shot,
    and the boot build's liveness heartbeats must not consume its budget. Both
    exist so that ``harness stream --max-frames 1`` — the launcher's forced-
    refresh lane — always answers with an AUTHORITATIVE core, never with a stale
    one and never with a heartbeat carrying nothing.
    """

    return max_frames is not None and int(max_frames) <= 1


class _SnapshotBuildJob:
    """Finite daemon build used by the stream's liveness envelope.

    Snapshot construction is synchronous and can involve filesystem parsing.
    Running it on a daemon worker lets the stream generator keep emitting the
    already-applied watermark as a heartbeat and observe cooperative request
    cancellation. A cancelled consumer does not wait for a finite build to
    finish; the build may complete in the background and remains protected by
    ``build_snapshot``'s existing coalescing contract.
    """

    def __init__(
        self,
        *,
        caller: str = DEFAULT_STREAM_CALLER,
        accept_inflight: bool = False,
    ) -> None:
        #: Whether this job may RIDE a build that is already running rather than
        #: waiting for the next one. Load-bearing for exactly one caller and
        #: default-off for every other, which is why it is a field rather than a
        #: constant: the boot hydrate is the one place ``build_snapshot`` names
        #: as safe for it (its frame carries its own watermark and the tail
        #: resumes from exactly that offset, so nothing is lost — see that
        #: function's own argument). Moving the boot build onto this job WITHOUT
        #: carrying the flag would have made every boot pay a second full build
        #: behind the serve's prewarm, silently: the receipt would still say
        #: ``reason=hydrate`` and only a second ``role=led`` line per boot would
        #: have shown it.
        self.accept_inflight = bool(accept_inflight)
        self.done = threading.Event()
        self.snapshot: dict[str, Any] | None = None
        self.error: BaseException | None = None
        #: Wall time of this job's wait for a core, measured ON the build
        #: thread. Taken here rather than around ``job.done.wait`` because that
        #: wait polls at ``_SNAPSHOT_CANCEL_POLL_SECONDS``, which would round
        #: every build up by as much as 100ms. Set before ``done`` so any reader
        #: that has observed completion has also observed the number. It is a
        #: WAIT, not necessarily a build: the coalescer may hand this job a copy
        #: of somebody else's build, which is what ``build_info`` records.
        self.elapsed_ms: int | None = None
        #: Filled by the builder: role / caller / generation / build_ms. See
        #: :func:`agent_runtime.snapshot.build_snapshot`.
        self.build_info: dict[str, Any] = {"caller": caller}

    def run(self) -> None:
        started = time.monotonic()
        try:
            self.snapshot = build_snapshot(
                accept_inflight=self.accept_inflight, build_info=self.build_info
            )
        except BaseException as exc:  # re-raised on the stream worker
            self.error = exc
        finally:
            self.elapsed_ms = int((time.monotonic() - started) * 1000)
            self.done.set()


def _build_with_liveness(
    job: _SnapshotBuildJob,
    *,
    heartbeat_offset: int | None,
    heartbeat_interval_seconds: float,
    emit_liveness: bool = True,
) -> Iterator[dict[str, Any]]:
    """Run ``job`` on a daemon worker, yielding liveness until it finishes.

    Shared by the two lanes that pay for a full core inside a stream: the boot
    hydrate and an uncovered batch. It owns exactly what the two have in common
    and nothing either of them decides — the worker, the
    ``_SNAPSHOT_CANCEL_POLL_SECONDS`` wait, the ``request_cancelled`` probe, the
    heartbeat cadence, and the ``snapshot_build`` activity block. Which FRAME
    the finished build becomes and which receipt it bills stay at each call
    site, because those are the parts that differ and folding them in would
    have needed a discriminator argument per difference — a helper shaped like
    a switch, which is how one loop becomes two loops wearing one name.

    ``heartbeat_offset`` is the watermark to advertise, and the two callers
    answer it differently on purpose. A batch build keeps the last APPLIED
    offset: advertising the drained batch's future offset would make the
    launcher infer a missed delta and start a second hydrate while this build is
    perfectly healthy. A BOOT build has no applied core at all, so its honest
    answer is ``None`` — ``heartbeat_frame``'s own contract, "liveness without a
    position … must not be stamped ``0``", which every watermark-gated reader
    would take as a real cursor at the head of the log.

    Returns EARLY on cancellation, leaving ``job.done`` unset; callers re-probe
    ``request_cancelled()`` before touching the result, exactly as they must
    after any generator that can return without finishing.

    ``emit_liveness=False`` still runs and waits for the build — it only
    suppresses the frames. See ``_is_one_shot``.
    """

    started = time.monotonic()
    threading.Thread(
        target=job.run,
        name="harness-stream-snapshot",
        daemon=True,
    ).start()
    heartbeat_interval = max(0.05, float(heartbeat_interval_seconds or 0.05))
    next_heartbeat = started + heartbeat_interval
    while not job.done.wait(_SNAPSHOT_CANCEL_POLL_SECONDS):
        if request_cancelled():
            return
        current = time.monotonic()
        if current >= next_heartbeat:
            if emit_liveness:
                yield heartbeat_frame(
                    offset=heartbeat_offset,
                    activity={
                        "kind": "snapshot_build",
                        "state": "busy",
                        "elapsed_ms": int((current - started) * 1000),
                    },
                )
            next_heartbeat = current + heartbeat_interval


def _full_core_batch_frames(
    batch: list[tuple[int, Event]],
    *,
    base_offset: int,
    heartbeat_interval_seconds: float,
    reason: str = "full_core",
    caller: str = DEFAULT_STREAM_CALLER,
) -> Iterator[dict[str, Any]]:
    """Emit liveness while one uncovered batch builds its authoritative core.

    ``reason`` names why this batch is paying for a full core — it is the
    caller's classification, not something this function can re-derive, and it
    is what makes the emitted ``snapshot_build`` line actionable. ``caller``
    names WHO is paying, which this function likewise cannot re-derive: the same
    generator serves the serve hub and a terminal.

    **THE CORE MUST REACH THE OFFSET IT IS ABOUT TO BE STAMPED WITH (MCF-Q1).**
    This lane is the designated CARRIER of everything the patch lane cannot
    express (``patch_coverage``: "The demote to a full core is what carries
    it"), and that design assumes the core it demotes to is FRESH. When it is
    not, the frame is the worst shape this producer can emit: a ``delta`` at an
    offset strictly ahead of the client's, whose core the launcher applies
    WHOLESALE — so a section present only via folded patches (a persona instance
    dragged onto the canvas seconds ago) is replaced away by the older core's
    complete copy of that section, while everything that predates the core
    survives. That asymmetry is the 2026-08-21 "the new agent disappears, the old
    one does not" report.

    The producer of a stale core here is the boot cache lane, and closing that
    lane's window correctly (``shadow_validate``) is the root fix — but
    it is NOT sufficient, which is why this guard is not belt-and-braces. The
    operator's log shows the same shape on 2026-08-20 at 18:30:11 and 18:38:43,
    where the boot's shadow validation DIVERGED and closed the window about ten
    seconds in: the erasing frames landed inside a window that was going to close
    anyway. Only a check at the frame — where the core and the offset it is about
    to be stamped with are both in hand — refuses that one.

    ``7204896978`` established this invariant INSIDE a build (an offset stamped
    ahead of the content it was read from); this is the same invariant one layer
    out, over a core the builder handed back rather than built. The check costs
    two dict lookups and fires only when the invariant is already broken.

    **W3-H2: the second demote at one offset does not build again.** Three
    ``role=led`` demote builds landed at offset 89961793 in the operator's log
    on 2026-08-22, each ~3 s, each writing back the same fingerprint. The
    coalescer cannot merge them because they are SEQUENTIAL, not concurrent —
    see ``demote_core_reuse`` for why a positional check makes reuse safe where
    riding an in-flight build is not. The reuse is of the CORE only: this
    function still builds and yields a complete frame for every caller, which is
    what the BO-1 convergence-pair invariant requires.
    """

    last_offset = int(batch[-1][0] or 0)
    reused = (
        demote_core_reuse.consult(floor=last_offset)
        if reason == BATCH_REASON_DEMOTE
        else None
    )
    if reused is not None:
        if request_cancelled():
            # The same probe the build arm makes on the way out. A reuse has no
            # wait to interrupt, but a consumer that cancelled before this batch
            # was reached must not be handed a frame just because answering it
            # became cheap.
            return
        # No build, no worker, no liveness: there is nothing to be live DURING.
        # ``build_ms`` rides from the reused core's own envelope so the receipt
        # still names what the frame's core cost to make.
        frame = delta_batch_frame(batch, snapshot=reused)
        _log_snapshot_build(
            reason=reason,
            waited_ms=0,
            offset=(frame.get("watermark") or {}).get("event_offset"),
            events=len(batch),
            snapshot=reused,
            build_info={
                "caller": caller,
                "role": BUILD_ROLE_REUSED,
                "generation": None,
            },
            core_source=demote_core_reuse.CORE_SOURCE_REUSED_SAME_OFFSET,
        )
        yield frame
        return

    # Stage 5: stand aside for a live agent run before paying for a full core.
    # Placed AFTER the reuse gate on purpose — a reuse builds nothing, so there
    # is no CPU to yield and nothing to wait for — and BEFORE the job so the
    # wait is not held while a worker thread is already running. Bounded by
    # ``SNAPSHOT_DEMOTE_DEFERRAL_MAX_MS`` and a no-op on every lane but demote.
    _defer_demote_build_for_active_turns(reason=reason, caller=caller)
    if request_cancelled():
        return

    job = _SnapshotBuildJob(caller=caller)
    # Keep the watermark at the last APPLIED core — see ``_build_with_liveness``
    # for why this caller answers ``heartbeat_offset`` differently from the boot.
    yield from _build_with_liveness(
        job,
        heartbeat_offset=base_offset,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    if request_cancelled():
        return
    if job.error is not None:
        raise job.error
    if job.snapshot is None:
        raise RuntimeError("snapshot build completed without a result")
    core_offset = core_event_offset(job.snapshot)
    if core_offset is not None and core_offset < last_offset:
        # The ONE reachable producer of this shape is the boot cache lane: a
        # genuine build in this lane cannot be behind, because the batch was
        # DRAINED before the build started and this job never rides an in-flight
        # one (``accept_inflight`` is default-off here, deliberately). So the
        # answer is to stop the lane and pay for the build once, rather than to
        # ship a frame whose watermark is a lie about its own core.
        close_cache_lane(
            reason=REFUSAL_CORE_BEHIND_FRAME,
            caller=caller,
            detail=f"core_offset={core_offset} frame_offset={last_offset}",
        )
        job = _SnapshotBuildJob(caller=caller)
        yield from _build_with_liveness(
            job,
            heartbeat_offset=base_offset,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )
        if request_cancelled():
            return
        if job.error is not None:
            raise job.error
        if job.snapshot is None:
            raise RuntimeError("snapshot build completed without a result")
    frame = delta_batch_frame(batch, snapshot=job.snapshot)
    if reason == BATCH_REASON_DEMOTE:
        # Held for the NEXT demote build only, and keyed on this core's own
        # pre-build watermark rather than on a stat taken now — see
        # ``demote_core_reuse.remember`` for the direction argument.
        demote_core_reuse.remember(job.snapshot)
    if job.elapsed_ms is not None:
        _log_snapshot_build(
            reason=reason,
            waited_ms=job.elapsed_ms,
            offset=(frame.get("watermark") or {}).get("event_offset"),
            events=len(batch),
            snapshot=job.snapshot,
            build_info=job.build_info,
        )
    yield frame


def _batch_frames_with_liveness(
    batch: list[tuple[int, Event]],
    *,
    base_offset: int,
    delta_patches: bool,
    resync: bool,
    heartbeat_interval_seconds: float,
    fold_entities: Iterable[str] | None = None,
    promote_fold_entities: Iterable[str] | None = None,
    caller: str = DEFAULT_STREAM_CALLER,
) -> Iterator[dict[str, Any]]:
    accepted = normalize_fold_entities(fold_entities)
    #: What SOME subscriber can fold, when the room disagrees. ``None`` — every
    #: caller but the serve hub, and the hub itself whenever its room is
    #: homogeneous — collapses this to ``accepted``, and then the split branch
    #: below is unreachable by construction: ``required <= accepted`` and
    #: ``required <= promote`` become the same test, so the first one takes every
    #: batch the second could have. That is the whole single-subscriber
    #: no-change guarantee, and it is a property of these two lines rather than
    #: a promise kept elsewhere.
    promote = (
        accepted
        if promote_fold_entities is None
        else normalize_fold_entities(promote_fold_entities)
    )
    # Coverable is not the same as EXPRESSIBLE. A covered domain event with no
    # paired `state.patched` in the batch is coverable on its own and would ship
    # an empty `patches` list — a watermark the client advances having folded
    # nothing. The honest answer for that batch is the core: state moved and this
    # lane has no patch to say what. See `batch_carries_patch_rows` for the five
    # producer paths that reach here.
    if delta_patches and not resync and batch_carries_patch_rows(batch):
        # The SET a declaration must contain, derived once, rather than the
        # boolean asked once per candidate declaration. `batch_required_fold_
        # tokens` returning None is `batch_is_patch_coverable` returning False
        # for every declaration there is — the structurally uncovered batch —
        # and the equivalence is pinned by test rather than restated here.
        required = batch_required_fold_tokens(event for _, event in batch)
        if required is not None and required <= accepted:
            yield patch_batch_frame(batch, base_offset=base_offset)
            return
        if required is not None and required <= promote:
            # The room DISAGREES about this batch: somebody can fold it and
            # somebody cannot. Build both halves once and let the fan-out hand
            # each subscriber the one it declared for. The core here is the
            # frame the intersection rule would have sent EVERYONE, so this
            # costs the same build and saves the wire for whoever declared.
            promoted = patch_batch_frame(batch, base_offset=base_offset)
            for frame in _full_core_batch_frames(
                batch,
                base_offset=base_offset,
                heartbeat_interval_seconds=heartbeat_interval_seconds,
                reason=BATCH_REASON_DEMOTE,
                caller=caller,
            ):
                # Liveness passes through UNPAIRED and unchanged: a heartbeat
                # says the producer is alive while a core builds, which is the
                # same true sentence for every subscriber in the room and
                # carries no state either half could disagree about.
                if frame.get("type") == FRAME_HEARTBEAT:
                    yield frame
                    continue
                yield fold_variants_frame(
                    patch=promoted, core=frame, required_tokens=required
                )
            return
    # Classified HERE because this is the only place that holds all three
    # facts. `resync` is a re-baseline the client asked for; with the lane off
    # every batch is a full core by design (not a demotion); otherwise either the
    # coverage gate rejected the batch or it carried no patch row to express, and
    # a foldable update just paid for a whole snapshot — the case worth grepping
    # for. Both demote reasons bill the same `snapshot_build reason=demote`
    # receipt, which is what makes the empty-frame paths attributable at all.
    yield from _full_core_batch_frames(
        batch,
        base_offset=base_offset,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        reason=(
            "resync"
            if resync
            else (BATCH_REASON_DEMOTE if delta_patches else "full_core")
        ),
        caller=caller,
    )
