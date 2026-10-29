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
    "runtime.project.category.set": (*_WRITE, "category", "slot", "subpath", "shared"),
    "runtime.project.guidance.set": (*_WRITE, "description", "instructions"),
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
    "slot_not_declared": ERR_NOT_FOUND,
    "realm_publish_denied": ERR_HANDLER_FAILED,
}


def _guarded(handler):
    def run(rid, params, context=None):
        from agent_runtime.workspace_slots import SlotRefused

        try:
            return ok(rid, handler(params or {}))
        except SlotRefused as exc:
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
                                       shared=params.get("shared"), issued_at=_issued_at(params))


@method("runtime.project.guidance.set", tier=TIER_CONSOLE)
@_guarded
def _project_guidance_set(params):
    return _store(params).set_guidance(params.get("project_id"), description=params.get("description"),
                                       instructions=params.get("instructions"), issued_at=_issued_at(params))
