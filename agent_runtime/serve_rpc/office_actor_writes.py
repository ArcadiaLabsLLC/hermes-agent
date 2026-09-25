"""``runtime.office.upsert`` / ``remove`` — the two actor-row writes (the
prediction/reconciliation leg described in ``protocol``'s docstring).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE

from agent_runtime.serve_rpc.protocol import (
    ERR_CONFLICT,
    ERR_INVALID_PARAMS,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    RpcContext,
    err,
    ok,
)
from agent_runtime.serve_rpc.registry import method
from agent_runtime.serve_rpc.params import (
    CORRELATION_ID_INVALID_REASON,
    _CorrelationIdRefused,
    _correlation_id_param,
    _workspace_id_param,
)
from agent_runtime.serve_rpc.office_read import log_office_write

__layer__ = "lanes"

__all__ = [
    "_runtime_office_remove",
    "_runtime_office_upsert",
]


@method("runtime.office.upsert", tier=TIER_CONSOLE)
def _runtime_office_upsert(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """ONE actor placement, written — and acked LIGHT so a drag can predict.

    Params: ``workspace_id`` (required), ``actor`` (required object — the same
    identity-triple-plus-items payload ``harness office actor-upsert`` takes on
    ``--actor-json``, deliberately not a second schema), ``expect_revision``
    (optional int) and ``updated_by`` (optional string, defaults to the argv
    lane's own ``operator``).

    Result: ``{"actor_key", "revision"}``, plus ``correlation_id`` echoed back
    when the caller sent one. See the module docstring for why the ack is those
    two facts and not the actor.

    ``correlation_id`` (optional string, EG-2.3) is the CALLER's gesture token:
    a generated ``[A-Za-z0-9_.:-]`` id of at most 64 characters, minted once per
    operator gesture and threaded into every event this write appends, so the
    launcher receipt and the serve-child ``office_write`` line join on one grep
    instead of on timestamps. Absent is normal and keeps every payload
    byte-identical; present-but-illegal is REFUSED
    (``data.reason: correlation_id_invalid``) rather than sanitized. It is NOT
    the idempotency key (a replay reuses that by design) and NOT ``issued_at``
    (an ordering basis); a retry of the same gesture carries the SAME token,
    which is the truth and is what makes a retry visible as two receipts under
    one id.

    Why this method REFUSES an unknown workspace instead of authoring one
    ---------------------------------------------------------------------
    ``OfficeStore.upsert_actor`` calls ``ensure_surface``, which used to lazily
    create the office for ANY id. This lane's caller is the same program that
    just called ``runtime.office.get``, which REFUSES an unknown workspace so a
    typo cannot render as a blank canvas. A pair where the read refuses a typo
    and the write silently authors a whole new office for it is incoherent, and
    the write side is the worse half — a mis-rendered canvas is repainted on the
    next poll, a mis-authored one is on disk forever. So the existence check
    happens HERE, before the store's own create.

    **Amended MC-8 / P10.** This paragraph used to continue "…which is right for
    the CLI: a human typed ``--workspace`` and can see what they made", leaving
    the surface-authoring path on the argv lane. That reasoning is retired: the
    lazy create is how a leaked test context minted a LIVE office for a workspace
    that never existed, so ``ensure_surface`` now refuses typed
    (``WorkspaceUnresolved``) on every lane when no workspace RECORD resolves the
    id. The two guards ask different questions and both still earn their place —
    this one asks whether a SURFACE exists, so an unknown workspace reads as
    ``workspace_not_found`` rather than as an empty office; the store's asks
    whether a workspace RECORD does. Because this check runs first and refuses
    whenever the surface is absent, ``WorkspaceUnresolved`` is NOT REACHABLE
    through this arm. A handler for it here would be a catch that can never fire,
    so there deliberately is none.

    The desk fence is GONE (2026-09-18, owner ruling)
    -------------------------------------------------
    This handler used to carry a third translation arm: ``DuplicateDeskRefused``
    into a 4090 with ``data.reason = "duplicate_desk"``. The store fence behind
    it (D6, one live desk per persona per level) was deleted with the invariant
    it enforced — a desk is furniture addressed by its own synthetic id, so a
    second desk in a workspace is the normal shape rather than the refused one.
    Nothing replaced the arm: a desk write now succeeds, and this lane is one
    reason string shorter. ``RPC_CONTRACT_VERSION`` did not move — a reason a
    server can no longer emit is not a contract a client has to be told about,
    and every other reason on this method is unchanged.

    Concurrency is the store's, not a second scheme
    -----------------------------------------------
    ``expect_revision`` and the realm-sync conflict guard are passed straight
    through to ``upsert_actor``; both refusals arrive as typed exceptions and
    are translated, never re-implemented. Note what ``expect_revision`` can and
    cannot express: ``_check_revision`` compares against ``None`` for an actor
    that does not exist yet, so EVERY value — including ``0`` — refuses a
    create. A create is therefore necessarily unguarded, and a client must send
    ``expect_revision`` only for a placement it has already seen.

    The class-key fence, and why it has NO override here
    ----------------------------------------------------
    The fence is the STORE's (``OfficeStore._guard_class_keyed_write``, hoisted
    there by EG-6.6) for the reason ``office_class_key_guard`` gives:
    ``upsert_actor`` reads an explicit upsert of an ARCHIVED key as operator
    intent to re-add and clears the resurrection ledger, so one surviving
    class-keyed write undoes the class→instance re-key and places the same agent
    twice. What this handler keeps is the TRANSLATION — a 4090 whose
    ``data.reason`` is ``class_key_collision`` and whose message names the exit
    this lane actually has. It holds no copy of the predicate; deleting the
    store's fence does not leave this lane guarded.

    The CLI verb beside it passes ``allow_class_key=True`` to the store on
    ``--allow-class-key``. This one never passes it, and that asymmetry is the
    point rather than an omission. The
    flag is consent: an operator read the refusal, typed the override, and owns
    the double placement. A wire PARAMETER is not consent — it is a constant in
    a client build, set once by whoever was debugging the day drags started
    failing, and thereafter sent by every install on every write with no human
    in any loop. And the wire client needs it least: the read projection hands
    it ``persona_instance_id`` on every item, so its remedy is to send back the
    binding it was already given. The genuine operator-intent paths are
    untouched — ``harness office actor-restore``, and the CLI's own override.
    """

    from agent_runtime.errors import (
        ActorArchived,
        ArchiveUnreadable,
        StaleRevision,
        SyncConflict,
    )
    from agent_runtime.office_class_key_guard import ClassKeyedPlacementRefused
    from agent_runtime.office_store import OfficeStore

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        # The same reason string the read leg spends, on purpose: one client
        # branch covers "the launcher forgot the workspace" on either lane.
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: workspace_id must be a non-empty string",
            {"reason": "workspace_id_required"},
        )

    actor_payload = params.get("actor")
    if not isinstance(actor_payload, dict):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: actor must be an object",
            {"reason": "actor_required"},
        )

    expect_revision = params.get("expect_revision")
    # ``bool`` is an ``int`` in Python and ``True`` would silently mean revision
    # 1 — a wrong guard is worse than no guard, so the type check is explicit.
    if expect_revision is not None and (
        isinstance(expect_revision, bool) or not isinstance(expect_revision, int)
    ):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: expect_revision must be an integer or omitted",
            {"reason": "expect_revision_invalid"},
        )

    updated_by = params.get("updated_by")
    if updated_by is not None and not isinstance(updated_by, str):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: updated_by must be a string or omitted",
            {"reason": "updated_by_invalid"},
        )

    try:
        correlation_id = _correlation_id_param(params)
    except _CorrelationIdRefused as refused:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            refused.message,
            {"reason": CORRELATION_ID_INVALID_REASON, "workspace_id": workspace_id},
        )

    store = OfficeStore()
    if not store.surface_exists(workspace_id):
        return err(
            rid,
            ERR_NOT_FOUND,
            f"unknown workspace: {workspace_id}",
            {"reason": "workspace_not_found", "workspace_id": workspace_id},
        )

    try:
        actor = store.upsert_actor(
            workspace_id,
            actor_payload,
            updated_by=updated_by or "operator",
            expect_revision=expect_revision,
            correlation_id=correlation_id,
        )
    except ClassKeyedPlacementRefused as exc:
        # The store's fence, translated. Its own reason: the remedy is neither
        # "refetch and rebase" nor "fix the payload shape" — the payload is
        # well-formed and the client is not behind. It is "name WHICH instance
        # you are placing". The guard's two narrow reasons ride beside it as a
        # list rather than as the branch point, because they share that one
        # remedy and because a client decoder switches on a single stable string.
        #
        # ``str(exc)`` — the shared ``refusal_message`` — is deliberately NOT
        # reused: it ends by offering ``--allow-class-key``, which is a CLI flag
        # that does not exist on this lane. Advice a caller cannot follow is
        # worse than none. So the SENTENCE is this lane's and the FACTS are the
        # store's, read off ``safe_details`` (the collision dict verbatim) rather
        # than recomputed — recomputing them here is the second copy EG-6.6
        # removed.
        collision = exc.safe_details
        return err(
            rid,
            ERR_CONFLICT,
            (
                f"class-keyed write for persona {collision['persona_id']!r} refused: "
                f"{', '.join(collision['reasons'])}"
                # Named when there is one. The two reasons fire on different
                # evidence — a ledger entry vs. a live sibling — and only the
                # second has another actor to point at.
                + (
                    f" (conflicts with {', '.join(collision['conflicting_actor_keys'])})"
                    if collision["conflicting_actor_keys"]
                    else ""
                )
                + ". The class→instance re-key archived this class key; writing it "
                "back undoes that migration. Send persona_instance_id to place a "
                "specific instance."
            ),
            {
                "reason": "class_key_collision",
                "workspace_id": workspace_id,
                "persona_id": collision["persona_id"],
                "class_actor_key": collision["class_actor_key"],
                "reasons": collision["reasons"],
                "conflicting_actor_keys": collision["conflicting_actor_keys"],
            },
        )
    except ActorArchived as exc:
        # The tombstone fence (D1), translated. A 4090 because a guard refused
        # this write, and a FOURTH reason on that code because the cure is a
        # fourth thing again: not "refetch and rebase", not "name the instance",
        # not "an operator must resolve a sidecar" — it is DROP THE LOCAL ROW.
        # This is the live-incident lane. The launcher that re-pushed archived
        # actors nineteen seconds after boot was not sending a malformed or
        # stale payload; it was sending a well-formed write for a row that no
        # longer exists on the authority, and every retryable reason would have
        # spun it. A client must not re-place this key: re-placing is a NEW
        # create with a freshly minted id.
        #
        # No ``resurrect`` parameter on this lane, for the reason spelled out
        # above about ``allow_class_key``: a wire parameter is not consent. The
        # deliberate re-add doors stay where they are — ``harness office
        # actor-restore`` and the CLI's own ``--resurrect``.
        details = exc.safe_details
        return err(
            rid,
            ERR_CONFLICT,
            (
                f"actor {details['actor_key']!r} was deleted on this server. "
                "Drop the local row; re-placing this agent is a new create with "
                "a new id, not a re-add of this key."
            ),
            {
                "reason": "actor_archived",
                "workspace_id": workspace_id,
                "actor_key": details["actor_key"],
                "persona_instance_id": details["persona_instance_id"],
            },
        )
    except StaleRevision as exc:
        # The prediction is behind. ``data`` deliberately does NOT carry the
        # current revision: the prescribed cure is to refetch and rebase onto
        # server truth, and handing back a bare integer invites a retry with it
        # — which is the lost update this guard exists to refuse. The number is
        # in ``message``, where an operator can read it and a client should not.
        return err(
            rid,
            ERR_CONFLICT,
            str(exc),
            {
                "reason": "stale_revision",
                "workspace_id": workspace_id,
                "expect_revision": expect_revision,
            },
        )
    except SyncConflict as exc:
        # A different refusal with a different cure — an unresolved realm-sync
        # sidecar. Retrying never clears it; an operator resolving it does.
        return err(
            rid,
            ERR_CONFLICT,
            str(exc),
            {"reason": "sync_conflict", "workspace_id": workspace_id},
        )
    except ArchiveUnreadable as exc:
        # The archived copy of this key exists and would not decode, so the
        # revision this write must bump is unknown. NOT a 4090: no guard refused
        # anything and there is no prediction to rebase — the store declined to
        # invent a base. ``-32600`` is the band this runtime already spends on
        # "cannot serve this right now" with ``data.reason`` as the branch
        # (``baseline_unavailable`` on the subscribe lane), and the cure is the
        # same shape: ask again once the file is readable, or have an operator
        # repair/remove the archive copy. Retrying is safe and may well work —
        # an AV hold is transient — but the client must not paper over it by
        # writing UNGUARDED, which is what a revision of 1 would have invited.
        #
        # ``exc.code``, not the class constant: ``ActorsUnreadable`` subclasses
        # this so it inherits the band and the cure SHAPE (EG-6.6 — the class-key
        # fence refusing rather than answering "no conflict" from a directory it
        # could only partly read), and its own code names the different FILE the
        # operator has to repair. A hard-coded constant here would have told them
        # to go fix the archive copy.
        return err(
            rid,
            ERR_INVALID_REQUEST,
            str(exc),
            {
                "reason": exc.code,
                "workspace_id": workspace_id,
            },
        )
    except ValueError as exc:
        # Every ``invalid_request: …`` the store raises while normalizing the
        # payload — a missing persona_id, an unparseable position, a
        # secret-shaped display name. One reason, because the client's response
        # to all of them is identical: fix the payload, it is a launcher bug.
        # The store's own sentence rides ``message`` so the dev knows which.
        return err(
            rid,
            ERR_INVALID_PARAMS,
            str(exc),
            {"reason": "actor_invalid", "workspace_id": workspace_id},
        )

    log_office_write(
        op="runtime.office.upsert",
        correlation_id=correlation_id,
        workspace=workspace_id,
        actor_key=actor.actor_key,
        revision=actor.revision,
    )
    # Light, and both fields are things the caller could not have computed.
    # ``correlation_id`` rides only when the caller sent one — the ECHO is what
    # lets the launcher's reply receipt name the token without trusting its own
    # memory of what it sent, and its absence keeps every pre-EG-2.3 reply
    # byte-identical.
    result: dict[str, Any] = {"actor_key": actor.actor_key, "revision": actor.revision}
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)


@method("runtime.office.remove", tier=TIER_CONSOLE)
def _runtime_office_remove(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """ONE actor placement, ARCHIVED — the delete gesture's write leg.

    Params: ``workspace_id`` (required), ``actor_key`` (required string),
    ``expect_revision`` (optional int), ``updated_by`` and ``reason`` (optional
    strings, both defaulting to the argv lane's own ``operator``), and
    ``correlation_id`` (optional gesture token — see ``runtime.office.upsert``).

    Result: ``{"actor_key", "revision", "state"}`` — the store's POST-archive
    revision, not the one the caller was holding. ``_archive_actor_locked``
    bumps the number on its way out and an archived key carries it forward
    through a restore, so the +1 is the token a later guarded write on this key
    must present. Returning the pre-archive number would hand the client a
    guard token that is already one behind.

    ``state`` is on the ack even though it is a constant. The alternative reads
    ``{actor_key, revision}`` exactly like the upsert's ack and means the
    opposite thing, and a client decoder that crossed the two would settle a
    deletion with a placement's ack. One word makes the two frames
    self-describing.

    Why this REFUSES an unknown workspace before the store
    ------------------------------------------------------
    Same ruling as ``runtime.office.upsert``'s, reached from the other side.
    ``remove_actor`` on an unauthored workspace raises ``NotFound`` about the
    ACTOR — which is true but useless, because it names the wrong thing: the
    client's cure for "this workspace has no office" is not "resend a different
    key". Checking ``surface_exists`` first means the read leg and both write
    legs spend one reason string on one condition, and a typo answers the same
    way whichever verb hit it.

    Why an already-archived key is an OK and not a 4001
    ---------------------------------------------------
    ``OfficeStore.remove_actor`` is idempotent on purpose: an already-archived
    key returns the archived copy and writes nothing. That is the honest answer
    for this lane too. The launcher's flush re-names a key it has already
    deleted whenever a later save recomputes the same vacated set, and turning
    the second attempt into an error would make an operator's single deletion
    report a failure it did not have — with a rollback behind it that puts the
    actor back on the canvas. Nothing was written either way; the state the
    caller asked for is the state the store is in.

    NO class-key fence, and that is not an omission
    -----------------------------------------------
    ``office_class_key_guard`` exists because an upsert of an archived key is
    read as intent to RE-ADD and clears the resurrection ledger. An archive
    moves in the other direction — it cannot resurrect anything, and a
    class-keyed archive is the class→instance migration's own mechanism rather
    than a write that undoes it.
    """

    from agent_runtime.errors import ArchiveUnreadable, NotFound, StaleRevision
    from agent_runtime.office_store import OfficeStore

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        # The same reason string every office method spends on this, on
        # purpose: one client branch covers it whatever the verb was.
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: workspace_id must be a non-empty string",
            {"reason": "workspace_id_required"},
        )

    raw_key = params.get("actor_key")
    actor_key = raw_key.strip() if isinstance(raw_key, str) else ""
    if not actor_key:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: actor_key must be a non-empty string",
            {"reason": "actor_key_required"},
        )

    expect_revision = params.get("expect_revision")
    # ``bool`` is an ``int`` in Python and ``True`` would silently mean revision
    # 1 — a wrong guard is worse than no guard, so the type check is explicit.
    if expect_revision is not None and (
        isinstance(expect_revision, bool) or not isinstance(expect_revision, int)
    ):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: expect_revision must be an integer or omitted",
            {"reason": "expect_revision_invalid"},
        )

    updated_by = params.get("updated_by")
    if updated_by is not None and not isinstance(updated_by, str):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: updated_by must be a string or omitted",
            {"reason": "updated_by_invalid"},
        )

    reason = params.get("reason")
    if reason is not None and not isinstance(reason, str):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: reason must be a string or omitted",
            {"reason": "reason_invalid"},
        )

    try:
        correlation_id = _correlation_id_param(params)
    except _CorrelationIdRefused as refused:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            refused.message,
            {"reason": CORRELATION_ID_INVALID_REASON, "workspace_id": workspace_id},
        )

    store = OfficeStore()
    if not store.surface_exists(workspace_id):
        return err(
            rid,
            ERR_NOT_FOUND,
            f"unknown workspace: {workspace_id}",
            {"reason": "workspace_not_found", "workspace_id": workspace_id},
        )

    try:
        actor = store.remove_actor(
            workspace_id,
            actor_key,
            reason=reason or "operator",
            updated_by=updated_by or "operator",
            expect_revision=expect_revision,
            correlation_id=correlation_id,
        )
    except NotFound:
        # Its OWN reason, distinct from ``workspace_not_found``: the office is
        # there and this key is not in it, which is a different client story
        # (a stale key, or a key the store canonicalized differently) with a
        # different cure (refetch the projection, not re-author the office).
        return err(
            rid,
            ERR_NOT_FOUND,
            f"unknown actor: {actor_key}",
            {
                "reason": "actor_not_found",
                "workspace_id": workspace_id,
                "actor_key": actor_key,
            },
        )
    except StaleRevision as exc:
        # ``data`` deliberately carries NO current revision — the same rule the
        # upsert follows, and for the same reason: handing back the number
        # invites a retry with it, which is the lost update the guard refused.
        return err(
            rid,
            ERR_CONFLICT,
            str(exc),
            {
                "reason": "stale_revision",
                "workspace_id": workspace_id,
                "actor_key": actor_key,
                "expect_revision": expect_revision,
            },
        )
    except ArchiveUnreadable as exc:
        # The already-archived (idempotent) branch: this key's archive copy is
        # the only place its post-archive revision lives, and this ack CARRIES
        # that revision as the token a later guarded write must present. A decode
        # failure there is the token going missing, so the refusal is typed with
        # the same reason the upsert leg spends — one string per condition, not
        # one per verb.
        #
        # What it replaced was worse than an untyped crash: ``JSONDecodeError``
        # is a ``ValueError``, so the bare read fell into the ``actor_invalid``
        # arm below and told the client to FIX ITS PAYLOAD for a corrupt file on
        # the server. The mutation test for this arm still shows ``-32602``.
        return err(
            rid,
            ERR_INVALID_REQUEST,
            str(exc),
            {
                "reason": ArchiveUnreadable.code,
                "workspace_id": workspace_id,
                "actor_key": actor_key,
            },
        )
    except ValueError as exc:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            str(exc),
            {"reason": "actor_invalid", "workspace_id": workspace_id},
        )

    log_office_write(
        op="runtime.office.remove",
        correlation_id=correlation_id,
        workspace=workspace_id,
        actor_key=actor.actor_key,
        revision=actor.revision,
        state=actor.state,
    )
    result: dict[str, Any] = {
        "actor_key": actor.actor_key,
        "revision": actor.revision,
        "state": actor.state,
    }
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)
