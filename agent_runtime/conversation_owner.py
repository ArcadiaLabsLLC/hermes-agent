"""Opaque client ownership in native session metadata; no account directory."""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

__layer__ = "models"


class ConversationOwnerError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def client_scope(value: Any) -> str | None:
    """A Launcher digest is a namespace, never a credential or user ID."""
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ConversationOwnerError("invalid_client_scope")
    return value


def session_client_scope(row: Mapping[str, Any]) -> str | None:
    if not isinstance(row, Mapping):
        raise ConversationOwnerError("conversation_owner_unreadable")
    config = row.get("model_config") or {}
    try:
        if isinstance(config, str):
            config = json.loads(config)
        if not isinstance(config, Mapping):
            raise ValueError()
        return client_scope(config.get("client_scope"))
    except (ValueError, TypeError) as exc:
        raise ConversationOwnerError("conversation_owner_unreadable") from exc


def require_session_owner(row: Mapping[str, Any], expected: str | None) -> str | None:
    owner = session_client_scope(row)
    # Unscoped native operator calls retain their existing authority. Scoped
    # clients cannot adopt legacy sessions or another client's transcript.
    if client_scope(expected) is not None and expected != owner:
        raise ConversationOwnerError("conversation_owner_changed")
    return owner


def request_client_scope(params: Mapping[str, Any]) -> str | None:
    owner = client_scope(params.get("client_scope"))
    if "client_scope" in params and owner is None:
        raise ConversationOwnerError("invalid_client_scope")
    return owner
