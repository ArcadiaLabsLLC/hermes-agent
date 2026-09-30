"""Model defaults from existing profile configuration, never a second store."""
from __future__ import annotations

from pathlib import Path

from .session_facts import model_key

__layer__ = "lanes"


def default_target(home: Path, auth_home: Path | None) -> dict[str, str]:
    from agent_runtime.provider_configuration import configuration_at

    model = configuration_at(home).get("model")
    if not model and auth_home is not None and auth_home != home:
        model = configuration_at(auth_home).get("model")
    if isinstance(model, str):
        return {"model": model} if model else {}
    if not isinstance(model, dict):
        return {}
    return {key: value for key, value in (
        ("model", model.get("default") or model.get("name")), ("provider", model.get("provider")),
    ) if isinstance(value, str) and value.strip()}


def default_id(home: Path, auth_home: Path | None) -> str | None:
    target = default_target(home, auth_home)
    if target.get("provider") and target.get("model"):
        return model_key(target["provider"], target["model"])
    return None
