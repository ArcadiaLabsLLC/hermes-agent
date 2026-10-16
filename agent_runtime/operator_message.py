"""Admission for operator-authored text, shared by RPC, CLI and steer."""
from typing import Any

__layer__ = "policy"

# A transport admission limit, never a post-acceptance truncation budget.
MAX_MESSAGE_LENGTH = 64_000
#: What ``MAX_MESSAGE_LENGTH`` counts: Python ``len(str)``, one per Unicode code point
#: (not UTF-16 units, not bytes, not grapheme clusters).
MESSAGE_LENGTH_UNIT = "unicode_code_point"


def operator_text_admission() -> dict[str, Any]:
    """The admission rule a composer reads before send, from the one owner of the number.

    Advertised on the method-lane manifest (``serve_rpc.registry.manifest``'s ``limits``)
    so a client never copies the constant. A client may resolve a SMALLER limit (product
    entitlements); the server refusal below stays the final authority either way.
    """
    return {"max_length": MAX_MESSAGE_LENGTH, "unit": MESSAGE_LENGTH_UNIT}


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
