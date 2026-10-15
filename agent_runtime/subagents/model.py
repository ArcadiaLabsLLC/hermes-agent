"""Subagent inspection protocol shared by native and operator conversations."""
from enum import StrEnum

__layer__ = "models"

VERSION = 1
TAIL_BYTES = 16384
MUTATIONS = ("steer", "stop")
OPERATIONS = ("capabilities", "list", "tail", *MUTATIONS, "receipt")
COMMAND_PARAMS = ("expected_generation", "child_ref", "request_id")


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
    for key in ("expected_generation", "child_ref"):
        value = params.get(key)
        if value is not None and (not isinstance(value, str) or not value or len(value) > 512):
            raise SubagentError(Refusal.INVALID)
    if operation in ("tail", *MUTATIONS, "receipt") and (not params.get("child_ref") or not params.get("expected_generation")):
        raise SubagentError(Refusal.INVALID)
    if operation in (*MUTATIONS, "receipt"):
        request_id = params.get("request_id")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            raise SubagentError(Refusal.INVALID)
    if operation == "steer":
        text = params.get("text")
        if not isinstance(text, str) or not text.strip() or len(text.encode("utf-8")) > 8192:
            raise SubagentError(Refusal.INVALID)
    elif params.get("text") is not None:
        raise SubagentError(Refusal.INVALID)
