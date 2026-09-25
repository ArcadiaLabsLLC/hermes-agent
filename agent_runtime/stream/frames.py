"""One frame each: hydrate, heartbeat, delta, delta batch, patch batch and the
fold-variants envelope (with its per-subscriber resolution), plus the
watchdog's ``state.reconciled`` append, the delta op and the identity map."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

from hermes_time import now
from ..events import EventLog
from ..models import Event
from ..patch_coverage import normalize_fold_entities
from ..serde import optional_text, section_rows, to_jsonable
from ..snapshot.build import build_snapshot
from ..state_patches.models import STATE_PATCHED_EVENT_TYPE

from .build_policy import _log_snapshot_build
from .vocabulary import DEFAULT_STREAM_CALLER, FOLD_VARIANTS_FRAME_TYPE, STREAM_PATCH_SCHEMA_VERSION, STREAM_SCHEMA_VERSION, _first_text, _redaction_safe_json

__layer__ = "wiring"


def hydrate_frame(
    snapshot: dict[str, Any] | None = None,
    *,
    delta_patches: bool = False,
    fold_entities: Iterable[str] | None = None,
    caller: str = DEFAULT_STREAM_CALLER,
) -> dict[str, Any]:
    """Build the initial warm-stream hydrate frame.

    The hydrate carries the existing full snapshot as the read model payload so
    the stream is additive: the one-shot snapshot remains the canonical fallback
    and consumers can converge by applying this frame exactly like a fresh
    snapshot response.

    S6: when the ``read_model.delta_patches`` lane is on, the hydrate carries an
    additive ``delta_patches: true`` marker — the signal that tells a fold-aware
    launcher to RETAIN this frame's raw core as the patch base (so the next
    ``patch`` frame folds instead of resyncing). The marker is absent when the
    flag is off, so a flag-off hydrate stays byte-identical (its golden asserts
    the key-set, Ruling 0).

    Beside it rides the ACCEPTED ``fold_entities`` (sorted), completing that
    handshake in the direction it was missing: ``delta_patches: true`` told the
    client the lane exists, but nothing told the client which of the entities it
    declared the server actually honoured. On the socket lane that answer is not
    a restatement of the request — the producer is SHARED, so the accepted set is
    the intersection across every attached subscriber (see
    :func:`patch_coverage.accepted_fold_entities`) and a client can be honoured
    for strictly less than it asked for, by somebody else's declaration. A client
    that cannot read the echo is unaffected: it is one additive key on a frame
    that only exists when the lane is on, and the echo is absent entirely when
    the flag is off, so the flag-off hydrate stays byte-identical.
    """

    # ``accept_inflight``: this hydrate may ride the build that is ALREADY
    # running (serve prewarms one right after ``ready``). It loses no event —
    # the frame's ``watermark.event_offset`` is read back out of the snapshot
    # below and ``stream_frames`` tails from exactly that offset, so anything
    # appended after the shared build arrives as the first delta instead.
    # Requiring a newer build would make the launcher's boot hydrate wait for
    # the prewarm AND then pay a second build — strictly worse than no prewarm.
    build_info: dict[str, Any] = {"caller": caller}
    if snapshot is not None:
        snap = snapshot
        waited_ms: int | None = None
    else:
        build_started = time.monotonic()
        snap = build_snapshot(accept_inflight=True, build_info=build_info)
        # NOTE what this measures: the hydrate's WAIT, which under
        # ``accept_inflight`` may be a short ride on a build somebody else
        # started (serve prewarms one right after ``ready``) rather than a
        # build of its own. That is the number the client actually paid, which
        # is the one worth logging here — and ``build_info["role"]`` is what
        # says which of the two this line is reporting.
        waited_ms = int((time.monotonic() - build_started) * 1000)
    parity = snap.get("parity") if isinstance(snap.get("parity"), dict) else {}
    watermark = parity.get("watermark") if isinstance(parity.get("watermark"), dict) else {}
    frame: dict[str, Any] = {
        "type": "hydrate",
        "schema_version": STREAM_SCHEMA_VERSION,
        "generated_at": snap.get("generated_at") or now(),
        "watermark": dict(watermark or {}),
        "identity_map": _identity_map(snap),
        "core": snap,
        "completeness": parity.get("completeness") or {},
        "drops": parity.get("drops") or [],
        "parity_warnings": parity.get("warnings") or [],
    }
    if delta_patches:
        frame["delta_patches"] = True
        frame["fold_entities"] = sorted(normalize_fold_entities(fold_entities))
    if waited_ms is not None:
        _log_snapshot_build(
            reason="hydrate",
            waited_ms=waited_ms,
            offset=(frame.get("watermark") or {}).get("event_offset"),
            snapshot=snap,
            build_info=build_info,
        )
    return frame


def _resume_offset(frame: dict[str, Any]) -> int | None:
    """The tail position a frame says to resume from, or ``None`` if unknown.

    Two distinct absences used to collapse into ``0`` at the call site: a frame
    carrying no watermark key at all, and one carrying an explicit ``None``
    because ``events_watermark`` could not stat the log. Both mean "no position";
    neither means "the head of the log".
    """

    value = (frame.get("watermark") or {}).get("event_offset")
    return None if value is None else int(value)


def heartbeat_frame(
    *, offset: int | None, activity: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Liveness frame that advances the stream watermark without a core delta.

    Pure liveness telemetry: consumers merge it fire-and-forget and a dropped
    frame only ages the HUD, never runtime state. (This frame previously also
    carried the Mission Daemon status block; the background daemon was retired.)

    ``offset=None`` is the honest heartbeat of a stream that has not been able
    to read the log's tail: liveness without a position. It must not be stamped
    ``0``, which every watermark-gated reader would take as a real cursor at the
    head of the log.
    """

    frame = {
        "type": "heartbeat",
        "schema_version": STREAM_SCHEMA_VERSION,
        "generated_at": now(),
        "watermark": {
            "event_offset": None if offset is None else int(offset),
            "captured_at": now(),
        },
    }
    if activity:
        frame["activity"] = activity
    return frame


def _delta_entity(event: Event) -> dict[str, Any]:
    """One event's redaction-safe entity block, shared by the single-delta
    shape and the batched ``events`` list so the two can never drift."""

    payload = _redaction_safe_json(event.payload)
    return {
        "event": {
            **to_jsonable(event),
            "payload": payload,
        },
        "task_id": event.task_id,
        "goal_id": event.task_id,
        "run_id": event.run_id,
        "persona_id": event.persona_id,
        "session_id": event.session_id,
        "correlation_id": payload.get("correlation_id") if isinstance(payload, dict) else None,
    }


def delta_frame(event: Event, *, offset: int, snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": "delta",
        "schema_version": STREAM_SCHEMA_VERSION,
        "generated_at": now(),
        "watermark": {
            "event_offset": int(offset or 0),
            "last_event_ts": event.ts,
            "captured_at": now(),
        },
        "seq": int(offset or 0),
        "op": _delta_op(event),
        "entity": _delta_entity(event),
        "core": snapshot if snapshot is not None else build_snapshot(),
    }


def delta_batch_frame(
    batch: list[tuple[int, Event]], *, snapshot: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One delta frame for a whole drained event batch (transport plan W1).

    The old loop shipped one full ``build_snapshot()`` core PER EVENT — a
    ~9MB rebuild + serialize per append, measured live 2026-07-16 — which is
    why a 30-event burst cost thirty rebuilds on this side and thirty full
    decodes on the launcher side. This frame carries the SAME core exactly
    once for the batch.

    Shape is strictly additive over :func:`delta_frame` (schema_version stays
    1; pinned by ``tests/fixtures/stream_frames/delta_batch.json`` and the
    launcher's byte-identical golden): ``watermark``/``seq`` sit at the FINAL
    offset so the launcher's ``>``-only sequence gate applies the batch once;
    ``entity``/``op`` remain the LAST event for pre-batch consumers; the new
    ``events`` list carries every batched entity and ``coalesced_count`` its
    length. The launcher reads only type/watermark/identity_map/core, so the
    additions must stay additions.
    """

    if not batch:
        raise ValueError("delta_batch_frame requires a non-empty batch")
    last_offset, last_event = batch[-1]
    core = snapshot if snapshot is not None else build_snapshot()
    frame = delta_frame(last_event, offset=last_offset, snapshot=core)
    frame["events"] = [_delta_entity(event) for _, event in batch]
    frame["coalesced_count"] = len(batch)
    return frame


def batch_carries_patch_rows(batch: list[tuple[int, Event]]) -> bool:
    """Whether :func:`patch_batch_frame` would find at least one row in ``batch``.

    The same filter the builder applies, asked as a predicate and deliberately
    WITHOUT materializing the rows: the promotion gate runs on every drained
    batch and only needs the emptiness answer, while building the list costs a
    redaction-safe copy of every payload in it.

    **Why the question exists at all.** Coverability is decided per EVENT
    (:func:`~agent_runtime.patch_coverage.batch_is_patch_coverable` is an
    ``all(...)`` with no "at least one patch" requirement), and a COVERED DOMAIN
    EVENT is coverable on its own — it carries no fold state precisely because
    its paired ``state.patched`` is supposed to ride the same batch. When the
    pair does not arrive, the batch is still coverable, and the frame it used to
    ship was ``{"type": "patch", "patches": [], "watermark": <batch>}``: the
    client advances its watermark having folded NOTHING, and the row it should
    have folded is stale until some unrelated full core happens by. There is no
    downstream gate that can see that — the watermark says the span was applied.

    Five producer-side paths re-open the missing pair, which is why the guard is
    HERE and not in a producer: the three best-effort patch-emit swallows in
    :class:`~agent_runtime.office_store.OfficeStore`, ``update_surface``'s
    no-exception skip when the surface did not previously exist, and the
    cross-process split of ``delta_patches_enabled`` (the writer and the stream
    producer evaluate it independently, so a transient root-config fault in the
    writer suppresses the patch while the stream happily promotes the event-only
    batch). This predicate is the one place that sees all five.
    """

    return any(event.type == STATE_PATCHED_EVENT_TYPE for _, event in batch)


def patch_batch_frame(
    batch: list[tuple[int, Event]], *, base_offset: int
) -> dict[str, Any]:
    """One coalesced batch of foldable ``state.patched`` entries as a v2 ``patch``
    frame — op-based wire patches only, **no full core** (F7's ~9MB rebuild is
    gone on this lane; the per-update transfer drops from a fused megabyte core to
    a sub-4KB patch, the ~99.96% reduction the plan's S6/S7 acceptance names).

    ``base_offset`` is the watermark the batch applies FROM (the offset before
    its first entry); the launcher folds only when its held watermark equals
    ``base_offset`` — a mismatch is a **sequence gap** → checkpoint resync.
    ``watermark.event_offset`` is the post-batch offset the fold advances to,
    keeping the launcher's ``>``-only sequence gate applicable exactly as the
    full-core lane does. ``patches`` is the ordered list of the batch's
    ``{seq, ts, entity, id, op, changed?}`` entries (the op-based wire contract —
    ``changed`` present only for ``upsert``); ``coalesced_count`` is the whole
    batch length (parity with :func:`delta_batch_frame`).

    Refuses an EMPTY FILTERED LIST as well as an empty batch — a frame that
    advances a watermark must carry the state that justifies it, and a batch of
    covered domain events with no paired ``state.patched`` justifies nothing (see
    :func:`batch_carries_patch_rows` for the five paths that produce one). Belt
    and braces with the promotion gate in :func:`_batch_frames_with_liveness`:
    the gate decides the honest lane, this refuses to BUILD the dishonest frame,
    and one authority saying so at each end is cheaper than two that can
    disagree. The caller's guard is the reachable one; this is the one that keeps
    a future caller from re-opening the hole quietly.
    """

    if not batch:
        raise ValueError("patch_batch_frame requires a non-empty batch")
    last_offset, last_event = batch[-1]
    patches = [
        {"seq": int(offset or 0), "ts": event.ts, **_redaction_safe_json(event.payload)}
        for offset, event in batch
        if event.type == STATE_PATCHED_EVENT_TYPE
    ]
    if not patches:
        raise ValueError(
            "patch_batch_frame requires at least one state.patched row: "
            f"{len(batch)} events, none of them {STATE_PATCHED_EVENT_TYPE}"
        )
    return {
        "type": "patch",
        "schema_version": STREAM_PATCH_SCHEMA_VERSION,
        "generated_at": now(),
        "watermark": {
            "event_offset": int(last_offset or 0),
            "last_event_ts": last_event.ts,
            "captured_at": now(),
        },
        "base_offset": int(base_offset or 0),
        "patches": patches,
        "coalesced_count": len(batch),
    }


def fold_variants_frame(
    *,
    patch: dict[str, Any],
    core: dict[str, Any],
    required_tokens: Iterable[str],
) -> dict[str, Any]:
    """Pair one batch's promoted patch with its demoted core for a MIXED room.

    ``required_tokens`` is what a subscriber's declaration must contain to be
    handed the ``patch`` half (:func:`~agent_runtime.patch_coverage
    .batch_required_fold_tokens`). Everyone else gets ``core``, which is the
    identical frame the intersection rule would have sent them anyway — the
    demotion moves from the ROOM to the SUBSCRIBER and nothing else about it
    changes.

    **The build is not paid twice.** The core in here was going to be built
    regardless: under the old intersection rule a batch that any subscriber
    could not fold demoted the whole room, so the snapshot build happened then
    too. What changes is who receives the megabyte, not how many megabytes are
    made. A batch nobody can fold never reaches this function (the caller emits
    the bare core), and a batch everybody can fold never reaches it either (the
    caller emits the bare patch and builds no core at all) — so the envelope
    exists exactly on the batches where the room genuinely disagrees.
    """

    return {
        "type": FOLD_VARIANTS_FRAME_TYPE,
        "required_fold_tokens": sorted(required_tokens),
        "patch": patch,
        "core": core,
    }


def resolve_fold_variant(
    frame: dict[str, Any], declared: Iterable[str] | None
) -> dict[str, Any]:
    """The frame ONE subscriber should be handed, given what it declared.

    Any frame that is not a :data:`FOLD_VARIANTS_FRAME_TYPE` envelope is returned
    unchanged — which is every frame on a homogeneous lane, so the resolver costs
    one dict lookup on the overwhelmingly common path.

    ``declared`` is that subscriber's own declaration, normalized by the same
    :func:`~agent_runtime.patch_coverage.normalize_fold_entities` the coverage
    gate uses (so ``None`` means the historical set here exactly as it does
    there, and never the empty set).

    **The default direction is the core**, and it is the reason this resolver
    takes a declaration rather than a boolean: a caller that passes nothing
    coherent, or a subscriber lane added later that never learned to declare,
    receives the demoted core — correct, merely un-promoted. The failure mode of
    the opposite default is a client handed a patch it answers with a
    re-hydrate, which is the exact regression this negotiation exists to
    prevent, and it would be silent.
    """

    if frame.get("type") != FOLD_VARIANTS_FRAME_TYPE:
        return frame
    required = frozenset(
        str(token) for token in (frame.get("required_fold_tokens") or ())
    )
    if required <= normalize_fold_entities(declared):
        patch = frame.get("patch")
        if isinstance(patch, dict):
            return patch
    core = frame.get("core")
    return core if isinstance(core, dict) else frame


def _append_state_reconciled(log: EventLog, fingerprint: str) -> bool:
    """Append the synthetic watchdog event; True when the offset advanced.

    Cross-process guard: if another stream consumer just reconciled the same
    fingerprint, its event already advanced the offset — skip the duplicate
    and let the normal delta path deliver it. Best effort: a broken event log
    degrades to plain heartbeats (bounded UI ageing), never a stream crash.
    """

    try:
        tail = log.tail(1)
        if tail and tail[0].type == "state.reconciled" and tail[0].payload.get("fingerprint") == fingerprint:
            return True
        log.append(
            Event(
                now(),
                "state.reconciled",
                None,
                None,
                None,
                {"fingerprint": fingerprint, "source": "stream_watchdog"},
            )
        )
        return True
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("state.reconciled append failed", exc_info=True)
        return False


def _delta_op(event: Event) -> str:
    # S21 removed three arms whose whole event family is de-registered, so
    # ``EventLog.append`` refuses them and no frame can ever carry them: the
    # task pair (task.upserted / task.state_changed), proof.attached, and the
    # daemon.* prefix. They now fall through to the generic arm like any other
    # unrouted type. Keep this table in step with the event catalog — an arm for
    # a type that cannot be appended is a classifier branch that reads as live.
    event_type = str(event.type or "")
    if event_type.startswith("run.tool.") or event_type == "run.progress":
        return "chat.trace.appended"
    if event_type.startswith("incident."):
        return event_type
    if event_type.startswith("persona_assignment."):
        return "instance.upserted"
    return "event.appended"


def _identity_map(snapshot: dict[str, Any]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for instance in section_rows(snapshot.get("persona_instances")):
        if not isinstance(instance, dict):
            continue
        canonical = _first_text(instance, "persona_instance_id", "instance_id", "id")
        if not canonical:
            continue
        for key in ("persona_instance_id", "instance_id", "id", "agent_profile_id"):
            alias = optional_text(instance.get(key))
            if alias:
                identity[alias] = canonical
        persona_id = optional_text(instance.get("persona_id"))
        if persona_id and persona_id.startswith("profile:"):
            identity[persona_id.replace(":", "_")] = persona_id
    for channel in section_rows(snapshot.get("operator_channels")):
        if not isinstance(channel, dict):
            continue
        canonical = _first_text(channel, "persona_instance_id", "channel_id", "id")
        if not canonical:
            continue
        for key in ("persona_instance_id", "channel_id", "id", "session_id"):
            alias = optional_text(channel.get(key))
            if alias:
                identity[alias] = canonical
    # The snapshot's legacy->canonical aliases (reconciler registry + live
    # structural drift) OVERRIDE the per-row self aliases above: a retired id
    # must resolve to its canonical channel, not to itself.
    for key, value in (snapshot.get("identity_map") or {}).items():
        if isinstance(key, str) and isinstance(value, str) and key and value:
            identity[key] = value
    return identity
