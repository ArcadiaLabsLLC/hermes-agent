"""Translate an already-owned route to its existing worker; never attach."""
from agent_runtime.subagents.model import ERROR_CODES, SubagentError, validate_request
from .model import ConversationError, digest

__layer__ = "lanes"


def inspect_children(install_id, scope, live, operation, params):
    validate_request(operation, params)
    identity = {"install_id": install_id, "session_id": live.route.id,
                "client_scope": scope.client, "profile": scope.profile}
    request = {
        "session_id": live.native_id,
        "owner_scope": digest([install_id, scope.key, live.route.id]),
        "worker_generation": live.worker.generation,
        **{key: params[key] for key in ("expected_generation", "child_ref") if key in params},
    }
    try:
        result = live.peer.call("eternia.subagents." + operation, request)
    except ConversationError as exc:
        reason = next((reason for reason, code in ERROR_CODES.items() if code == exc.native_code), None)
        if reason is not None:
            raise SubagentError(reason) from exc
        raise
    return {**result["data"], **identity}
