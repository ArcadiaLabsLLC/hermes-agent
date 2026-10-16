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
        from agent_runtime.reasoning_control_catalog import cached_control_capabilities
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


# ── provider-declared efforts (lane pb-r: moved out of the upstream ``agent/transports/codex.py``,
# ``agent/reasoning_effort.py`` and ``hermes_cli/models.py``; each keeps one import + one call) ──


def read_declared_efforts(profile: Any, model: str | None, base_url: Any = None, allow_warm: bool = True) -> Any:
    """``profile.supported_reasoning_efforts(model)``, threading ``allow_warm=False`` and ``base_url``
    only to a hook whose signature takes them. ``None`` profile -> ``None``.

    Called by ``agent/transports/codex.py::_profile_declared_efforts`` for the endpoint-inferred
    profile and the named one.
    """
    if profile is None:
        return None
    hook = profile.supported_reasoning_efforts
    options = {}
    if not allow_warm or base_url:
        import inspect
        parameters = inspect.signature(hook).parameters
        if not allow_warm and "allow_warm" in parameters:
            options["allow_warm"] = False
        if base_url and "base_url" in parameters:
            options["base_url"] = base_url
    return hook(model, **options)


def declared_reasoning_efforts(provider: str, model: str, base_url: str | None = None) -> tuple | None:
    """Read-only public projection of the transport's endpoint-first declaration (never warms)."""
    from agent_runtime._upstream_doors import codex_profile_declared_efforts

    return codex_profile_declared_efforts(provider, model, base_url, allow_warm=False)


def codex_declared_or_static_efforts(model: str | None) -> tuple[str, ...]:
    """The openai-codex profile's declared vocabulary, else the static Codex ladder.

    Called by ``agent/reasoning_effort.py::route_supported_efforts`` for ``openai-codex``.
    """
    from agent.reasoning_effort import codex_supported_efforts
    from providers import get_provider_profile

    profile = get_provider_profile("openai-codex")
    declared = profile.supported_reasoning_efforts(model) if profile is not None else None
    return tuple(declared) if declared is not None else codex_supported_efforts(model)


def widen_github_reasoning_efforts(model_id: str, upstream: list[str]) -> list[str]:
    """Upstream's ``_github_reasoning_efforts_for_model_id`` answer, widened to the GPT-6 tiers.

    O-series and Astra keep upstream's answer; a GPT-6 / no-disable tier answers the Codex
    tier ladder (shared vocabulary with the transport); everything else is upstream's.
    Called by ``hermes_cli/models.py::github_model_reasoning_efforts``.
    """
    raw = (model_id or "").strip().lower()
    if raw.startswith(("openai/o1", "openai/o3", "openai/o4", "o1", "o3", "o4")):
        return upstream
    from hermes_cli.models import is_astra_model, normalize_copilot_model_id

    normalized = normalize_copilot_model_id(model_id).lower()
    if is_astra_model(normalized):
        return upstream
    from agent.reasoning_effort import GPT6_TIER_PREFIXES, NO_DISABLE_TIER_PREFIXES, codex_supported_efforts

    bare = normalized.rsplit("/", 1)[-1]
    if bare.startswith((*GPT6_TIER_PREFIXES, *NO_DISABLE_TIER_PREFIXES)):
        return list(codex_supported_efforts(bare))
    return upstream
