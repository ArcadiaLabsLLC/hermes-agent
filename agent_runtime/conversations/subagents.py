"""Translate an already-owned route to its existing worker; never attach."""
from agent_runtime.subagents.model import COMMAND_PARAMS, ERROR_CODES, WRITES, Refusal, SubagentError, validate_request
from .model import ConversationError, digest

__layer__ = "lanes"


def child_owner(install_id, scope, live) -> dict:
    """The worker-side owner of a route's children: ``owner_scope`` + ``worker_generation``.

    The ONE derivation both ``eternia.subagents.*`` and the child address on
    ``eternia.skills.*`` send, so a ``child_ref`` minted by a subagents read resolves on a skills call.
    """
    return {"owner_scope": digest([install_id, scope.key, live.route.id]),
            "worker_generation": live.worker.generation}


def call_child(live, method: str, request: dict, *, write: bool) -> dict:
    """``live.peer.call`` with a worker's subagent refusal raised as a ``SubagentError``.

    A write whose reply is lost is ``unknown`` (its outcome cannot be proven either way).
    """
    try:
        return live.peer.call(method, request)
    except ConversationError as exc:
        reason = next((reason for reason, code in ERROR_CODES.items() if code == exc.native_code), None)
        if reason is not None:
            raise SubagentError(reason) from exc
        if write:
            raise SubagentError(Refusal.UNKNOWN) from exc
        raise


def inspect_children(install_id, scope, live, operation, params):
    validate_request(operation, params)
    identity = {"install_id": install_id, "session_id": live.route.id,
                "client_scope": scope.client, "profile": scope.profile}
    request = {
        "session_id": live.native_id,
        **child_owner(install_id, scope, live),
        **{key: params[key] for key in (*COMMAND_PARAMS, "text", "host_ref", "paused") if key in params},
    }
    result = call_child(live, "eternia.subagents." + operation, request, write=operation in WRITES)
    return {**result["data"], **identity}


def inspect_settings_route(install_id, scope, route, operation, params):
    """Profile defaults for the route's own recorded home; no worker is borrowed or started."""
    from pathlib import Path
    from agent_runtime.subagents.settings import inspect_settings

    identity = {"install_id": install_id, "session_id": route.id,
                "client_scope": scope.client, "profile": scope.profile}
    owner = digest([install_id, scope.key, route.id, str(route.home)])
    return {**inspect_settings(operation, params, owner=(owner,), home=Path(route.home)), **identity}
