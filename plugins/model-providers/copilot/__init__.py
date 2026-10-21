"""Copilot / GitHub Models provider profile.

Core routes GPT-5+/Codex -> codex_responses and Claude -> anthropic_messages;
this profile covers the chat_completions remainder: editor attribution headers
(copilot_default_headers()) and catalog-gated GitHub Models reasoning.
"""

import time
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


def _cached_catalog() -> list[dict[str, Any]] | None:
    """The catalog ``fetch_github_model_catalog`` last cached, while fresh; never fetches (read-only)."""
    from hermes_cli import models

    cached = models._github_model_catalog_cache
    if cached is None or time.monotonic() - models._github_model_catalog_cache_time >= models._GITHUB_MODEL_CATALOG_CACHE_TTL:
        return None
    return cached


class CopilotProfile(ProviderProfile):
    """GitHub Copilot / GitHub Models — editor headers + reasoning."""

    def supported_reasoning_efforts(self, model: str | None) -> tuple[str, ...] | None:
        """The levels the cached Copilot catalog advertises for *model* (``()`` when its structured
        entry advertises none); ``None`` while the catalog is cold or does not list the model, so
        the transport keeps its own vocabulary. Never fetches: this runs per request."""
        from hermes_cli.models import github_model_reasoning_efforts, normalize_copilot_model_id

        catalog = _cached_catalog()
        if not catalog or not model:
            return None
        normalized = normalize_copilot_model_id(model, catalog=catalog)
        entry = next((item for item in catalog if item.get("id") == normalized), None)
        if entry is None or not isinstance(entry.get("capabilities"), dict):
            return None
        return tuple(github_model_reasoning_efforts(model, catalog=catalog))

    def build_api_kwargs_extras(
        self, *, model: str | None = None, reasoning_config: dict | None = None,
        supports_reasoning: bool = False, **ctx,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not (supports_reasoning and model):
            return {}, {}
        try:
            from hermes_cli.models import clamp_github_reasoning_effort, github_model_reasoning_efforts

            supported = self.supported_reasoning_efforts(model)
            if supported is None:
                supported = github_model_reasoning_efforts(model)
            if not supported:
                return {}, {}
            if not reasoning_config:
                return {"reasoning": {"effort": "medium"}}, {}
            # Never drop straight to medium, which inverted the ladder (ultra < high). See #74295.
            effort = clamp_github_reasoning_effort(reasoning_config.get("effort"), supported)
            return {"reasoning": {"effort": effort}}, {}
        except Exception:
            return {}, {}


copilot = CopilotProfile(
    name="copilot", aliases=("github-copilot", "github-models", "github-model", "github"),
    env_vars=("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"), base_url="https://api.githubcopilot.com",
    auth_type="copilot",
)

register_provider(copilot)
