"""``runtime.office.get`` / ``subscribe`` / ``unsubscribe`` — the office READ
verbs, the projection they share, and ``log_office_write`` (the one log line
every office write emits).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_READ

from agent_runtime.serve_rpc.protocol import (
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    RpcContext,
    err,
    logger,
    ok,
)
from agent_runtime.serve_rpc.registry import method
from agent_runtime.serve_rpc.params import workspace_id_required, unknown_workspace, _workspace_id_param

__layer__ = "lanes"

__all__ = [
    "_office_projection",
    "_runtime_office_get",
    "_runtime_office_subscribe",
    "_runtime_office_unsubscribe",
    "log_office_write",
]


def log_office_write(
    *, op: str, correlation_id: str | None, **fields: Any
) -> None:
    """ONE line per office WRITE, in the serve child's own log (EG-2.3 / CI-2).

    The hermes half of the two-log join. Before this line existed the serve
    child's log named no office write at all — plan §8 item 5 measured 12 MB with
    zero ``office`` lines — so "which RPC produced this launcher update" could
    only be answered by anchoring on the launcher's flush receipt, and that
    anchoring is exactly what produced the confidently wrong "deletes take 3.8 s"
    diagnosis (Plan D's opening).

    Shaped like ``stream.log_stream_attach`` on purpose — ``key=value`` after a
    leading event word, ``-`` for an absent value — because an operator greps the
    two together and a second format would make the join a parse instead of a
    grep. ``corr=-`` rather than an omitted key: a write with no gesture behind
    it is a FACT worth reading, and an omitted key is indistinguishable from an
    old build.

    Never raises: an instrument must not be the reason a write fails.
    """

    try:
        extras = " ".join(
            f"{key}={'-' if value is None else value}" for key, value in fields.items()
        )
        logger.info(
            "office_write op=%s corr=%s%s",
            op,
            correlation_id or "-",
            f" {extras}" if extras else "",
        )
    except Exception:  # pragma: no cover - observability must never fail a lane
        pass


@method("runtime.office.get", tier=TIER_READ)
def _runtime_office_get(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """ONE workspace's office projection — canvas-shaped, and bounded.

    Carries per item: ``item_id``, ``kind``, ``persona_id`` (the character-class
    POINTER), ``persona_instance_id`` (the owning actor's IDENTITY binding, or
    ``null`` when the actor is class-keyed), ``revision`` (the owning actor's,
    and the token ``runtime.office.upsert`` guards on), ``folder``, ``position``,
    ``scale``, ``display_name``, ``pet_slug``; plus surface-level ``folders``,
    ``revision``, ``updated_at``.

    ``persona_instance_id`` is the actor's, not the item's — an actor file is
    the binding unit (all of one agent's placements plus its coupled desk live
    in it), so every item flattened out of one actor carries the same value.
    It is NOT derivable client-side: an ``item_id`` such as
    ``personainst_qa_agent_9c8a382f`` is instance-SHAPED but is an item id, and
    reading it as a binding would invent an instance for a class-keyed actor.
    When this field was added every live actor was class-keyed, so it was
    ``null`` across the board and existed precisely so that stopped being
    invisible. The re-key migration has since landed: all eight live actors
    across both workspaces are instance-keyed and carry a populated value. The
    field is now the normal case, not the empty warning it was written as.

    Deliberately NOT carried, though the store holds them: the surface's
    ``archived_actor_keys`` (an append-only ledger capped at 5000 — the one
    genuinely unbounded field in this domain), and the actors' ``updated_by`` /
    ``created_at`` / ``state`` / ``backing_profile``. None of it is renderable
    and the first three are provenance for a different surface. Archived actors
    are excluded outright: ``scan_actors`` without ``include_archived`` is the
    placement set the canvas draws.

    Items are flattened out of their actor files in ``(actor_key, file order)``
    — ``scan_actors`` sorts by ``actor_key`` — so the same store state produces
    the same bytes on every call, which is what makes a caching client able to
    compare them.
    """

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        return workspace_id_required(rid)
    projection = _office_projection(workspace_id)
    if projection is None:
        # NOT an empty projection. `office show` answers an unauthored office
        # with an honest empty because a CLI reader is a human who can see the
        # zero; a program told `folders: [], items: []` cannot tell "this
        # workspace has no office yet" from "you asked for a workspace that
        # does not exist", and would render a blank canvas for a typo.
        return unknown_workspace(rid, workspace_id)
    return ok(rid, projection)


def _office_projection(workspace_id: str) -> dict | None:
    """The canvas projection for one workspace, or None when it does not exist.

    Extracted so ``runtime.office.subscribe``'s BASELINE is not a second
    derivation of the same thing. A subscribe whose baseline could disagree
    with a ``get`` would put the client back in the state this whole lane
    exists to end — two readers of one truth, differing silently.
    """

    from agent_runtime import paths  # noqa: F401 - store_root side of the read
    from agent_runtime.office_models import office_item_wire_row
    from agent_runtime.office_store import OfficeStore
    from agent_runtime.serde import to_jsonable
    from agent_runtime.office_models import MAX_OFFICE_ACTORS_PROJECTED

    store = OfficeStore()
    if not store.surface_exists(workspace_id):
        return None

    surface = store.get_surface(workspace_id)
    # The cut below is measured against the scan's OWN length, and
    # ``scan.unreadable`` rides the projection beside it: a list that had already
    # dropped its unreadable files made that subtraction answer 0 — a projection
    # shortened by the platform, describing itself as complete.
    scan = store.scan_actors(workspace_id)
    actors = scan.actors
    projected = actors[:MAX_OFFICE_ACTORS_PROJECTED]

    # The item shape lives in ``office_models`` and NOT here (plan S2). It is the
    # shape ``runtime.agent.create``'s ack now returns inside ``result.actor``,
    # and ``agent_create`` cannot import this module — that dependency is
    # inverted on purpose. Two copies of these ten keys is the
    # silent-disagreement shape ``_office_projection`` itself was extracted to
    # end, one level down.
    items = [
        office_item_wire_row(actor, item)
        for actor in projected
        for item in actor.items
    ]

    return {
        "workspace_id": surface.workspace_id,
        "folders": list(surface.folders),
        "revision": surface.revision,
        "updated_at": to_jsonable(surface.updated_at),
        "items": items,
        # Accounted, never silent. Zero on every real workspace today; a cut
        # that read as a smaller office would be indistinguishable from actors
        # having been removed.
        "actors_truncated": max(0, len(actors) - len(projected)),
        # The OTHER way this projection can be short, and the one it used to
        # hide completely: files that exist and would not decode. Its sibling
        # above counts a cut WE chose; this one counts rows the platform took.
        # Additive — an old launcher ignores the key — and it rides the shared
        # ``_office_projection``, so the subscribe baseline and ``get`` cannot
        # disagree about how complete the office they just handed over was.
        "actors_unreadable": scan.unreadable,
    }


@method("runtime.office.subscribe", tier=TIER_READ)
def _runtime_office_subscribe(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """The baseline AND the registration, in one call. The push leg's keystone.

    Params: ``workspace_id`` (required), ``fold_entities`` (optional list of
    strings — what THIS client can fold), ``reason`` (optional string — WHY this
    client is subscribing).

    Result: the SAME body ``runtime.office.get`` returns, plus ``watermark``
    ``{"event_offset": N}`` — the event-log offset the baseline was read at —
    ``fold_entities``, the accepted declaration echoed back, and ``replaced``,
    the re-baselining receipt described below. Subsequent
    ``runtime.office.patch`` notifications carry ``base_offset`` /
    ``watermark`` from the same counter, so the client's existing ``>``-only
    sequence gate applies unchanged and a gap is a gap on either lane.

    Rationale (5 sections) relocated verbatim to
    ``docs/agent-runtime-harness/history/serve_rpc.md`` § `runtime.office.subscribe` (rule 7).
    """

    from agent_runtime.locks import office_lock
    from agent_runtime.parity import events_watermark
    from agent_runtime.serve_office_subscriptions import (
        OFFICE_SUBSCRIPTIONS,
        event_offset_of,
        normalize_office_fold_entities,
        normalize_office_subscribe_reason,
    )

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        return workspace_id_required(rid)
    raw_fold_entities = params.get("fold_entities")
    fold_entities = (
        None if raw_fold_entities is None else normalize_office_fold_entities(raw_fold_entities)
    )
    if raw_fold_entities is not None and fold_entities is None:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: fold_entities must be a list of strings",
            {"reason": "fold_entities_invalid", "workspace_id": workspace_id},
        )
    # BEFORE the office lock, the projection and the hub — a param this method
    # only ever writes to a log must not be able to cost a producer restart on
    # its way to being refused.
    raw_reason = params.get("reason")
    subscribe_reason = (
        None if raw_reason is None else normalize_office_subscribe_reason(raw_reason)
    )
    if raw_reason is not None and subscribe_reason is None:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: reason must be <=64 chars of [a-z0-9_:.-]",
            {"reason": "reason_invalid", "workspace_id": workspace_id},
        )
    context = context or RpcContext()
    if context.emit is None:
        return err(
            rid,
            ERR_INVALID_REQUEST,
            "this transport cannot carry pushes; use runtime.office.get",
            {"reason": "push_channel_unavailable", "transport": context.transport},
        )

    with office_lock(workspace_id):
        projection = _office_projection(workspace_id)
        if projection is None:
            return unknown_workspace(rid, workspace_id)
        # ONE reader of the watermark, asked ONE question, through the same
        # helper the sink's baseline gate uses. ``int(… or 0)`` used to sit here
        # and answered a DIFFERENT question: it folded an unreadable log —
        # ``{"event_offset": None, "event_offset_error": ...}``, which
        # ``events_watermark`` documents as a routine outcome on this platform
        # under AV scanning — into offset 0, with no exception for the typed
        # ``except`` to catch and the error string discarded. A subscription
        # baselined at 0 has no gate at all, so the hub's mandatory hydrate came
        # back as a resync and the client re-subscribed, restarting the producer
        # for the whole room, forever.
        #
        # Cannot-read is now its own answer. No registration happens on this
        # path: the reply is a transient refusal beside the other two, and the
        # client's existing degrade ladder already holds this shape without
        # spinning.
        watermark = events_watermark()
        baseline_offset = event_offset_of(watermark)
        if baseline_offset is None:
            return _baseline_unavailable(rid, workspace_id, watermark)
        outcome = OFFICE_SUBSCRIPTIONS.subscribe(
            connection_key=context.connection_key,
            workspace_id=workspace_id,
            baseline_offset=baseline_offset,
            emit=context.emit,
            fold_entities=fold_entities,
            reason=subscribe_reason,
        )

    if not outcome.registered:
        return _push_lane_refusal(rid, workspace_id, outcome)
    return _subscribe_reply(rid, projection, baseline_offset, fold_entities, outcome)


def _baseline_unavailable(rid: Any, workspace_id: str, watermark: dict) -> dict:
    """The subscribe refusal when the event log's tail cannot be read (no registration)."""

    from agent_runtime.serve_office_subscriptions import (
        BASELINE_UNAVAILABLE,
        OFFICE_SUBSCRIPTIONS,
    )

    # The discarded half, kept: the reply cannot carry a platform error
    # string (a client has no use for one and it is not part of the
    # vocabulary), but an operator watching subscribes fail needs to
    # know WHY the log could not be read. Class only — the same
    # disclosure rule the rest of this runtime's receipts follow — and
    # the ``-`` sentinel rather than an absent key, because a field that
    # appears only sometimes is one a log reader stops looking for.
    raw_error = watermark.get("event_offset_error")
    error_class = (
        str(raw_error).split(":", 1)[0].strip() or "-"
        if isinstance(raw_error, str) and raw_error.strip()
        else "-"
    )
    log = OFFICE_SUBSCRIPTIONS.service_log()
    if log is not None:
        log(
            {
                "event": "serve_office_subscribe_refused",
                "reason": BASELINE_UNAVAILABLE,
                "workspace_id": workspace_id,
                "error": error_class,
            }
        )
    return err(
        rid,
        ERR_INVALID_REQUEST,
        "this runtime cannot read its event log's tail; subscribe again",
        {
            "reason": BASELINE_UNAVAILABLE,
            "workspace_id": workspace_id,
            # Shape parity with the registry's own refusals below: this
            # lane's clients branch on ``data.reason`` and decode the
            # rest, so a key that exists on two of three transient
            # refusals would have to be special-cased. Always False
            # here, and honestly so — the registry was never called, so
            # no prior subscription was displaced.
            "prior_subscription_released": False,
        },
    )


def _push_lane_refusal(rid: Any, workspace_id: str, outcome: Any) -> dict:
    """The subscribe refusal when the registry did not register (no hub / draining)."""

    from agent_runtime.serve_office_subscriptions import NO_PUSH_LANE, PUSH_LANE_DRAINING

    # The reason comes from the REGISTRY, not from a second guess here. The
    # old branch re-derived it by asking ``bound()``, which cannot separate
    # "no hub" from "a bound hub that is draining" — see the history doc.
    # Both share ``-32600`` on purpose: this lane's clients branch on
    # ``data.reason``, which is the whole reason ``data`` is populated at
    # all, and minting a code per transient state would make the numbers
    # the contract instead of the names.
    return err(
        rid,
        ERR_INVALID_REQUEST,
        "this runtime's push lane is draining; reconnect and subscribe again"
        if outcome.reason == PUSH_LANE_DRAINING
        else "this runtime has no push lane",
        {
            "reason": outcome.reason or NO_PUSH_LANE,
            "workspace_id": workspace_id,
            # Honest even on the failure path: a re-baseline that raced the
            # drain destroyed the caller's previous subscription before it
            # learned the new one would not be granted. Silence here would
            # leave the client believing its old lane survived.
            "prior_subscription_released": bool(outcome.replaced),
        },
    )


def _subscribe_reply(
    rid: Any,
    projection: dict,
    baseline_offset: int,
    fold_entities: Any,
    outcome: Any,
) -> dict:
    """The baseline plus the registration receipts: ``watermark``, ``fold_entities``, ``replaced``."""

    from agent_runtime.serve_office_subscriptions import OFFICE_FOLD_ENTITIES

    return ok(
        rid,
        {
            **projection,
            "watermark": {"event_offset": baseline_offset},
            # The declaration this subscription was actually registered with —
            # sorted so the answer is a value the client can compare, not an
            # iteration order. A client that declared nothing sees the legacy
            # constant here, which is how it learns what it is being held to
            # without having to know the server's defaults.
            "fold_entities": sorted(
                fold_entities if fold_entities is not None else OFFICE_FOLD_ENTITIES
            ),
            # Always present, never omitted on the False case — the same rule
            # the projection's own nullable keys follow. A client decoding into
            # a typed struct must not have to special-case which keys exist,
            # and a receipt that appears only sometimes is one a client learns
            # to stop reading.
            "replaced": bool(outcome.replaced),
        },
    )


@method("runtime.office.unsubscribe", tier=TIER_READ)
def _runtime_office_unsubscribe(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """Hand ONE workspace's push subscription back, keeping the connection.

    Params: ``workspace_id`` (required).
    Result: ``{"workspace_id": ..., "released": bool}``.

    Why the method exists at all
    ----------------------------
    ``runtime.office.subscribe`` registers and answers together, so a
    subscription outlives the client's decision about the reply that created it.
    Re-baselining covers the client that wants a BETTER baseline; this covers
    the one that wants none — it navigated away from the workspace, or it gave
    up. Before this, the only release was closing the socket, which also took
    every unrelated call riding it. A subscriber the runtime could not reclaim
    keeps a producer rebuilding projections for nobody.

    Why an unknown subscription is an ANSWER and not an error
    ---------------------------------------------------------
    ``released: false`` is the honest report that nothing was live under this
    key, and it is deliberately a result rather than a 4001. Releasing something
    already released is exactly what a recovering client does: it lost track of
    whether its subscribe landed, and asking is how it finds out. An error there
    would make ordinary recovery indistinguishable from a fault, and a client
    that cannot tell those apart either logs noise forever or stops looking.

    Deliberately NOT here
    ---------------------
    No ``office_lock``, and no existence check on the workspace. There is no
    baseline to pair a read with, so the lock would buy nothing and could only
    make a release wait behind a write. And a client must still be able to
    release a workspace that has since been deleted — refusing there would
    strand the subscription for good, which is the very failure being closed.

    No ``push_channel_unavailable`` either. Subscribe needs an emitter because
    it registers one; this only names a key, and a caller with no push channel
    has no subscription to release — which ``released: false`` already says.
    """

    from agent_runtime.serve_office_subscriptions import OFFICE_SUBSCRIPTIONS

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        # A caller BUG, unlike everything else this method tolerates: there is
        # no key to name, so there is nothing to answer False about.
        return workspace_id_required(rid)
    context = context or RpcContext()

    released = OFFICE_SUBSCRIPTIONS.release_one(
        context.connection_key, workspace_id
    )
    return ok(rid, {"workspace_id": workspace_id, "released": bool(released)})
