"""Resolve chat identity at its existing owner; never persist another binding."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import Reason, WorkRefused, text

__layer__ = "lanes"


@dataclass(frozen=True)
class WorkContext:
    session: str | None
    profile: str | None
    can_start: bool = False

    def wire(self):
        return {"agent_profile": self.profile, "can_start": self.can_start,
                "scopes": ["conversation", *(["agent"] if self.profile else []), "all"]}


def resolve(reference, client, caller, install):
    if not isinstance(reference, dict):
        raise WorkRefused(Reason.INVALID)
    resolver = {"native": _native, "operator": _operator}.get(reference.get("kind"))
    if resolver is None:
        raise WorkRefused(Reason.INVALID)
    return resolver(reference, text(client), caller, install)


def _native(reference, client, caller, install):
    from agent_runtime.conversations.binding import get_service
    from agent_runtime.conversations.model import ConversationError, caller_scope

    service = get_service()
    profile = text(reference.get("profile"))
    if service.install_id != install:
        raise WorkRefused(Reason.OWNER_CHANGED)
    try:
        home = service.profile_home(profile).resolve(strict=True)
        if home != Path(text(reference.get("profile_home"), maximum=4096)).resolve(strict=True):
            raise WorkRefused(Reason.OWNER_CHANGED)
        session = reference.get("session_id")
        if session is None:
            return WorkContext(None, profile)
        route = service.store.get(text(session, maximum=512), caller_scope(caller, client, profile))
        if Path(route.home) != home:
            raise WorkRefused(Reason.OWNER_CHANGED)
        return WorkContext(route.native_id or None, profile, service.store.has_turns(route))
    except (ConversationError, OSError) as exc:
        raise WorkRefused(Reason.OWNER_CHANGED) from exc


def _operator(reference, client, caller, install):
    from agent_runtime.operator_conversation import (
        OperatorConversationRefused, validate_operator_conversation,
    )

    try:
        validate_operator_conversation({**reference, "install_id": install})
    except OperatorConversationRefused as exc:
        raise WorkRefused(Reason.OWNER_CHANGED) from exc
    # A persona instance is not a native dispatcher profile. Do not advertise
    # profile assignment as execution by that persona, even if it has a backing profile.
    return WorkContext(text(reference.get("session_id"), maximum=512), None, True)
