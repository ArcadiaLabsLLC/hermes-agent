"""One frame each: hydrate, heartbeat, delta, delta batch, patch batch, the
``running_work`` section frame, the ``persona_chat_turn`` root overlay and the
fold-variants envelope (with its
per-subscriber resolution), plus the watchdog's ``state.reconciled`` append,
the delta op and the identity map."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from typing import Any

from hermes_time import now
from ..chat_turn_presence import EVENT_TURN_ENDED, EVENT_TURN_STARTED
from ..events import EventLog
from ..models import Event
from ..patch_coverage import normalize_fold_entities
from ..running_work import build_running_work
from ..serde import optional_text, section_rows, to_jsonable
from ..snapshot.build import build_snapshot
from ..state_patches.models import STATE_PATCHED_EVENT_TYPE

from .build_policy import _log_snapshot_build
from .vocabulary import EVENT_RUN_PROGRESS, EVENT_STATE_RECONCILED, FRAME_DELTA, FRAME_HEARTBEAT, FRAME_HYDRATE, FRAME_PATCH, FRAME_PERSONA_CHAT_TURN, FRAME_RUNNING_WORK, STREAM_PERSONA_CHAT_TURN_SCHEMA_VERSION, logger, DEFAULT_STREAM_CALLER, FOLD_VARIANTS_FRAME_TYPE, STREAM_PATCH_SCHEMA_VERSION, STREAM_SCHEMA_VERSION, first_text, _redaction_safe_json

__layer__ = "lanes"


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
    build_info: dict[str, Any] = {"caller": caller, "reason": "hydrate"}
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
        "type": FRAME_HYDRATE,
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
        "type": FRAME_HEARTBEAT,
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


def batch_ends_a_chat_turn(batch: list[tuple[int, Event]]) -> bool:
    """Whether ``batch`` carries a ``persona_chat.turn_ended`` publish."""

    return any(getattr(event, "type", None) == EVENT_TURN_ENDED for _, event in batch)


def running_work_frame(*, as_of_offset: int | None) -> dict[str, Any] | None:
    """The ``running_work`` section alone, read NOW; ``None`` if it cannot be read.

    Why it exists: a turn's ``persona_chat.turn_ended`` batch can never ride the
    patch lane (the event is uncovered), so the only frame that said the turn
    left ``running_work`` was the next full core — measured 2026-10-01 at
    16.6 s after the event (a 10.2 s build queued behind another caller's), and
    every console showed the finished turn as running for all of it. The
    section is cheap on its own; the core around it is not.

    ``as_of_offset`` is the log position the read was taken AFTER, and it is
    deliberately not a ``watermark``: this frame is an overlay of one section on
    the held core, superseded by the next core at or past that offset, and must
    never move a consumer's sequence. ``None`` is "position unknown", not 0.

    A read that raises answers ``None`` and the caller ships nothing: the core
    that follows still carries the section, so the cost of a miss is the old
    lag, never a wrong row.
    """

    try:
        section = build_running_work()
    except Exception:
        logger.debug("running_work_frame: section read failed", exc_info=True)
        return None
    return {
        "type": FRAME_RUNNING_WORK,
        "schema_version": STREAM_SCHEMA_VERSION,
        "generated_at": now(),
        "as_of_offset": None if as_of_offset is None else int(as_of_offset),
        "running_work": _redaction_safe_json(section),
    }


#: The events one chat turn appends, and nothing else (plan h-turn1 §2 C0.1):
#: the turn's three publishes and its chat-trace lane
#: (``persona_chat_history.vocabulary._TRACE_EVENT_TYPES``).
_TURN_PUBLISH_EVENT_TYPES = frozenset(
    {EVENT_TURN_STARTED, EVENT_TURN_ENDED, "persona_chat.projected"}
)
_TURN_TRACE_EVENT_TYPES = frozenset(
    {EVENT_RUN_PROGRESS, "run.tool.started", "run.tool.finished"}
)
#: The turn's auto-title (``chat_events._publish_persona_chat_metadata_event``):
#: it moves the root's title, which the root's history row and channel carry.
#: Only this ``change_kind``: a future kind is not known to stay inside the row.
_TURN_METADATA_EVENT_TYPE = "persona_chat.metadata_updated"
_TURN_METADATA_CHANGE_KINDS = frozenset({"auto_title_updated"})

#: The watchdog's ``state.reconciled`` ``source`` (``session.StreamSession.beat``).
WATCHDOG_SOURCE = "stream_watchdog"
#: The fingerprint families a reconcile may name and still ride a turn batch:
#: the chat database (only with its ``chat_roots``) and the ``running_work``
#: stores (the overlay ships the whole section). Never ``scope``.
_TURN_COVERABLE_FAMILIES = frozenset({"chat_db", "running_work"})


def _turn_event_roots(event: Event) -> tuple[str, ...] | None:
    """The chat roots ``event`` belongs to (possibly none), or ``None`` when it
    is not an event a turn batch may carry.

    A watchdog reconcile is a turn event when it proves what moved: only
    ``chat_db`` / ``running_work`` families, and a chat-database move named
    down to existing root chats whose rows alone changed (``chat_roots``,
    :func:`fingerprint.scope_move_attribution`). It names those roots; a
    ``running_work``-only move names none and is carried by whatever root the
    batch's other events name.
    """

    event_type = getattr(event, "type", None)
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event_type in _TURN_PUBLISH_EVENT_TYPES:
        root = optional_text(payload.get("root_chat_session_id"))
        return (root,) if root else None
    if event_type == _TURN_METADATA_EVENT_TYPE:
        root = optional_text(payload.get("root_chat_session_id"))
        if root and payload.get("change_kind") in _TURN_METADATA_CHANGE_KINDS:
            return (root,)
        return None
    if event_type in _TURN_TRACE_EVENT_TYPES:
        # A ``run.*`` with no session is a task-run trace, not a chat turn's.
        root = optional_text(event.session_id)
        return (root,) if root else None
    if event_type == EVENT_STATE_RECONCILED and payload.get("source") == WATCHDOG_SOURCE:
        families = payload.get("families")
        if not isinstance(families, list) or not families or not set(families) <= _TURN_COVERABLE_FAMILIES:
            return None
        roots = payload.get("chat_roots")
        if "chat_db" in families:
            if not isinstance(roots, list) or not roots:
                return None
            named = tuple(text for text in (optional_text(root) for root in roots) if text)
            return named if len(named) == len(roots) else None
        return ()
    return None


def batch_turn_roots(batch: list[tuple[int, Event]]) -> list[tuple[str, int]] | None:
    """The chat roots a batch made ONLY of turn events names, or ``None``.

    A TURN batch is one where every event is a turn publish carrying
    ``payload.root_chat_session_id``, the turn's auto-title, a chat-trace
    ``run.*`` carrying a ``session_id``, or a watchdog reconcile that proves it
    moved only those roots' rows (:func:`_turn_event_roots`). Anything else in
    it — a ``state.patched`` of any entity, ``gateway.peer.updated`` (ruling
    C2-r3), an unattributed ``state.reconciled``, ``persona_instance.chat_opened``,
    a session-less ``run.*`` — answers ``None`` and the batch takes today's
    lanes unchanged. A batch that names no root at all answers ``None``.

    Each root is paired with the offset of ITS last event, and the list is in
    that order: a batch naming two roots ships two frames, chained so the first
    advances the watermark to its root's last event and the second applies from
    there (the client's gap gate holds across both).
    """

    if not batch:
        return None
    last_seen: dict[str, int] = {}
    for offset, event in batch:
        roots = _turn_event_roots(event)
        if roots is None:
            return None
        for root in roots:
            last_seen[root] = int(offset or 0)
    if not last_seen:
        return None
    return sorted(last_seen.items(), key=lambda item: item[1])


def _turn_instance(
    root: str, batch: list[tuple[int, Event]], instances: list[Any]
) -> Any | None:
    """The persona instance whose chat ``root`` is: the turn publish names it,
    else the instance bound to the session, else the mint's owner."""

    from ..persona_assignments import chat_session_owner_instance_id

    by_id = {str(getattr(item, "id", "") or ""): item for item in instances}
    for _offset, event in batch:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if (
            getattr(event, "type", None) in _TURN_PUBLISH_EVENT_TYPES
            and optional_text(payload.get("root_chat_session_id")) == root
        ):
            named = by_id.get(optional_text(payload.get("persona_instance_id")) or "")
            if named is not None:
                return named
    for instance in instances:
        if root in (
            optional_text(getattr(instance, "default_chat_session_id", None)),
            optional_text(getattr(instance, "session_id", None)),
        ):
            return instance
    return by_id.get(chat_session_owner_instance_id(root) or "")


def _channel_for_instance(channels: list[dict[str, Any]], instance_id: str) -> dict[str, Any] | None:
    for channel in channels:
        if not isinstance(channel, dict):
            continue
        if channel.get("persona_instance_id") == instance_id or instance_id in (
            channel.get("source_instance_ids") or ()
        ):
            return channel
    return None


def _read_persona_chat_turn_sections(
    root: str, batch: list[tuple[int, Event]]
) -> tuple[dict[str, Any], dict[str, int]]:
    """One root's turn sections, read NOW by the core's own builders.

    The FULL instance list goes in everywhere attribution or ranking needs it —
    the history bound ranks every candidate exactly as the core does and only
    then narrows to the root (``only_session_ids``, plan §2 C0.3), and the
    channel join takes every instance so display names and relationships are
    the core's — so each row equals the row a full core built now would carry.
    The roster is ``list_all`` (a read), never ``ensure_for_personas`` (it
    writes). Raises when any read fails; the caller demotes.
    """

    from ..config import ensure_persisted_personas
    from ..operator_channels import operator_channel_summary
    from ..persona_assignments import PersonaInstanceStore, persona_instance_summary
    from ..persona_chat_history import persona_chat_history_summary, persona_chat_trace_summary
    from ..persona_chat_history.vocabulary import DEFAULT_PERSONA_CHAT_MESSAGE_TAIL
    from ..persona_lifecycle import is_runtime_persona
    from ..resolution import runtime_resolution_scope
    from ..snapshot.details import persona_session_db_scope
    from ..snapshot.receipts import _persona_chat_history_frame
    from ..snapshot_turn_yield import snapshot_yield_point
    from ..store import AgentStore

    timings: dict[str, int] = {}
    snapshot_yield_point()
    with runtime_resolution_scope(), persona_session_db_scope() as session_db:
        event_log = EventLog()
        instances = PersonaInstanceStore(event_log=event_log).list_all()
        instance = _turn_instance(root, batch, instances)
        if instance is None:
            raise LookupError(f"no persona instance owns chat root {root!r}")
        started = time.perf_counter()
        omitted: set[str] = set()
        history = persona_chat_history_summary(
            persona_instances=instances,
            session_db=session_db,
            message_tail=DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
            omitted_session_ids=omitted,
            only_session_ids=frozenset({root}),
        )
        timings["history_ms"] = int((time.perf_counter() - started) * 1000)
        snapshot_yield_point()
        started = time.perf_counter()
        trace = persona_chat_trace_summary(
            persona_instances=[instance],
            event_log=event_log,
            message_tail=DEFAULT_PERSONA_CHAT_MESSAGE_TAIL,
        )
        timings["trace_ms"] = int((time.perf_counter() - started) * 1000)
        snapshot_yield_point()
        channels = operator_channel_summary(
            persona_instances=instances,
            persona_chat_history=history,
            persona_chat_trace=trace,
            intentionally_omitted_history_session_ids=omitted,
        )
    channel = _channel_for_instance(channels, str(instance.id))
    if channel is None:
        raise LookupError(f"no operator channel for {instance.id!r}")
    personas = {
        str(getattr(agent, "id", "") or ""): agent
        for agent in AgentStore().list_all()
        if is_runtime_persona(agent)
    }
    history_rows = _persona_chat_history_frame(history)
    snapshot_yield_point()
    sections = {
        "persona_instance_id": str(instance.id),
        "persona_chat_history": to_jsonable(history_rows[0]) if history_rows else None,
        "operator_channel": to_jsonable(channel),
        "persona_instance": to_jsonable(
            persona_instance_summary(
                instance,
                personas.get(str(getattr(instance, "persona_id", "") or "")),
                roster=ensure_persisted_personas,
            )
        ),
        "running_work": _redaction_safe_json(build_running_work()),
        "omitted": root in omitted,
    }
    return sections, timings


def persona_chat_turn_frames(
    batch: list[tuple[int, Event]],
    roots: list[tuple[str, int]],
    *,
    base_offset: int,
    caller: str = DEFAULT_STREAM_CALLER,
) -> list[dict[str, Any]] | None:
    """One ``persona_chat_turn`` frame per root of a turn batch, or ``None``.

    Each frame carries everything a chat turn moves for its root — the history
    row (``null`` when the core's bound omits the root, with ``omitted: true``),
    the operator channel, the persona-instance row, and ``running_work`` — and
    ``base_offset`` / ``watermark`` exactly as :func:`patch_batch_frame` does,
    because the declaring subscriber CONSUMES the batch with it. Frames are
    chained in ``roots`` order: frame k applies from frame k-1's watermark and
    the last one ends at the batch's last offset.

    The second subscriber of the same batch reuses the first's read
    (:mod:`agent_runtime.turn_section_reuse`), re-stamped with its own offsets.
    ANY root whose read fails answers ``None`` for the whole batch, and the
    caller demotes it as before: the cost of a miss is the old core, never a
    wrong row. Not ``prompt_observability`` and not ``events`` (ruling C1-r1:
    they wait for the next full core). No size cap (ruling C1-r2).
    """

    from .. import turn_section_reuse

    if not batch or not roots:
        return None
    last_offset, last_event = batch[-1]
    frames: list[dict[str, Any]] = []
    applies_from = int(base_offset or 0)
    for index, (root, root_last) in enumerate(roots):
        stamp_offset = int(last_offset or 0) if index == len(roots) - 1 else int(root_last)
        started = time.monotonic()
        sections = turn_section_reuse.consult(root, floor=stamp_offset)
        if sections is None:
            sections = turn_section_reuse.await_inflight(
                root, floor=stamp_offset, timeout_s=_TURN_SECTION_INFLIGHT_WAIT_S
            )
        timings: dict[str, int] = {}
        source = turn_section_reuse.SOURCE_REUSED
        if sections is None:
            source = turn_section_reuse.SOURCE_BUILT
            sections, timings = _read_turn_sections_standing_aside(root, batch, caller=caller)
            if sections is None:
                return None
        root_events = [event for _offset, event in batch if root in (_turn_event_roots(event) or ())]
        frame = {
            "type": FRAME_PERSONA_CHAT_TURN,
            "schema_version": STREAM_PERSONA_CHAT_TURN_SCHEMA_VERSION,
            "generated_at": now(),
            "base_offset": applies_from,
            "watermark": {
                "event_offset": stamp_offset,
                "last_event_ts": (root_events[-1] if root_events else last_event).ts,
                "captured_at": now(),
            },
            "coalesced_count": len(batch),
            "root_chat_session_id": root,
            **sections,
        }
        logger.info(
            "turn_section reason=%s root=%s waited_ms=%d history_ms=%s trace_ms=%s "
            "yielded_ms=%s bytes=%d source=%s caller=%s offset=%d pid=%d",
            _turn_section_reason(root_events),
            root,
            int((time.monotonic() - started) * 1000),
            timings.get("history_ms", "-"),
            timings.get("trace_ms", "-"),
            timings.get("yielded_ms", "-"),
            len(json.dumps(frame, default=str)),
            source,
            caller,
            stamp_offset,
            os.getpid(),
        )
        frames.append(frame)
        applies_from = stamp_offset
    return frames


#: How long a second lane waits for the first lane's in-flight read of the same
#: root: the read's whole stand-aside budget plus a cold read.
_TURN_SECTION_INFLIGHT_WAIT_S = 20.0


def _read_turn_sections_standing_aside(
    root: str, batch: list[tuple[int, Event]], *, caller: str
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """One root's read, off the turn's latency-critical windows.

    The overlay is 0.9–1.8 s of pure Python on the serve's interpreter (live
    2026-10-06: history 308–818 ms, trace 470–552 ms), and a START batch's read
    lands exactly where the turn assembles and dispatches its provider call. So
    the read runs under the core build's own rule (:mod:`snapshot_turn_yield`,
    the owner's 2026-10-03 ruling — a build running during a live turn's hot
    window is a bug): it waits before it starts and pauses at each section
    boundary while a turn is inside a hot window, within the same budget. The
    sections are still read NOW by the core's own builders, so C1's equality
    rule is untouched — standing aside only makes them newer than the batch,
    the direction every reuse here already accepts.
    """

    from .. import turn_section_reuse
    from ..parity import events_position
    from ..snapshot_turn_yield import build_yield_scope, log_build_yield

    position = events_position().get("event_offset")
    key = turn_section_reuse.begin(root, position=position)
    try:
        with build_yield_scope() as standing_aside:
            try:
                sections, timings = _read_persona_chat_turn_sections(root, batch)
            except Exception:
                logger.debug("persona_chat_turn: section read failed root=%s", root, exc_info=True)
                return None, {}
        log_build_yield(standing_aside, caller=caller, generation="turn_section")
        timings["yielded_ms"] = standing_aside.waited_ms if standing_aside is not None else 0
        turn_section_reuse.remember(root, sections, position=position)
        return sections, timings
    finally:
        turn_section_reuse.finish(key)


def _turn_section_reason(root_events: list[Event]) -> str:
    types = {getattr(event, "type", None) for event in root_events}
    if EVENT_TURN_ENDED in types:
        return "end"
    if EVENT_TURN_STARTED in types:
        return "start"
    return "trace"


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
        "type": FRAME_DELTA,
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
        "type": FRAME_PATCH,
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


def _append_state_reconciled(
    log: EventLog, fingerprint: str, attribution: dict[str, Any] | None = None
) -> bool:
    """Append the synthetic watchdog event; True when the offset advanced.

    ``attribution`` (:func:`fingerprint.scope_move_attribution`) rides in the
    payload: the moved ``families`` and, when provable, the ``chat_roots`` whose
    rows moved — what lets the turn rule cover the reconcile instead of
    demoting its batch.

    Cross-process guard: if another stream consumer just reconciled the same
    fingerprint, its event already advanced the offset — skip the duplicate
    and let the normal delta path deliver it, but only when that event claims
    at least as much as this one would (a narrower claim would let this lane's
    batch be covered for less than moved). Best effort: a broken event log
    degrades to plain heartbeats (bounded UI ageing), never a stream crash.
    """

    extra = dict(attribution or {})
    try:
        tail = log.tail(1)
        if (
            tail
            and tail[0].type == EVENT_STATE_RECONCILED
            and tail[0].payload.get("fingerprint") == fingerprint
            and _reconcile_claims_at_least(tail[0].payload, extra)
        ):
            return True
        log.append(
            Event(
                now(),
                EVENT_STATE_RECONCILED,
                None,
                None,
                None,
                {"fingerprint": fingerprint, "source": WATCHDOG_SOURCE, **extra},
            )
        )
        return True
    except Exception:  # noqa: BLE001
        logger.warning("state.reconciled append failed", exc_info=True)
        return False


def _reconcile_claims_at_least(held: dict[str, Any], ours: dict[str, Any]) -> bool:
    """Does the held reconcile's payload say at least what ``ours`` would?

    An unattributed event (no ``chat_roots`` where the chat database moved, a
    ``scope`` move, or no ``families`` at all) is never covered by the turn rule, so it demotes
    whatever rode with it — it claims everything."""

    held_families = held.get("families")
    if not isinstance(held_families, list):
        return True
    if "chat_db" in held_families and not held.get("chat_roots"):
        return True
    if not set(held_families) <= _TURN_COVERABLE_FAMILIES:
        return True
    if not set(ours.get("families") or ()) <= set(held_families):
        return False
    if "chat_db" in (ours.get("families") or ()):
        return bool(ours.get("chat_roots")) and set(ours["chat_roots"]) <= set(held.get("chat_roots") or ())
    return True


def _delta_op(event: Event) -> str:
    # S21 removed three arms whose whole event family is de-registered, so
    # ``EventLog.append`` refuses them and no frame can ever carry them: the
    # task pair (task.upserted / task.state_changed), proof.attached, and the
    # daemon.* prefix. They now fall through to the generic arm like any other
    # unrouted type. Keep this table in step with the event catalog — an arm for
    # a type that cannot be appended is a classifier branch that reads as live.
    event_type = str(event.type or "")
    if event_type.startswith("run.tool.") or event_type == EVENT_RUN_PROGRESS:
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
        canonical = first_text(instance, "persona_instance_id", "instance_id", "id")
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
        canonical = first_text(channel, "persona_instance_id", "channel_id", "id")
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
