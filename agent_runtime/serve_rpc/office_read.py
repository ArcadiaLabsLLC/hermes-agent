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
    ERR_NOT_FOUND,
    RpcContext,
    err,
    logger,
    ok,
)
from agent_runtime.serve_rpc.registry import method
from agent_runtime.serve_rpc.params import _workspace_id_param

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
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: workspace_id must be a non-empty string",
            {"reason": "workspace_id_required"},
        )
    projection = _office_projection(workspace_id)
    if projection is None:
        # NOT an empty projection. `office show` answers an unauthored office
        # with an honest empty because a CLI reader is a human who can see the
        # zero; a program told `folders: [], items: []` cannot tell "this
        # workspace has no office yet" from "you asked for a workspace that
        # does not exist", and would render a blank canvas for a typo.
        return err(
            rid,
            ERR_NOT_FOUND,
            f"unknown workspace: {workspace_id}",
            {"reason": "workspace_not_found", "workspace_id": workspace_id},
        )
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
    from agent_runtime.snapshot import MAX_OFFICE_ACTORS_PROJECTED

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

    Why one call and not two
    ------------------------
    A ``get`` followed by a separate join is two reads of one truth with a
    window between them, and nothing tells the client whether anything moved
    inside that window. Taking the projection and the offset together — and
    registering with the same value — is what makes "I have the office as of N,
    push me everything after N" a statement the runtime can honour rather than
    a hope. The office lock is held across the pair so a write cannot land
    between them.

    The ordering seam, stated rather than papered over
    --------------------------------------------------
    The dispatcher emits this reply AFTER the handler returns, so a patch
    published in between reaches the client BEFORE the baseline it rebases on.
    That is not fixed by a server-side buffer; it is fixed by the sink dropping
    any frame at or below ``event_offset``, which is the same rule that absorbs
    the hub's mandatory re-hydrate. See ``serve_office_subscriptions``.

    A second subscribe RE-BASELINES, and says so
    --------------------------------------------
    Registering and answering together has a consequence the first cut did not
    follow through on: the subscription exists before the client has finished
    reading the reply. A client that finds the baseline unusable is right to
    refuse it — folding a knowingly-partial office would render it as
    authoritative — but the old ``already_subscribed`` refusal then left a live
    subscription the client would never fold against, reclaimable only by
    dropping the connection. There is no method that could have released it.

    So a repeat subscribe for this ``(connection, workspace)`` replaces the
    registration with a fresh baseline and watermark, and the stuck state stops
    existing by construction. The refusal it retires was only ever there to stop
    a subscriber leaking per retry; one key still means one subscription, so
    nothing leaks either way, and replacement is the answer that gets a confused
    client out of the hole rather than deeper into it.

    ``replaced`` on the result is the bill. ``StreamHub.subscribe`` restarts the
    producer, so a re-baseline costs every OTHER subscriber on that hub a fresh
    full core — a cost the old refusal did not incur, because a duplicate key
    was declined before a generation was ever bumped. A client that sees
    ``replaced: true`` on a call it thought was its first has learned something
    true about its own state, and the same event is written to the service log
    for the operator (``serve_office_subscription_rebaselined``). Silent
    re-baselining would let a retry loop tax the whole room invisibly.

    Refusals are typed because their cures differ:

    ``push_channel_unavailable``
        This caller has no push channel — a stdio probe, a test double. The
        method refuses rather than registering into a void, which is the whole
        reason ``RpcContext.emit`` is allowed to be ``None``.
    ``push_lane_unavailable``
        The runtime has no stream hub bound — no socket lane, or a serve loop
        that has not reached its bind yet. Nothing the client can do about the
        first; the second is a startup window ``serve.py`` announces ``ready``
        several hundred lines before closing, and it is a separate bug.
    ``push_lane_draining``
        A hub IS bound and it refused: it is stopping, so this call raced
        ``_close_socket_lane``. Transient, and the cure is to reconnect — which
        is precisely why it must not share a name with the case above. When the
        caller held a subscription, ``data.prior_subscription_released`` says
        so: the re-baseline's teardown already ran, so the old lane is gone too.
    ``baseline_unavailable``
        The event log's tail could not be read, so there is no offset to
        baseline at. Transient like the case above, and the reason this method
        no longer answers an unreadable log with ``0`` — see the refusal at the
        watermark read for what a fabricated baseline costs the whole room.

    ``already_subscribed`` is GONE. It was the only ``ERR_CONFLICT`` this method
    raised, and its disappearance also retires a mislabel that shipped with it:
    the old branch chose its reason by asking ``bound()``, which answers True
    for a bound-but-draining hub as readily as for a live one. A client racing
    the drain was therefore told "already subscribed to this workspace" while
    holding no subscription at all — sent to the one cure (stop retrying) that
    could not work. Splitting the two reasons is what keeps replacement from
    quietly inheriting that lie under a new name.

    ``fold_entities``: what THIS client can fold, not what an office subscriber
    can fold in general
    ---------------------------------------------------------------------------
    The declaration used to be a SERVER-side constant
    (``OFFICE_FOLD_ENTITIES``), which is a shape that can only ever report a
    fact about the runtime — and that is the hole the 2026-08-16 capability
    token exposed (plan §V4). Promotion is negotiated over the room, so a
    launcher whose fold had been widened could never have its widened rows
    promoted on this lane: the intersection cannot contain a token nobody told
    the server about.

    So the param is optional and FAIL-OPEN. Absent → the legacy constant, i.e.
    today's wire for every client in the field, byte-identical. Present → this
    subscription declares exactly what it says, unknown members included (the
    channel has never interpreted its strings, and a server that filtered to a
    known vocabulary would drop the NEXT token the same way). An explicitly
    EMPTY list is honoured as empty — "I fold nothing, send me full cores" is a
    thing a client is allowed to say and must stay distinguishable from silence.
    A non-list is refused rather than guessed: a client sending the wrong shape
    should learn it, not be quietly filed as legacy.

    The accepted set is ECHOED on the reply, under the same always-present rule
    the other keys follow. Without it a client cannot tell a declaration that
    was honoured from one the runtime is too old to have read — and this whole
    method exists because a push that arrives and is silently dropped is the
    failure this lane keeps paying for.

    ``reason``: the client's own resubscribe cause, so the server log can join
    the ladder
    ---------------------------------------------------------------------------
    Every re-subscribe in the launcher flows through ONE door and already
    carries an exact cause string (``start``, ``fold:fenced``,
    ``push:full_core``, ``reconnect``, ``deferred:*``, ``fold_threw``) — and
    that string used to die in the launcher's log. The server saw a re-baseline
    with no way to tell a fold-fence storm from a demote storm, so separating
    the two classes meant joining two logs on timestamps: inference, on the same
    shape that has already misattributed this lane once.

    So the param is optional, additive and INERT. It decides nothing: it is
    stamped verbatim on the ``serve_office_subscription_rebaselined`` receipt
    and read nowhere else. A cause the client chose is evidence, never
    authority — a server that branched on it would be taking dispatch orders
    from an untrusted string.

    Boundary-validated rather than echoed raw, because it is written to an
    operator's log: ≤64 chars over ``[a-z0-9_:.-]``, refused ``-32602`` with
    ``{"reason": "reason_invalid"}`` otherwise, and refused BEFORE any store or
    hub call so a bad param cannot cost a projection, a lock, or a producer
    restart. See ``normalize_office_subscribe_reason`` for why a blank is a
    refusal rather than an absence.

    Absent — every client in the field today — prints
    ``SUBSCRIBE_REASON_ABSENT`` (``-``) on the receipt, so silence is visible as
    a value rather than as a missing key.
    """

    from agent_runtime.locks import office_lock
    from agent_runtime.parity import events_watermark
    from agent_runtime.serve_office_subscriptions import (
        BASELINE_UNAVAILABLE,
        NO_PUSH_LANE,
        OFFICE_FOLD_ENTITIES,
        OFFICE_SUBSCRIPTIONS,
        PUSH_LANE_DRAINING,
        event_offset_of,
        normalize_office_fold_entities,
        normalize_office_subscribe_reason,
    )

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: workspace_id must be a non-empty string",
            {"reason": "workspace_id_required"},
        )
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
            return err(
                rid,
                ERR_NOT_FOUND,
                f"unknown workspace: {workspace_id}",
                {"reason": "workspace_not_found", "workspace_id": workspace_id},
            )
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
        outcome = OFFICE_SUBSCRIPTIONS.subscribe(
            connection_key=context.connection_key,
            workspace_id=workspace_id,
            baseline_offset=baseline_offset,
            emit=context.emit,
            fold_entities=fold_entities,
            reason=subscribe_reason,
        )

    if not outcome.registered:
        # The reason comes from the REGISTRY, not from a second guess here. The
        # old branch re-derived it by asking ``bound()``, which cannot separate
        # "no hub" from "a bound hub that is draining" — see the docstring.
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
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: workspace_id must be a non-empty string",
            {"reason": "workspace_id_required"},
        )
    context = context or RpcContext()

    released = OFFICE_SUBSCRIPTIONS.release_one(
        context.connection_key, workspace_id
    )
    return ok(rid, {"workspace_id": workspace_id, "released": bool(released)})
