"""Subagent inspection protocol shared by native and operator conversations."""
from enum import StrEnum

__layer__ = "models"

VERSION = 1
TAIL_BYTES = 16384
MUTATIONS = ("steer", "stop")
COMMAND_PARAMS = ("expected_generation", "child_ref", "request_id")
REQUIRED_PARAMS = {
    "capabilities": (), "list": (), "tail": COMMAND_PARAMS[:2],
    "steer": (*COMMAND_PARAMS, "text"), "stop": COMMAND_PARAMS, "receipt": COMMAND_PARAMS,
}
# Step 6: the pause is owned by the execution host process that runs delegate_task;
# the worker (or compute host, or the serve itself for operator chats) answers it.
SPAWNING_OPERATIONS = ("spawning", "spawning.set")
REQUIRED_PARAMS.update({"spawning": (), "spawning.set": ("expected_generation", "host_ref", "paused")})
LIVE_OPERATIONS = tuple(REQUIRED_PARAMS)
# Profile defaults are profile state, served by the serve process, never a child host.
SETTINGS_OPERATIONS = ("settings", "settings.set")
REQUIRED_PARAMS.update({"settings": (), "settings.set": ("expected_generation", "expected_revision", "changes")})
# A write whose outcome a lost reply cannot prove either way.
WRITES = (*MUTATIONS, "settings.set", "spawning.set")
HISTORY_OPERATIONS = ("history", "result", "tree")
REQUIRED_PARAMS.update({"history": (), "result": ("expected_generation", "history_ref"),
                        "tree": ("expected_generation", "history_ref")})
OPERATIONS = tuple(REQUIRED_PARAMS)


def include_history_capabilities(operation, reply):
    """Only the public owner routes serve stored observations and profile defaults, not workers."""
    if operation == "capabilities":
        return {**reply, "operations": [*reply["operations"], *SETTINGS_OPERATIONS, *HISTORY_OPERATIONS]}
    return reply


class Refusal(StrEnum):
    WRONG_OWNER = "subagent_owner_changed"
    STALE = "subagent_reference_stale"
    INVALID = "subagent_request_invalid"
    UNAVAILABLE = "subagent_unavailable"
    UNKNOWN = "subagent_outcome_unknown"
    MANAGED = "subagent_setting_managed"


class SubagentError(ValueError):
    def __init__(self, reason: Refusal):
        self.reason = reason
        super().__init__(reason.value)


ERROR_CODES = {reason: 4601 + index for index, reason in enumerate(Refusal)}


def validate_request(operation: str, params: dict) -> None:
    if operation not in OPERATIONS:
        raise SubagentError(Refusal.INVALID)
    required = REQUIRED_PARAMS[operation]
    for key, limit in (("expected_generation", 512), ("child_ref", 512), ("request_id", 128),
                       ("history_ref", 512), ("expected_revision", 128), ("host_ref", 512)):
        value = params.get(key)
        if value is None and key not in required:
            continue
        if not isinstance(value, str) or not value or len(value) > limit:
            raise SubagentError(Refusal.INVALID)
    if "text" in required:
        text = params.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 8192:
            raise SubagentError(Refusal.INVALID)
    elif params.get("text") is not None:
        raise SubagentError(Refusal.INVALID)
    paused, changes = params.get("paused"), params.get("changes")
    if ("paused" in required) != (paused is not None) or type(paused) not in (bool, type(None)):
        raise SubagentError(Refusal.INVALID)
    if ("changes" in required) != (changes is not None) or not isinstance(changes, dict | None):
        raise SubagentError(Refusal.INVALID)
