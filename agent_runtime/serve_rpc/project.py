"""``runtime.project.*`` — the Launcher Project record's doors (plan project-slots-and-shared-chats §2).

All ``console``. Every write (``declare``, ``category.set``, ``guidance.set``) runs the realm
PUBLISH decision for each realm whose workspace holds the Project
(``project_store.require_project_publish_rights``); ``credential`` is the inline object the
realm verbs take, ``credentials`` a list of them when the Project is assigned into several
server-bound realms (each admits only its own realm). Every refusal is a typed ``data.reason``.
"""

from agent_runtime.call_authorization import TIER_CONSOLE
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, ERR_NOT_FOUND, err, ok
from agent_runtime.serve_rpc.registry import method

__layer__ = "lanes"

_WRITE = ("project_id", "issued_at", "credential", "credentials")
#: The honoured keys of every ``runtime.project.*`` verb (the manifest's ``params``, the launcher mirror).
PROJECT_METHOD_PARAMS: dict[str, tuple[str, ...]] = {
    "runtime.project.show": ("project_id",),
    "runtime.project.declare": (*_WRITE, "name", "slots"),
    "runtime.project.category.set": (*_WRITE, "category", "slot", "subpath", "shared", "context_files"),
    "runtime.project.guidance.set": (*_WRITE, "description", "instructions"),
    "runtime.project.slot.bind": ("project_id", "slot", "path", "issued_at"),
    "runtime.project.slot.env.set": ("project_id", "slot", "env", "env_keep", "tool_paths", "path_prepend", "dotenv",
                                     "venv", "issued_at"),
    "runtime.project.report": ("project_id",),
    "runtime.project.artifacts.list": ("project_id",),
    "runtime.project.chat.share": ("project_id", "session_id", "shared", "credential", "credentials"),
    "runtime.project.chat.fold": ("project_id",),
}

#: ``SlotRefused.reason`` → the JSON-RPC error code it rides; anything else rides ERR_CONFLICT.
_REFUSAL_CODES = {
    "invalid_reference": ERR_INVALID_PARAMS,
    "invalid_slot_name": ERR_INVALID_PARAMS,
    "invalid_clone_url": ERR_INVALID_PARAMS,
    "invalid_declaration": ERR_INVALID_PARAMS,
    "clone_url_carries_credential": ERR_INVALID_PARAMS,
    "unknown_category": ERR_INVALID_PARAMS,
    "guidance_too_long": ERR_INVALID_PARAMS,
    "category_not_source_controlled": ERR_INVALID_PARAMS,
    "invalid_path": ERR_INVALID_PARAMS,
    "invalid_fill": ERR_INVALID_PARAMS,
    "secret_in_env": ERR_INVALID_PARAMS,
    "category_not_shared": ERR_CONFLICT,
    "chats_folder_unbound": ERR_CONFLICT,
    "session_not_found": ERR_NOT_FOUND,
    "slot_not_declared": ERR_NOT_FOUND,
    "path_not_found": ERR_NOT_FOUND,
    "realm_publish_denied": ERR_HANDLER_FAILED,
}


def _guarded(handler):
    def run(rid, params, context=None):
        from agent_runtime.work_store.reasons import WorkRefused
        from agent_runtime.workspace_slot_env import SlotEnvRefused
        from agent_runtime.workspace_slots import SlotRefused

        try:
            return ok(rid, handler(params or {}))
        except WorkRefused as exc:  # the chats folder's git publication refused (push, worktree, fence)
            return err(rid, ERR_CONFLICT, "The Project's chats folder could not publish.",
                       {"reason": getattr(getattr(exc, "reason", None), "value", "work_refused"),
                        "detail": str(exc)})
        except (SlotRefused, SlotEnvRefused) as exc:
            return err(rid, _REFUSAL_CODES.get(exc.reason, ERR_CONFLICT), "The Project request was refused.",
                       {"reason": exc.reason, "detail": exc.detail})
    return run


def _store(params: dict):
    """A :class:`ProjectStore` carrying the request's realm credentials, keyed by realm id."""

    from agent_runtime.project_store import ProjectStore
    from agent_runtime.realm_membership import RealmSyncCredential
    from agent_runtime.realm_sync.models import RealmSyncError
    from agent_runtime.workspace_slots import REASON_INVALID_DECLARATION, SlotRefused

    raw = list(params.get("credentials") or [])
    if params.get("credential") is not None:
        raw.append(params["credential"])
    credentials = {}
    for entry in raw:
        try:
            parsed = RealmSyncCredential.parse(entry)
        except RealmSyncError as exc:
            raise SlotRefused(REASON_INVALID_DECLARATION, "credential") from exc
        credentials[parsed.realm_id] = parsed
    return ProjectStore(credentials)


def _issued_at(params: dict) -> str:
    from agent_runtime.serve_rpc.workspace_slots import _issued_at as slot_issued_at

    return slot_issued_at(params)


@method("runtime.project.show", tier=TIER_CONSOLE)
@_guarded
def _project_show(params):
    from agent_runtime.project_store import show

    return show(params.get("project_id"))


@method("runtime.project.declare", tier=TIER_CONSOLE)
@_guarded
def _project_declare(params):
    from agent_runtime.workspace_slots import machine_id

    return _store(params).declare(params.get("project_id"), params.get("slots"), issued_at=_issued_at(params),
                                  machine=machine_id(), name=params.get("name"))


@method("runtime.project.category.set", tier=TIER_CONSOLE)
@_guarded
def _project_category_set(params):
    return _store(params).set_category(params.get("project_id"), str(params.get("category") or ""),
                                       slot=params.get("slot"), subpath=params.get("subpath"),
                                       shared=params.get("shared"), issued_at=_issued_at(params),
                                       context_files=params.get("context_files"))


@method("runtime.project.guidance.set", tier=TIER_CONSOLE)
@_guarded
def _project_guidance_set(params):
    return _store(params).set_guidance(params.get("project_id"), description=params.get("description"),
                                       instructions=params.get("instructions"), issued_at=_issued_at(params))


# ── this machine's fill of a Project's slots (LOCAL_CONSOLE_METHODS: never from a paired device) ──


@method("runtime.project.slot.bind", tier=TIER_CONSOLE)
@_guarded
def _project_slot_bind(params):
    from agent_runtime.workspace_slots import bind_project

    return bind_project(params.get("project_id"), str(params.get("slot") or ""), str(params.get("path") or ""),
                        issued_at=_issued_at(params))


@method("runtime.project.slot.env.set", tier=TIER_CONSOLE)
@_guarded
def _project_slot_env_set(params):
    from agent_runtime.project_store import load_project, valid_project_id
    from agent_runtime.workspace_slot_env import fill_shape, set_slot_fill
    from agent_runtime.workspace_slots import REASON_SLOT_NOT_DECLARED, SlotRefused, live_slots, secret_keys
    from agent_runtime.workspace_slots_probe import report_project

    project_id, slot = valid_project_id(params.get("project_id")), str(params.get("slot") or "")
    declared = live_slots(load_project(project_id)).get(slot)
    if declared is None:
        raise SlotRefused(REASON_SLOT_NOT_DECLARED, slot)
    keep = params.get("env_keep")
    fill = set_slot_fill(None, slot, env=params.get("env"), tool_paths=params.get("tool_paths"),
                         path_prepend=params.get("path_prepend"), dotenv=params.get("dotenv"), venv=params.get("venv"),
                         secret_keys=secret_keys(declared), issued_at=_issued_at(params), env_keep=keep,
                         project_id=project_id)
    row = report_project(project_id)["slots"].get(slot, {})
    return {"project_id": project_id, "slot": slot, "env_keys": sorted(fill.env), "report": row,
            "fill": fill_shape(None, slot, project_id=project_id),
            "env_keep_missing": sorted(set(keep or ()) - set(fill.env))}


@method("runtime.project.report", tier=TIER_CONSOLE)
@_guarded
def _project_report(params):
    from agent_runtime.project_store import valid_project_id
    from agent_runtime.workspace_slots_probe import report_project

    return report_project(valid_project_id(params.get("project_id")))


@method("runtime.project.artifacts.list", tier=TIER_CONSOLE)
@_guarded
def _project_artifacts_list(params):
    """The artifacts folder's names and sizes on this machine; hermes never writes there (plan §7)."""

    from agent_runtime.project_categories import artifacts_list

    return artifacts_list(params.get("project_id"))


@method("runtime.project.chat.share", tier=TIER_CONSOLE)
@_guarded
def _project_chat_share(params):
    """Share one chat into a Project (backfill, then every turn end) or stop sharing it (plan §5)."""

    from agent_runtime.chat_session_scope import SessionDbAccess, open_chat_session_db, resolve_chat_session_scope
    from agent_runtime.project_chat_export import share

    session_id = str(params.get("session_id") or "")
    session_db = (open_chat_session_db(resolve_chat_session_scope(session_id=session_id), access=SessionDbAccess.READ)
                  if session_id and params.get("shared") is True else None)
    store = _store(params)
    return share(params.get("project_id"), session_id, params.get("shared"), session_db=session_db,
                 credentials=store._credentials)


@method("runtime.project.chat.fold", tier=TIER_CONSOLE)
@_guarded
def _project_chat_fold(params):
    """Fetch the Project's chats folder to its remote tip and fold new turns into its shared store (plan §6)."""

    from agent_runtime.project_chat_fold import fold_from_remote
    from agent_runtime.project_store import valid_project_id

    return fold_from_remote(valid_project_id(params.get("project_id")))
