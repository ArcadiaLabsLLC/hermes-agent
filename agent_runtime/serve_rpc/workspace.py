"""Non-activating workspace setup over the existing store."""
from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_INVALID_PARAMS, err, ok
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


@method("runtime.workspace.create", tier=TIER_CONSOLE)
def runtime_workspace_create(rid, params, context=None):
    if set(params) != {"name", "idempotency_key"}:
        return err(rid, ERR_INVALID_PARAMS, "Name and creation key are required.")
    try:
        workspace = create_workspace(params["name"], params["idempotency_key"])
    except WorkspaceCreationRefused as exc:
        code = ERR_INVALID_PARAMS if exc.reason == WorkspaceCreationReason.INVALID else ERR_CONFLICT
        return err(rid, code, "Workspace creation needs review.", {"reason": exc.reason.value})
    return ok(rid, {"id": workspace.id, "name": workspace.name})
