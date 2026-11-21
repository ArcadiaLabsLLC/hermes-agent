"""Resolve chat identity at its existing owner; never persist another binding."""
from __future__ import annotations

from dataclasses import dataclass

from .model import Reason, WorkRefused, text

__layer__ = "lanes"


@dataclass(frozen=True)
class WorkContext:
    session: str | None
    profile: str | None
    can_start: bool = False
    assignee: str | None = None

    def wire(self):
        return {"agent_profile": self.profile, "can_start": self.can_start, "assignee": self.assignee,
                "scopes": ["conversation", *(["agent"] if self.profile else []), "all"]}


def resolve(reference, client, caller, install):
    if not isinstance(reference, dict):
        raise WorkRefused(Reason.INVALID)
    # ``native`` (a profile-scoped conversation) is retired with its turn path (RT-ONE-TURN-ENGINE-FOR-OPERATOR-
    # CHAT-AND-INTELLIGENCE-CHAT): every chat a work item names is an operator chat.
    resolver = {"operator": _operator}.get(reference.get("kind"))
    if resolver is None:
        raise WorkRefused(Reason.INVALID)
    return resolver(reference, text(client), caller, install)


def _operator(reference, client, caller, install):
    from agent_runtime.operator_conversation import (
        OperatorConversationRefused, validate_operator_conversation,
    )

    try:
        validate_operator_conversation({**reference, "install_id": install})
    except OperatorConversationRefused as exc:
        raise WorkRefused(Reason.OWNER_CHANGED) from exc
    # The persona instance the operator is talking to IS the assignee its work goes to.
    return WorkContext(text(reference.get("session_id"), maximum=512), None, True,
                       assignee=f"persona:{text(reference.get('persona_instance_id'), maximum=512)}")
