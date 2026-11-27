"""The bounded provider/model identity from one model execution."""

from __future__ import annotations

from typing import TypedDict

from .redaction import has_secret_value
from .serde import safe_text

__layer__ = "models"

ACTIVE_MODEL_ROUTE = "active_model_route"
MODEL_ROUTE = "model_route"


class ModelRoute(TypedDict):
    provider: str
    model: str


def execution_model_route(provider: object, model: object) -> ModelRoute | None:
    if not isinstance(provider, str) or not isinstance(model, str):
        return None
    provider = safe_text(provider, limit=120)
    model = safe_text(model, limit=200)
    if not provider or not model or has_secret_value(provider) or has_secret_value(model):
        return None
    return {"provider": provider, "model": model}


def read_model_route(value: object) -> ModelRoute | None:
    if not isinstance(value, dict):
        return None
    return execution_model_route(value.get("provider"), value.get("model"))
