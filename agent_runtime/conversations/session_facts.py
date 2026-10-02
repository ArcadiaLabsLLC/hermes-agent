"""Native model/context projection. No provider catalog or defaults of our own."""
from __future__ import annotations

import shlex

from .model import ConversationError, Refusal
from ..session_model_catalog import choices

__layer__ = "lanes"


def select(peer, native_id: str, choice: str, inventory: dict, *, save_default: bool = False) -> None:
    selected = choices(inventory).get(choice)
    if selected is None:
        raise ConversationError(Refusal.INVALID_REQUEST)
    provider, model = selected
    value = shlex.join([model, "--provider", provider, "--global" if save_default else "--session"])
    result = peer.call("config.set", {"session_id": native_id, "key": "model", "value": value})
    if result.get("confirm_required") or result.get("deferred"):
        raise ConversationError(Refusal.NATIVE_REFUSAL)
