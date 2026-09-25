"""``runtime.office.surface_update`` / ``resolve_conflict`` — the two
surface-level office writes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.errors import (
    AgentRuntimeError,
    ArchiveUnreadable,
    NotFound,
    StaleRevision,
    SyncConflict,
)
from agent_runtime.office_class_key_guard import ClassKeyedPlacementRefused

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
    workspace_id_required,
    unknown_workspace,
    expect_revision_invalid,
    updated_by_invalid,
    ParamRefused,
    _correlation_id_param,
    _workspace_id_param,
)
from agent_runtime.serve_rpc.office_read import log_office_write
from agent_runtime.serve_rpc.office_errors import (
    OfficeWriteScope,
    Translation,
    refusal,
    translate,
)

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

    Rationale (3 sections) relocated verbatim to
    ``docs/agent-runtime-harness/history/serve_rpc.md`` § `runtime.office.surface.update` (rule 7).
    """

    from agent_runtime.office_store import OfficeStore

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        # The same reason string every office method spends on this, on
        # purpose: one client branch covers it whatever the verb was.
        return workspace_id_required(rid)

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
        return expect_revision_invalid(rid)

    updated_by = params.get("updated_by")
    if updated_by is not None and not isinstance(updated_by, str):
        return updated_by_invalid(rid)

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as refused:
        return refused.frame(rid, workspace_id=workspace_id)

    store = OfficeStore()
    if not store.surface_exists(workspace_id):
        return unknown_workspace(rid, workspace_id)

    try:
        surface = store.update_surface(
            workspace_id,
            folders=folders,
            updated_by=updated_by or "operator",
            expect_revision=expect_revision,
            correlation_id=correlation_id,
        )
    except (AgentRuntimeError, ValueError) as exc:
        scope = OfficeWriteScope(rid, workspace_id, {"expect_revision": expect_revision})
        return translate(exc, SURFACE_UPDATE_ERRORS, scope)

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

    Rationale (3 sections) relocated verbatim to
    ``docs/agent-runtime-harness/history/serve_rpc.md`` § `runtime.office.resolve_conflict` (rule 7).
    """

    from agent_runtime.office_store import OfficeStore

    workspace_id = _workspace_id_param(params)
    if workspace_id is None:
        # The same reason string every office method spends on this, on
        # purpose: one client branch covers it whatever the verb was.
        return workspace_id_required(rid)

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
        return updated_by_invalid(rid)

    try:
        correlation_id = _correlation_id_param(params)
    except ParamRefused as refused:
        return refused.frame(rid, workspace_id=workspace_id)

    store = OfficeStore()
    if not store.surface_exists(workspace_id):
        return unknown_workspace(rid, workspace_id)

    try:
        actor = store.resolve_conflict(
            workspace_id,
            actor_key,
            take=take,
            updated_by=updated_by or "operator",
            correlation_id=correlation_id,
        )
    except (AgentRuntimeError, ValueError) as exc:
        scope = OfficeWriteScope(rid, workspace_id, {"actor_key": actor_key, "take": take})
        return translate(exc, RESOLVE_CONFLICT_ERRORS, scope)

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


# ── store exceptions → frames, per verb (office_errors.translate walks these) ──


#: ``runtime.office.surface.update``'s translation table.
SURFACE_UPDATE_ERRORS: Mapping[type[BaseException], Translation] = {
        # ``data`` deliberately carries NO current revision — the same rule both
        # actor verbs follow, and for the same reason: handing back the number
        # invites a retry with it, which is the lost update the guard refused.
    StaleRevision: refusal(ERR_CONFLICT, "stale_revision", carry=("expect_revision",)),
        # The store's own ``invalid_request`` sentence rides ``message``; one
        # reason, because the client's response to every one of them is the
        # same — fix the payload, it is a launcher bug.
    ValueError: refusal(ERR_INVALID_PARAMS, "folders_invalid"),
}


def _resolve_class_keyed_refusal(
    exc: ClassKeyedPlacementRefused, scope: OfficeWriteScope
) -> dict:
    details = dict(getattr(exc, "safe_details", None) or {})
    reasons = list(details.get("reasons") or [])
    conflicting = list(details.get("conflicting_actor_keys") or [])
    return err(
        scope.rid,
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
            "workspace_id": scope.workspace_id,
            "actor_key": scope.fields["actor_key"],
            "persona_id": details.get("persona_id"),
            "class_actor_key": details.get("class_actor_key"),
            "reasons": reasons,
            "conflicting_actor_keys": conflicting,
            "take": scope.fields["take"],
        },
    )


#: ``runtime.office.resolve_conflict``'s translation table.
RESOLVE_CONFLICT_ERRORS: Mapping[type[BaseException], Translation] = {
    ClassKeyedPlacementRefused: _resolve_class_keyed_refusal,
        # ``no_conflict:<key>`` — see the docstring for why this is a 4001 and
        # not the 4090 ``sync_conflict`` the upsert spends on the same class.
    SyncConflict: refusal(ERR_NOT_FOUND, "conflict_not_found", carry=("actor_key",)),
        # The race arm, same reason and same cure: refetch the projection.
    NotFound: refusal(ERR_NOT_FOUND, "conflict_not_found", carry=("actor_key",)),
        # EG-1.5's typed refusal, surfaced rather than swallowed. No store path
        # inside ``resolve_conflict`` raises this TODAY — the arm is here because
        # ``ArchiveUnreadable`` is an ``AgentRuntimeError`` and not a
        # ``ValueError``, so without it the condition would arrive as
        # ``handle_request``'s catch-all ``-32000 handler_failed``: a corrupt
        # file on the server reported to the client as "the handler crashed",
        # with no reason to branch on and nothing an operator could act on. One
        # condition gets one name across all three write verbs, so a client that
        # learned ``archive_unreadable`` from the archive leg reads it here too.
    ArchiveUnreadable: refusal(
        ERR_INVALID_REQUEST, ArchiveUnreadable.code, carry=("actor_key",)
    ),
        # Whatever the store rejected while normalizing ids. ``take`` cannot
        # arrive here — it was validated above — so every remaining case is a
        # malformed identifier, and the client's response to all of them is the
        # same: fix the payload, it is a launcher bug.
    ValueError: refusal(ERR_INVALID_PARAMS, "actor_invalid"),
}
