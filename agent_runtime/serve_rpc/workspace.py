"""Workspace setup and management over the existing store: the conversations home, the create door, the realm
assign, the realm move and unarchive."""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, ERR_NOT_FOUND, err, ok
from agent_runtime.serve_rpc.registry import method
from agent_runtime.workspace_create import create_workspace, WorkspaceCreationRefused, WorkspaceCreationReason

__layer__ = "lanes"


@method("runtime.workspace.conversations", tier=TIER_CONSOLE)
def runtime_conversations_workspace(rid, params, context=None):
    from agent_runtime.workspace_create import conversations_workspace

    if params:
        return err(rid, ERR_INVALID_PARAMS, "No parameters expected.")
    try:
        workspace = conversations_workspace()
    except WorkspaceCreationRefused as exc:
        return err(rid, ERR_CONFLICT, "The conversations workspace needs attention.", {"reason": exc.reason.value})
    return ok(rid, {"id": workspace.id, "name": workspace.name})


_CREATE_REQUIRED = {"name", "idempotency_key"}
_CREATE_OPTIONAL = {"realm_id", "template_workspace_id", "copy_scopes"}


@method("runtime.workspace.create", tier=TIER_CONSOLE)
def runtime_workspace_create(rid, params, context=None):
    """The argv verb's contract (``harness workspace create``): one
    implementation in ``agent_runtime.workspace_create``, fenced by the key."""
    keys = set(params)
    if not _CREATE_REQUIRED <= keys or not keys <= _CREATE_REQUIRED | _CREATE_OPTIONAL:
        return err(rid, ERR_INVALID_PARAMS, "Name and creation key are required.")
    try:
        _workspace, row, warnings = create_workspace(
            params["name"],
            params["idempotency_key"],
            realm_id=params.get("realm_id"),
            template_workspace_id=params.get("template_workspace_id"),
            copy_scopes=params.get("copy_scopes"),
            land_in_default=True,
        )
    except WorkspaceCreationRefused as exc:
        code = ERR_INVALID_PARAMS if exc.reason == WorkspaceCreationReason.INVALID else ERR_CONFLICT
        return err(rid, code, "Workspace creation needs review.", {"reason": exc.reason.value})
    return ok(rid, {**row, "warnings": warnings})


_ASSIGN_CODES = {"invalid_request": ERR_INVALID_PARAMS, "workspace_not_found": ERR_NOT_FOUND,
                 "realm_not_found": ERR_NOT_FOUND}


@method("runtime.workspace.assign_realm", tier=TIER_CONSOLE)
def runtime_workspace_assign_realm(rid, params, context=None):
    """Home a realm-less workspace in a realm (RT-WORKSPACE-REALM-ASSIGN-VERB): ``{workspace_id, realm_id}``
    -> the workspace row plus ``assigned`` (false when that realm already owned it whole)."""
    from agent_runtime.workspace_create import assign_workspace_realm, WorkspaceRealmRefused

    if set(params) != {"workspace_id", "realm_id"}:
        return err(rid, ERR_INVALID_PARAMS, "workspace_id and realm_id are required.", {"reason": "invalid_request"})
    try:
        row, assigned = assign_workspace_realm(params["workspace_id"], params["realm_id"])
    except WorkspaceRealmRefused as exc:
        data = {"reason": exc.reason.value}
        if exc.owner_realm_id is not None:
            data["owner_realm_id"] = exc.owner_realm_id
        return err(rid, _ASSIGN_CODES.get(exc.reason.value, ERR_CONFLICT), "The realm assignment was refused.", data)
    return ok(rid, {**row, "assigned": assigned})


_MANAGE_CODES = {"invalid_request": ERR_INVALID_PARAMS, "workspace_not_found": ERR_NOT_FOUND,
                 "realm_not_found": ERR_NOT_FOUND}


def _manage(rid, keys, params, call, optional=frozenset()):
    """One ``agent_runtime.workspace_manage`` verb: exact params (``keys``, plus any of ``optional``), the row
    plus its outcome flags, or the typed refusal on ``error.data`` (``reason`` and the refusal's details). A
    realm-sync refusal (the publish gate of a move out of a shared realm) answers the same shape, with
    ``RealmSyncError.code`` as the reason."""
    from agent_runtime.realm_sync import RealmSyncError
    from agent_runtime.serde import to_jsonable
    from agent_runtime.workspace_manage import WorkspaceManageRefused

    if not isinstance(params, dict) or not keys <= set(params) <= keys | optional:
        return err(rid, ERR_INVALID_PARAMS, f"{' and '.join(sorted(keys))} required.", {"reason": "invalid_request"})
    try:
        row, flags = call()
    except WorkspaceManageRefused as exc:
        code = _MANAGE_CODES.get(exc.reason.value, ERR_CONFLICT)
        return err(rid, code, "The workspace was not changed.", {"reason": exc.reason.value, **exc.details})
    except RealmSyncError as exc:
        return err(rid, ERR_CONFLICT, "The workspace was not changed.",
                   {"reason": exc.code, "retryable": bool(exc.retryable)})
    return ok(rid, dict(to_jsonable({**row, **flags})))


@method("runtime.workspace.unarchive", tier=TIER_CONSOLE)
def runtime_workspace_unarchive(rid, params, context=None):
    """Bring an archived workspace back (RT-WORKSPACE-UNARCHIVE; argv twin ``harness workspace unarchive``):
    ``{workspace_id}`` -> the full workspace row (``archived: false``) plus ``restored`` (false when it was not
    archived). Refusals: ``invalid_request``, ``workspace_not_found``, ``realm_archived`` (+ ``realm_id``)."""
    from agent_runtime.workspace_manage import unarchive_workspace

    def call():
        row, restored = unarchive_workspace(params["workspace_id"])
        return row, {"restored": restored}

    return _manage(rid, {"workspace_id"}, params, call)


@method("runtime.workspace.move_realm", tier=TIER_CONSOLE)
def runtime_workspace_move_realm(rid, params, context=None):
    """Move a workspace into another realm (RT-WORKSPACE-MOVE-REALM; argv twin ``harness workspace move-realm``):
    ``{workspace_id, realm_id}`` plus, for a move OUT of a server-bound realm (RT-WORKSPACE-MOVE-OUT-OF-SERVER-REALM),
    ``confirm_leave_realm`` (that realm's id or name) and ``credential`` (the launcher-brokered object the
    ``runtime.realm.*`` verbs take, minted for that realm) -> the workspace row (``realm_id`` now the target) plus
    ``moved``, ``from_realm_id``, ``active_workspace_id`` and ``publish_owed`` (the server-bound realms to publish,
    in order). Refusals: ``invalid_request``, ``workspace_not_found``, ``realm_not_found``, ``realm_archived``
    (+ ``realm_id``), ``workspace_archived``, ``realm_default_workspace`` (+ ``realm_id``),
    ``workspace_move_confirm_required`` (+ ``owner_realm_id``, ``owner_realm_name``: the confirm is absent or names
    another realm), and the source realm's publish gate — ``sync_auth_failed``, ``role_insufficient``,
    ``membership_denied``, ``realm_revoked``, ``sync_remote_unreachable`` (+ ``retryable``). The rules are
    ``agent_runtime.workspace_manage.move_workspace_realm``'s."""
    from agent_runtime.workspace_manage import move_workspace_realm

    def call():
        from agent_runtime.realm_membership import RealmSyncCredential

        raw = params.get("credential")
        return move_workspace_realm(
            params["workspace_id"], params["realm_id"], confirm_leave_realm=params.get("confirm_leave_realm"),
            credential=None if raw is None else RealmSyncCredential.parse(raw))

    return _manage(rid, {"workspace_id", "realm_id"}, params, call,
                   optional=frozenset({"confirm_leave_realm", "credential"}))
