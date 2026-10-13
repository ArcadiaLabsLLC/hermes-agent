"""Read-only, profile-scoped reasoning facts from existing provider authorities."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Any

__layer__ = "stores"
logger = logging.getLogger(__name__)


class ReasoningSupport(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ReasoningCapabilities:
    provider: str | None
    model: str | None
    state: ReasoningSupport = ReasoningSupport.UNKNOWN
    levels: tuple[str, ...] | None = None
    default_effort: str | None = None
    source: str = "not_reported"
    api_mode: str | None = None
    unrecognised_levels: tuple[str, ...] = ()
    provider_default_effort: str | None = None
    descriptions: dict[str, str] = field(default_factory=dict)

    def wire(self) -> dict[str, Any]:
        return {
            "provider": self.provider, "model": self.model,
            "state": self.state.value,
            "levels": list(self.levels) if self.levels is not None else None,
            "default_effort": self.default_effort, "source": self.source,
            "api_mode": self.api_mode,
            "unrecognised_levels": list(self.unrecognised_levels),
            "provider_default_effort": self.provider_default_effort,
            "descriptions": dict(self.descriptions),
        }


def _levels(values: Any) -> tuple[tuple[str, ...] | None, tuple[str, ...]]:
    """Order native write vocabulary; preserve new provider terms for inspection."""
    if not isinstance(values, (tuple, list)):
        return None, ()
    from agent.reasoning_effort import EFFORT_LADDER

    reported = tuple(dict.fromkeys(v.strip().lower() for v in values if isinstance(v, str) and v.strip()))
    accepted = tuple(level for level in EFFORT_LADDER if level in reported)
    return accepted, tuple(level for level in reported if level not in EFFORT_LADDER)


def reasoning_capabilities(
    provider: str | None, model: str | None, *, api_mode: str | None = None,
    default_effort: str | None = None, config: dict | None = None,
    base_url: str | None = None,
) -> ReasoningCapabilities:
    """No HTTP, credential resolution or invented default. Call in the owning profile scope.

    Serving-catalog facts win over reference metadata. Provider declarations and
    transport vocabularies remain their existing owners; clients register no models.
    A missing level list is distinct from a definitive unsupported model.
    """
    base = dict(provider=provider, model=model, api_mode=api_mode, default_effort=default_effort)
    if not provider or not model:
        return ReasoningCapabilities(**base)
    try:
        from agent.models_dev import get_model_capabilities
        from providers import get_provider_profile

        profile = get_provider_profile(provider.strip().lower())
        canonical = profile.name if profile is not None else provider.strip().lower()
        metadata = get_model_capabilities(provider, model, allow_network=False, config=config)
        if metadata is None and provider != canonical:
            metadata = get_model_capabilities(canonical, model, allow_network=False, config=config)
        support = metadata.supports_reasoning if metadata is not None else None
        source = "model_metadata" if support is not None else "not_reported"
        from hermes_cli.models_reasoning_caps import cached_control_capabilities
        catalog = cached_control_capabilities(canonical, model, base_url=base_url)
        if catalog is not None:
            support = catalog.get("supports_reasoning")
            source = "provider_catalog"
            if support is False:
                base["default_effort"] = None
                return ReasoningCapabilities(**base, state=ReasoningSupport.UNSUPPORTED, levels=(), source=source)
            levels, unrecognised = _levels(catalog.get("supported_efforts"))
            if levels is not None:
                if catalog.get("mandatory"):
                    levels = tuple(level for level in levels if level != "none")
                if canonical == "openai-codex" and api_mode == "codex_app_server" and "max" in levels:
                    levels = (*levels, "ultra")
                provider_default = catalog.get("default_effort")
                if base["default_effort"] is None and isinstance(provider_default, str):
                    base["default_effort"] = provider_default
                return ReasoningCapabilities(**base, state=ReasoningSupport.SUPPORTED, levels=levels,
                                             source=source, unrecognised_levels=unrecognised,
                                             provider_default_effort=provider_default,
                                             descriptions=catalog.get("descriptions") or {})
        if support is False:
            base["default_effort"] = None
            return ReasoningCapabilities(**base, state=ReasoningSupport.UNSUPPORTED, levels=(), source=source)

        from agent.transports.codex import declared_reasoning_efforts
        declared = declared_reasoning_efforts(provider, model, base_url)
        if declared is not None:
            levels, unrecognised = _levels(declared)
            if canonical == "openai-codex" and api_mode == "codex_app_server" and "max" in levels:
                levels = (*levels, "ultra")
            state = ReasoningSupport.SUPPORTED if declared else ReasoningSupport.UNSUPPORTED
            if not declared:
                base["default_effort"] = None
            return ReasoningCapabilities(**base, state=state, levels=levels,
                                         source="provider_profile", unrecognised_levels=unrecognised)

        # These are the vocabulary the existing Responses transport actually accepts,
        # not a Console generation check or a second model registry.
        if canonical == "openai-codex" or api_mode in ("codex_responses", "codex_app_server"):
            from agent.reasoning_effort import route_supported_efforts, codex_supported_efforts
            from hermes_cli.models import github_model_reasoning_efforts

            if support is True or github_model_reasoning_efforts(model):
                levels = (route_supported_efforts(canonical, model, api_mode)
                          if canonical == "openai-codex" else codex_supported_efforts(model))
                return ReasoningCapabilities(**base, state=ReasoningSupport.SUPPORTED,
                                             levels=levels, source="runtime_transport")
        if canonical == "copilot":
            from hermes_cli.models import github_model_reasoning_efforts

            levels, unrecognised = _levels(github_model_reasoning_efforts(model))
            if levels:
                return ReasoningCapabilities(**base, state=ReasoningSupport.SUPPORTED,
                                             levels=levels, source="provider_profile",
                                             unrecognised_levels=unrecognised)
        return ReasoningCapabilities(**base,
            state=ReasoningSupport.SUPPORTED if support is True else ReasoningSupport.UNKNOWN,
            source=source)
    except Exception:
        # Capability inspection must not break the existing model/effort read path.
        logger.debug("Reasoning capability inspection unavailable", exc_info=True)
        return ReasoningCapabilities(**base, source="lookup_unavailable")
