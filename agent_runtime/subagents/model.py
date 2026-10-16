"""Subagent inspection protocol shared by native and operator conversations."""
from enum import StrEnum

__layer__ = "models"

VERSION = 1
TAIL_BYTES = 16384
MUTATIONS = ("steer", "stop", "spawning.set", "settings.set")
COMMAND_PARAMS = ("expected_generation", "child_ref", "request_id")
REQUIRED_PARAMS = {
    "capabilities": (), "list": (), "tail": COMMAND_PARAMS[:2],
    "steer": (*COMMAND_PARAMS, "text"), "stop": COMMAND_PARAMS, "receipt": COMMAND_PARAMS,
    "spawning": (), "spawning.set": ("expected_generation", "host_ref", "paused"),
}
LIVE_OPERATIONS = tuple(REQUIRED_PARAMS)
HISTORY_OPERATIONS = ("history", "result", "tree")
SETTINGS_OPERATIONS = ("settings", "settings.set")
REQUIRED_PARAMS.update({"history": (), "result": ("expected_generation", "history_ref"),
                        "tree": ("expected_generation", "history_ref"), "settings": (),
                        "settings.set": ("expected_generation", "expected_revision", "changes")})
OPERATIONS = tuple(REQUIRED_PARAMS)


def include_service_capabilities(operation, reply):
    """Stored observations and profile settings belong to the public owner routes."""
    if operation == "capabilities":
        return {**reply, "operations": [*reply["operations"], *HISTORY_OPERATIONS, *SETTINGS_OPERATIONS]}
    return reply


class Refusal(StrEnum):
    WRONG_OWNER = "subagent_owner_changed"
    STALE = "subagent_reference_stale"
    INVALID = "subagent_request_invalid"
    UNAVAILABLE = "subagent_unavailable"
    UNKNOWN = "subagent_outcome_unknown"
    MANAGED = "subagent_config_managed"
    CONFIG_UNREADABLE = "subagent_config_unreadable"


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
                       ("history_ref", 512), ("host_ref", 512), ("expected_revision", 512)):
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
    if "paused" in required and type(params.get("paused")) is not bool:
        raise SubagentError(Refusal.INVALID)
    if "changes" in required and not isinstance(params.get("changes"), dict):
        raise SubagentError(Refusal.INVALID)
