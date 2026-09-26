"""Shared run identity and safe refusal values."""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .definition_store import _encode
from .definitions import DefinitionError, ParticipantRef

__layer__ = "stores"


class DiscussionError(ValueError):
    def __init__(self, reason: str, **details: Any) -> None:
        self.reason, self.details = reason, details
        super().__init__(reason.replace("_", " "))


def text(value: Any, *, field: str, max_bytes: int = 12000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DefinitionError("invalid_text", field)
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise DefinitionError("invalid_text", field) from exc
    if size > max_bytes or "\x00" in value:
        raise DefinitionError("invalid_text", field)
    return value.strip()


def digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_encode(value).encode("utf-8")).hexdigest()


def member_id(ref: ParticipantRef) -> str:
    return "m-" + digest(ref.to_dict())[:24]


def native_session_id(run_id: str, instance_id: str) -> str:
    # Native ownership parser uses the final twelve hex characters.
    suffix = digest({"run_id": run_id, "instance_id": instance_id})[:12]
    return f"persona_chat_{instance_id}_{suffix}"
