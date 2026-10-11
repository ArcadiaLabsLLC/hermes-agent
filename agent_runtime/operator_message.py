"""Admission for operator-authored text, shared by RPC, CLI and steer."""
from typing import Any

__layer__ = "policy"

# A transport admission limit, never a post-acceptance truncation budget.
MAX_MESSAGE_LENGTH = 64_000


class OperatorMessageInvalid(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def normalize_operator_message(value: Any) -> str:
    """Validate the entire body and retain its exact whitespace and Unicode."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise OperatorMessageInvalid("message_required", "message must be a non-empty string")
    if not isinstance(value, str):
        raise OperatorMessageInvalid("message_invalid", "message must be a string")
    if len(value) > MAX_MESSAGE_LENGTH:
        raise OperatorMessageInvalid("message_invalid", f"message must be {MAX_MESSAGE_LENGTH} characters or fewer")
    return value
