"""``runtime.office.surface_update`` / ``resolve_conflict`` — the two
surface-level office writes.
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
    "_runtime_office_resolve_conflict",
    "_runtime_office_surface_update",
]


@method("runtime.office.surface.update", tier=TIER_CONSOLE)
def _runtime_office_surface_update(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """The FOLDER TAXONOMY of one office surface, rewritten.

    Params: ``workspace_id`` (required), ``folders`` (required list of strings),
    ``expect_revision`` (optional int), ``updated_by`` (optional string,
    defaulting to the argv lane's own ``operator``), and ``correlation_id``
    (optional gesture token — see ``runtime.office.upsert``).

    Result: ``{"workspace_id", "folders", "revision"}`` — the folder list AS THE
    STORE NORMALIZED IT, and the post-write surface revision.

    ``folders`` is a LIST on this lane, deliberately
    -----------------------------------------------
    The capability lane joins the folders with commas onto one argv string
    because argv has no other shape. That encoding is an ARGV ARTIFACT and it is
    lossy in a way nobody has tripped over yet only because folder names happen
    not to contain commas — ``_safe_folder`` collapses whitespace and truncates
    at 80 chars but keeps every comma it is given, so ``"Design, Ops"`` splits
    into two folders on the way through. A typed lane must not copy an
    encoding's accidents, so the list stays a list and
    ``OfficeStore.update_surface`` receives exactly what the operator arranged.

    Why the ECHO is the load-bearing half of the reply
    --------------------------------------------------
    ``_normalize_folders`` is not identity: it always prepends
    ``DEFAULT_FOLDERS``, drops duplicates and blanks, and stops at
    ``MAX_FOLDERS``. The launcher's flush has, until this method existed, copied
    its OWN desired list into ``serverFolders`` on accept — so any normalization
    difference left the two permanently disagreeing and the folder branch
    re-firing on every subsequent flush, one write per flush forever. Echoing
    the store's canonical list is what closes that loop, which is why the reply
    carries the whole list rather than the light ``{revision}`` ack the actor
    verbs answer with. It is small by construction (≤64 names ≤80 chars).

    Why this REFUSES an unknown workspace instead of authoring one
    --------------------------------------------------------------
    Same ruling as ``runtime.office.upsert``'s, and it bites harder here.
    ``update_surface`` calls ``ensure_surface`` unconditionally on its non-dry
    path, so on this lane a typo'd ``workspace_id`` would not merely write to
    the wrong place — it would AUTHOR a whole office, emit
    ``office.surface.created``, and leave it on disk forever, while the read leg
    (``runtime.office.get``) answers the same typo with ``workspace_not_found``.
    A pair where the read refuses what the write invents is incoherent, and the
    write is the worse half. The lazy-create path stays where a human can see
    what they made: the argv lane.

    No class-key fence and no reservation, for the same reasons the archive
    records: this moves no actor rows, and it is one store call under one
    ``office_lock`` guarded by ``expect_revision``, so a transport retry
    converges.
    """

    from agent_runtime.errors import StaleRevision
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

    folders = params.get("folders")
    # Checked HERE rather than left to the store, because the store does not
    # refuse: ``_normalize_folders`` answers a non-list with the DEFAULT list,
    # so a client that sent a string would silently have its taxonomy reset to
    # ``("Agents", "Desks")`` and be acked. A per-element string check rides the
    # same reason: ``_safe_folder`` stringifies whatever it is handed, so a
    # number would be written as ``"3"`` and echoed back as a folder the
    # operator never named.
    if not isinstance(folders, list) or not all(
        isinstance(name, str) for name in folders
    ):
        return err(
            rid,
            ERR_INVALID_PARAMS,
            "invalid params: folders must be a list of strings",
            {"reason": "folders_invalid", "workspace_id": workspace_id},
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
        surface = store.update_surface(
            workspace_id,
            folders=folders,
            updated_by=updated_by or "operator",
            expect_revision=expect_revision,
            correlation_id=correlation_id,
        )
    except StaleRevision as exc:
        # ``data`` deliberately carries NO current revision — the same rule both
        # actor verbs follow, and for the same reason: handing back the number
        # invites a retry with it, which is the lost update the guard refused.
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
    except ValueError as exc:
        # The store's own ``invalid_request`` sentence rides ``message``; one
        # reason, because the client's response to every one of them is the
        # same — fix the payload, it is a launcher bug.
        return err(
            rid,
            ERR_INVALID_PARAMS,
            str(exc),
            {"reason": "folders_invalid", "workspace_id": workspace_id},
        )

    log_office_write(
        op="runtime.office.surface.update",
        correlation_id=correlation_id,
        workspace=workspace_id,
        folders=len(surface.folders),
        revision=surface.revision,
    )
    result: dict[str, Any] = {
        "workspace_id": surface.workspace_id,
        "folders": list(surface.folders),
        "revision": surface.revision,
    }
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)


@method("runtime.office.resolve_conflict", tier=TIER_CONSOLE)
def _runtime_office_resolve_conflict(
    rid: Any, params: dict, context: RpcContext | None = None
) -> dict:
    """ONE realm-sync conflict, ADOPTED — the sync strip's resolve button.

    Params: ``workspace_id`` and ``actor_key`` (required strings), ``take``
    (required, ``"local"`` or ``"remote"``), ``updated_by`` (optional string,
    defaulting to the argv lane's own ``operator``), and ``correlation_id``
    (optional gesture token — see ``runtime.office.upsert``).

    Result: ``{"actor_key", "take", "state", "revision"?}``. ``revision`` is
    present iff the resolution left an ACTOR behind; its absence is the
    edit-vs-remove tombstone, which is a real outcome of this verb and not an
    error (see below). ``actor_key`` is the STORE's, not the caller's, for the
    reason the upsert's ack records: ``resolve_conflict(take="remote")`` writes
    the key the peer's RECORD carries, and a sidecar's filename and its record
    are allowed to disagree ("payload is truth; the filename is routing only" —
    ``office_sync._read_remote_office``). Echoing the requested key would name a
    row the store did not write. ``take`` is echoed NORMALIZED (stripped,
    lowercased), so a client reading the ack learns which side actually won
    rather than which spelling it happened to send.

    The last office write verb to reach the wire, and the UNFINISHED MAIN PATH
    rather than a fallback deletion: ``harness office resolve-conflict`` stays
    the operator's lane and keeps its flags; this method wraps the same
    ``OfficeStore.resolve_conflict`` the CLI verb calls, adding envelope work
    and nothing else.

    Why ``take`` is validated HERE and not left to the store
    -------------------------------------------------------
    ``OfficeStore.resolve_conflict`` answers an unrecognized ``take`` with
    ``ValueError("invalid_request")`` — a bare string that carries no field
    name, and which this handler would then have to spend its ``actor_invalid``
    reason on, telling the client to inspect a payload whose only fault is one
    enum value. The typed reason is cheaper client-side and the check runs
    BEFORE the store is touched at all, so a nonsense ``take`` cannot even open
    the workspace it named.

    Why an already-resolved conflict is a 4001 and NOT the remove's idempotent
    ok
    -------------------------------------------------------------------------
    The two verbs look like they should agree here and must not. A repeat
    ARCHIVE describes the state the store is already in, so answering ok costs
    nothing and writes nothing. A repeat RESOLVE has no conflict to adopt: the
    sidecar is gone, the store has no remote copy to read, and the only way to
    answer ok would be to invent one. ``resolve_conflict`` refuses that with
    ``SyncConflict("no_conflict:…")``, and this lane translates it to
    ``4001 {reason: "conflict_not_found"}`` — a 4001 rather than 4090 because
    nothing raced: the named conflict does not exist, which is the same shape of
    answer the read leg gives an unknown workspace. Note that ``SyncConflict``
    means the OPPOSITE thing on ``runtime.office.upsert`` (there a sidecar
    EXISTS and blocks the write, so it is a 4090 ``sync_conflict``); copying
    that arm here would tell a client to fetch an operator for a conflict that
    has already been resolved.

    ``NotFound`` lands on the same reason on purpose. It is reachable only as a
    race — the live actor file disappearing between ``actor_exists`` and
    ``get_actor`` inside the store — and the client's cure is identical: refetch
    the projection, there is nothing here to resolve.

    NO ``allow_class_key``, and that asymmetry is the contract
    ---------------------------------------------------------
    ``take="remote"`` writes a PEER's actor with ``_write_actor``, past
    ``upsert_actor`` and every guard its callers hold, so its class-key fence
    lives inside the store (``OfficeStore._guard_class_keyed_adoption``) where a
    second caller inherits it instead of having to remember it. This method is
    that second caller, and it arrives fenced by construction because it calls
    the same store method the CLI does.

    The override stays where consent lives. ``harness office resolve-conflict
    --allow-class-key`` is an operator who read the refusal and typed it; a wire
    PARAMETER is not consent — it is a constant in a client build, set once by
    whoever was debugging the day resolves started failing, and thereafter sent
    by every install on every resolution with no human in any loop. So this
    handler takes no such param, forwards no such param, and an unknown
    ``allow_class_key`` key in ``params`` is inert. The sanctioned override arms
    are untouched: the CLI flag, and ``harness office actor-restore``.

    Which is also why the refusal message is BUILT here rather than passed
    through. The store's sentence ends by offering ``--allow-class-key`` and
    ``--take local``; the first is advice this caller cannot follow, and the
    upsert's arm already ruled that advice a caller cannot follow is worse than
    none. The wire message names the one exit this lane really has —
    ``take: "local"`` — and the machine-readable evidence rides ``data`` with
    the same keys the upsert's collision spends, so one client branch covers
    ``class_key_collision`` whichever verb hit it.
    """

    from agent_runtime.errors import ArchiveUnreadable, NotFound, SyncConflict
    from agent_runtime.office_class_key_guard import ClassKeyedPlacementRefused
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

    raw_take = params.get("take")
    # Normalized the way the store normalizes it, so the handler and the store
    # cannot disagree about which spellings are legal — and echoed from this
    # value, so the ack names the side that won.
    take = raw_take.strip().lower() if isinstance(raw_take, str) else ""
    if take not in {"local", "remote"}:
        return err(
            rid,
            ERR_INVALID_PARAMS,
            'invalid params: take must be "local" or "remote"',
            {"reason": "take_invalid", "workspace_id": workspace_id},
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
        actor = store.resolve_conflict(
            workspace_id,
            actor_key,
            take=take,
            updated_by=updated_by or "operator",
            correlation_id=correlation_id,
        )
    except ClassKeyedPlacementRefused as exc:
        details = dict(getattr(exc, "safe_details", None) or {})
        reasons = list(details.get("reasons") or [])
        conflicting = list(details.get("conflicting_actor_keys") or [])
        return err(
            rid,
            ERR_CONFLICT,
            (
                f"class-keyed adoption for persona {details.get('persona_id')!r} "
                f"refused: {', '.join(reasons)}"
                # Named when there is one — the two reasons fire on different
                # evidence (a ledger entry vs. a live sibling) and only the
                # second has another actor to point at.
                + (
                    f" (conflicts with {', '.join(conflicting)})"
                    if conflicting
                    else ""
                )
                + ". The class→instance re-key archived this class key; adopting "
                'the peer\'s copy undoes that migration. Resolve with take: "local" '
                "to keep the migrated state."
            ),
            {
                "reason": "class_key_collision",
                "workspace_id": workspace_id,
                "actor_key": actor_key,
                "persona_id": details.get("persona_id"),
                "class_actor_key": details.get("class_actor_key"),
                "reasons": reasons,
                "conflicting_actor_keys": conflicting,
                "take": take,
            },
        )
    except SyncConflict as exc:
        # ``no_conflict:<key>`` — see the docstring for why this is a 4001 and
        # not the 4090 ``sync_conflict`` the upsert spends on the same class.
        return err(
            rid,
            ERR_NOT_FOUND,
            str(exc),
            {
                "reason": "conflict_not_found",
                "workspace_id": workspace_id,
                "actor_key": actor_key,
            },
        )
    except NotFound as exc:
        # The race arm, same reason and same cure: refetch the projection.
        return err(
            rid,
            ERR_NOT_FOUND,
            str(exc),
            {
                "reason": "conflict_not_found",
                "workspace_id": workspace_id,
                "actor_key": actor_key,
            },
        )
    except ArchiveUnreadable as exc:
        # EG-1.5's typed refusal, surfaced rather than swallowed. No store path
        # inside ``resolve_conflict`` raises this TODAY — the arm is here because
        # ``ArchiveUnreadable`` is an ``AgentRuntimeError`` and not a
        # ``ValueError``, so without it the condition would arrive as
        # ``handle_request``'s catch-all ``-32000 handler_failed``: a corrupt
        # file on the server reported to the client as "the handler crashed",
        # with no reason to branch on and nothing an operator could act on. One
        # condition gets one name across all three write verbs, so a client that
        # learned ``archive_unreadable`` from the archive leg reads it here too.
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
        # Whatever the store rejected while normalizing ids. ``take`` cannot
        # arrive here — it was validated above — so every remaining case is a
        # malformed identifier, and the client's response to all of them is the
        # same: fix the payload, it is a launcher bug.
        return err(
            rid,
            ERR_INVALID_PARAMS,
            str(exc),
            {"reason": "actor_invalid", "workspace_id": workspace_id},
        )

    if actor is None:
        # The edit-vs-remove tombstone: the peer removed what this side edited,
        # so the resolution ARCHIVED the local row and there is no revision to
        # present. Reported as a success with no ``revision`` key rather than as
        # a refusal, because the operator's conflict really is resolved — and
        # the missing key is what tells the client not to keep guarding a row
        # that no longer exists.
        log_office_write(
            op="runtime.office.resolve_conflict",
            correlation_id=correlation_id,
            workspace=workspace_id,
            actor_key=actor_key,
            take=take,
            state="archived",
        )
        tombstone: dict[str, Any] = {
            "actor_key": actor_key,
            "take": take,
            "state": "archived",
        }
        if correlation_id is not None:
            tombstone["correlation_id"] = correlation_id
        return ok(rid, tombstone)
    log_office_write(
        op="runtime.office.resolve_conflict",
        correlation_id=correlation_id,
        workspace=workspace_id,
        actor_key=actor.actor_key,
        take=take,
        state=actor.state,
        revision=actor.revision,
    )
    result: dict[str, Any] = {
        "actor_key": actor.actor_key,
        "take": take,
        "state": actor.state,
        "revision": actor.revision,
    }
    if correlation_id is not None:
        result["correlation_id"] = correlation_id
    return ok(rid, result)
