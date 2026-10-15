"""Trusted auxiliary conversations share native admission, not the default pointer.

Only an in-process owner may bind a particular (instance, session) pair. Nothing
in the CLI/RPC arguments enables this scope. Room turns must not save the stale
instance row they read before an operator selected a different chat.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator

__layer__ = "policy"


@dataclass(frozen=True, slots=True)
class AuxiliaryChat:
    instance_id: str
    session_id: str


_SCOPE: ContextVar[AuxiliaryChat | None] = ContextVar("native_auxiliary_chat", default=None)


@contextmanager
def auxiliary_chat(instance_id: str, session_id: str) -> Iterator[None]:
    from .persona_assignments.identity import chat_session_owner_instance_id

    if not instance_id or chat_session_owner_instance_id(session_id) != instance_id:
        raise ValueError("auxiliary chat must name its exact native owner")
    token = _SCOPE.set(AuxiliaryChat(instance_id, session_id))
    try:
        yield
    finally:
        _SCOPE.reset(token)


def is_auxiliary_chat(instance_id: str | None, session_id: str | None) -> bool:
    scope = _SCOPE.get()
    return scope is not None and (scope.instance_id, scope.session_id) == (instance_id, session_id)


def safe_auxiliary_result(value: Any) -> dict[str, Any] | None:
    """Bound the native commit's recovery metadata, without credentials or tokens."""
    if not isinstance(value, dict) or set(value) != {"clarify"}:
        return None
    raw = value["clarify"]
    if raw is None:
        return {"clarify": None}
    if not isinstance(raw, dict) or not isinstance(raw.get("question"), str):
        return None
    question = raw["question"].strip()[:2000]
    if not question:
        return None
    choices = raw.get("choices") or []
    if not isinstance(choices, list):
        return None
    return {"clarify": {"question": question, "choices": [
        choice[:300] for choice in choices[:4] if isinstance(choice, str) and choice.strip()]}}


def auxiliary_result_metadata(instance_id: str, session_id: str, raw: Any) -> dict[str, Any]:
    if not is_auxiliary_chat(instance_id, session_id):
        return {}
    result = safe_auxiliary_result({"clarify": raw.get("clarify_request") if isinstance(raw, dict) else None})
    if result is None:
        raise ValueError("invalid native auxiliary result")
    return {"auxiliary_result": result}
