"""Legacy profile-backed groups: the scope and member addresses a saved one still carries.

A profile group ran its members on profile-scoped conversations; that path is retired
(RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT, owner 2026-11-21). No group is started
any more. A saved one keeps its private scope (so its room still reads) until ``group_migration``
adopts it into an agent room, which reads each member's transcript through :func:`member_scope`.
"""
from __future__ import annotations

from typing import Any, Mapping

from agent_runtime.conversations.model import ConversationScope
from .definitions import identifier
from .run_values import digest

__layer__ = "stores"

SCOPE_PREFIX = "conversation-scope-"


def group_scope(actor: str, client: str) -> str:
    identifier(client, "client_scope")
    return SCOPE_PREFIX + digest({"actor": actor, "client": client})[:40]


def is_group_scope(value: str) -> bool:
    return value.startswith(SCOPE_PREFIX)


def member_scope(run: Mapping[str, Any], member: Mapping[str, Any]) -> ConversationScope:
    group = run["initial"]["group"]
    return ConversationScope(group["actor"], group["client"], member["profile"])
