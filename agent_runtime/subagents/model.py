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
OPERATIONS = tuple(REQUIRED_PARAMS)


class Refusal(StrEnum):
    WRONG_OWNER = "subagent_owner_changed"
    STALE = "subagent_reference_stale"
    INVALID = "subagent_request_invalid"
    UNAVAILABLE = "subagent_unavailable"
    UNKNOWN = "subagent_outcome_unknown"


class SubagentError(ValueError):
    def __init__(self, reason: Refusal):
        self.reason = reason
        super().__init__(reason.value)


ERROR_CODES = {reason: 4601 + index for index, reason in enumerate(Refusal)}


def validate_request(operation: str, params: dict) -> None:
    if operation not in OPERATIONS:
        raise SubagentError(Refusal.INVALID)
    required = REQUIRED_PARAMS[operation]
    for key, limit in (("expected_generation", 512), ("child_ref", 512), ("request_id", 128)):
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
