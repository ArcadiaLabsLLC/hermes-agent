"""Subagent inspection protocol shared by native and operator conversations."""
from enum import StrEnum

__layer__ = "models"

VERSION = 1
TAIL_BYTES = 16384
OPERATIONS = ("capabilities", "list", "tail")


class Refusal(StrEnum):
    WRONG_OWNER = "subagent_owner_changed"
    STALE = "subagent_reference_stale"
    INVALID = "subagent_request_invalid"
    UNAVAILABLE = "subagent_unavailable"


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
    if operation == "tail" and (not params.get("child_ref") or not params.get("expected_generation")):
        raise SubagentError(Refusal.INVALID)
