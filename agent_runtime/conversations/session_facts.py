"""Native model/context projection. No provider catalog or defaults of our own."""
from __future__ import annotations

import json
import shlex

from .model import ConversationError, Refusal

__layer__ = "lanes"


def model_key(provider: str, model: str) -> str:
    return json.dumps([provider, model], ensure_ascii=False, separators=(",", ":"))


def choices(inventory: dict) -> dict[str, tuple[str, str]]:
    result = {}
    for provider in inventory.get("providers", ()):
        slug = provider.get("slug")
        if not isinstance(slug, str) or provider.get("authenticated") is False:
            continue
        unavailable = provider.get("unavailable_models") or []
        for model in provider.get("models", ()):
            if isinstance(model, str) and model not in unavailable:
                result[model_key(slug, model)] = (slug, model)
    return result


def facts(conversation_id: str, snapshot: dict, inventory: dict) -> dict:
    info = snapshot.get("info") or {}
    provider, model = info.get("provider"), info.get("model")
    current = model_key(provider, model) if provider and model else None
    offered = choices(inventory)
    return {"session_id": conversation_id, "current_model_id": current,
            "models": [{"id": key, "label": f"{model} · {provider}"}
                       for key, (provider, model) in offered.items()],
            "usage": info.get("usage") or {}}


def select(peer, native_id: str, choice: str, inventory: dict) -> None:
    selected = choices(inventory).get(choice)
    if selected is None:
        raise ConversationError(Refusal.INVALID_REQUEST)
    provider, model = selected
    value = shlex.join([model, "--provider", provider, "--session"])
    result = peer.call("config.set", {"session_id": native_id, "key": "model", "value": value})
    if result.get("confirm_required") or result.get("deferred"):
        raise ConversationError(Refusal.NATIVE_REFUSAL)
