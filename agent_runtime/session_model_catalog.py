"""Provider-owned model choices projected for native conversation clients."""
from __future__ import annotations

import json

__layer__ = "lanes"


def model_key(provider: str, model: str) -> str:
    return json.dumps([provider, model], ensure_ascii=False, separators=(",", ":"))


def provider_id(row: dict) -> str | None:
    slug = row.get("slug")
    if not isinstance(slug, str):
        return None
    if row.get("is_user_defined"):
        from hermes_cli.providers import custom_provider_slug
        return custom_provider_slug(slug, slug)
    return slug


def choices(inventory: dict) -> dict[str, tuple[str, str]]:
    result = {}
    for provider in inventory.get("providers", ()):
        slug = provider_id(provider)
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
    labels = {provider_id(row): row.get("name") or row["slug"]
              for row in inventory.get("providers", ()) if isinstance(row.get("slug"), str)}
    connected = {provider_id(row) for row in inventory.get("providers", ())
                 if row.get("authenticated") is not False}
    return {"session_id": conversation_id, "current_model_id": current,
            "model_selection_required": not model or provider not in connected,
            "models": [{"id": key, "label": model, "provider_id": provider,
                        "provider_label": labels[provider]}
                       for key, (provider, model) in offered.items()],
            "usage": info.get("usage") or {},
            "provider_usage": provider_usage(inventory)}


def provider_usage(inventory: dict) -> dict[str, dict]:
    """Each signed-in provider's account usage, exactly as upstream's picker carries it.

    ``hermes_cli.inventory`` attaches ``usage`` from its cache only (a background refresh is
    queued, never awaited): ``{"windows": [...]}`` for a single-account provider, or
    ``{"accounts": [{id, label, windows, state, resets_at}]}`` for a multi-entry credential
    pool, each window ``{label, used_percent, resets_at, scope}``. A provider with no fresh
    snapshot is absent — never a guessed gauge. Usage is a percent: no upstream fetcher
    reports an absolute used/limit pair."""
    result = {}
    for row in inventory.get("providers", ()):
        slug, usage = provider_id(row), row.get("usage")
        if isinstance(slug, str) and isinstance(usage, dict) and usage:
            result[slug] = usage
    return result
