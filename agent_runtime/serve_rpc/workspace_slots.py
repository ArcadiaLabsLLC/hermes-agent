"""``runtime.workspace.slots.*`` / ``.slot.*`` and ``runtime.persona.instance.slots.*`` — the repo-slot doors (build plan §3.4).

All ``console``. The three verbs that touch THIS machine's fill — ``slot.bind``,
``slot.env.set``, ``slots.report`` — are on ``LOCAL_CONSOLE_METHODS``: a paired console
device may read a workspace's slots, never write the operator's paths or environment.
``slots.declare`` is gated on the realm PUBLISH right (call 8a) and takes the same inline
``credential`` object the realm verbs do. Every refusal is a typed ``data.reason``.
"""

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, ERR_NOT_FOUND, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

#: ``SlotRefused.reason`` / ``SlotEnvRefused.reason`` → the JSON-RPC error code it rides.
_REFUSAL_CODES = {
    "invalid_slot_name": ERR_INVALID_PARAMS,
    "invalid_clone_url": ERR_INVALID_PARAMS,
    "invalid_declaration": ERR_INVALID_PARAMS,
    "invalid_path": ERR_INVALID_PARAMS,
    "invalid_fill": ERR_INVALID_PARAMS,
    "secret_in_env": ERR_INVALID_PARAMS,
    "workspace_not_found": ERR_NOT_FOUND,
    "slot_not_declared": ERR_NOT_FOUND,
    "path_not_found": ERR_NOT_FOUND,
    "realm_publish_denied": ERR_HANDLER_FAILED,
}


def _refused(rid, exc) -> dict:
    reason = getattr(exc, "reason", "invalid_request")
    return err(rid, _REFUSAL_CODES.get(reason, ERR_CONFLICT), "The slot request was refused.",
               {"reason": reason, "detail": getattr(exc, "detail", "")})


def _workspace(params: dict) -> str:
    from agent_runtime import paths
    from agent_runtime.workspace_slots import REASON_WORKSPACE_NOT_FOUND, SlotRefused

    workspace_id = params.get("workspace_id")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise SlotRefused("invalid_declaration", "workspace_id is required")
    if not paths.workspace_path(workspace_id).exists():
        raise SlotRefused(REASON_WORKSPACE_NOT_FOUND, workspace_id)
    return workspace_id


def _issued_at(params: dict) -> str:
    from agent_runtime.workspace_slots import SlotRefused, stamp_epoch

    issued_at = params.get("issued_at")
    if stamp_epoch(issued_at) is None:
        raise SlotRefused("invalid_declaration", "issued_at must be an ISO-8601 stamp")
    return str(issued_at)


def _guarded(handler):
    def run(rid, params, context=None):
        from agent_runtime.workspace_slot_env import SlotEnvRefused
        from agent_runtime.workspace_slots import SlotRefused

        try:
            return ok(rid, handler(params or {}))
        except (SlotRefused, SlotEnvRefused) as exc:
            return _refused(rid, exc)
    return run


@method("runtime.workspace.slots.show", tier=TIER_CONSOLE)
@_guarded
def _slots_show(params):
    from agent_runtime.workspace_slots import show

    return show(_workspace(params))


@method("runtime.workspace.slots.declare", tier=TIER_CONSOLE)
@_guarded
def _slots_declare(params):
    from agent_runtime.realm_membership import RealmSyncCredential
    from agent_runtime.workspace_slots import declare, machine_id, require_publish_right

    workspace_id = _workspace(params)
    raw = params.get("credential")
    require_publish_right(workspace_id, None if raw is None else RealmSyncCredential.parse(raw))
    return declare(workspace_id, params.get("slots"), issued_at=_issued_at(params), machine=machine_id())


@method("runtime.workspace.slots.report", tier=TIER_CONSOLE)
@_guarded
def _slots_report(params):
    from agent_runtime.workspace_slots_probe import report

    return report(_workspace(params))


@method("runtime.workspace.slot.bind", tier=TIER_CONSOLE)
@_guarded
def _slot_bind(params):
    from agent_runtime.workspace_slots import bind

    return bind(_workspace(params), str(params.get("slot") or ""), str(params.get("path") or ""),
                issued_at=_issued_at(params))


@method("runtime.workspace.slot.env.set", tier=TIER_CONSOLE)
@_guarded
def _slot_env_set(params):
    from agent_runtime.workspace_slot_env import set_slot_fill
    from agent_runtime.workspace_slots import REASON_SLOT_NOT_DECLARED, SlotRefused, live_slots, load_document, secret_keys
    from agent_runtime.workspace_slots_probe import report

    workspace_id, slot = _workspace(params), str(params.get("slot") or "")
    declared = live_slots(load_document(workspace_id)).get(slot)
    if declared is None:
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, slot)
    fill = set_slot_fill(workspace_id, slot, env=params.get("env"), tool_paths=params.get("tool_paths"),
                         path_prepend=params.get("path_prepend"), dotenv=params.get("dotenv"), venv=params.get("venv"),
                         secret_keys=secret_keys(declared), issued_at=_issued_at(params))
    row = report(workspace_id)["slots"].get(slot, {})
    return {"slot": slot, "env_keys": sorted(fill.env), "tool_paths": sorted(fill.tool_paths),
            "path_prepend": len(fill.path_prepend), "report": row}


# ── the per-instance assignment (the Agent Console's editor — owner correction 2026-10-04) ──

_ASSIGNMENT_CODES = {
    "invalid_request": ERR_INVALID_PARAMS,
    "instance_not_found": ERR_NOT_FOUND,
    "slot_not_in_workspace": ERR_INVALID_PARAMS,
    "primary_not_assigned": ERR_INVALID_PARAMS,
    "instance_has_no_workspace": ERR_CONFLICT,
    "stale_revision": ERR_CONFLICT,
}


def _assignment(handler):
    def run(rid, params, context=None):
        from agent_runtime.persona_slots import SlotAssignmentRefused

        try:
            return ok(rid, handler(params or {}))
        except SlotAssignmentRefused as exc:
            return err(rid, _ASSIGNMENT_CODES.get(exc.reason, ERR_CONFLICT), "The slot assignment was refused.",
                       {"reason": exc.reason, "detail": exc.detail})
    return run


@method("runtime.persona.instance.slots.show", tier=TIER_CONSOLE)
@_assignment
def _instance_slots_show(params):
    from agent_runtime.persona_slots import show_instance_slots

    return show_instance_slots(str(params.get("persona_instance_id") or ""))


@method("runtime.persona.instance.slots.set", tier=TIER_CONSOLE)
@_assignment
def _instance_slots_set(params):
    from agent_runtime.persona_slots import set_instance_slots

    return set_instance_slots(str(params.get("persona_instance_id") or ""), params.get("slots"), params.get("primary"),
                              issued_at=str(params.get("issued_at") or ""))
