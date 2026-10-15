"""Opaque account scope on the existing room admission record."""
from __future__ import annotations

from agent_runtime.conversation_owner import client_scope, ConversationOwnerError
from .run_values import DiscussionError, digest
from .definitions import identifier

__layer__ = "stores"


def room_client_scope(run):
    initial = run["initial"]
    return initial.get("client_scope", initial.get("group", {}).get("client"))


def scoped_room_key(key, owner):
    identifier(key, "idempotency_key")
    try:
        owner = client_scope(owner)
    except ConversationOwnerError as exc:
        raise DiscussionError(exc.reason) from exc
    return key if owner is None else "account-" + digest({"owner": owner, "key": key})


def require_room_owner(run, expected, *, account_access=True):
    owner = room_client_scope(run)
    if owner is not None and not account_access:
        raise DiscussionError("console_required")
    # The console tier retains its native all-owner view when no scope is sent.
    if expected is not None and owner != expected:
        raise DiscussionError("conversation_owner_changed")
