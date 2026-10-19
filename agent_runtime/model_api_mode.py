"""The ``api_mode`` a provider/model pair runs on — one rule for a persisted pick and a turn.

``api_mode`` belongs to the PROVIDER it was chosen with: ``anthropic_messages`` is right for
``anthropic`` and wrong for ``openai-codex``, whose client then POSTs to ``…/codex/v1/messages``
and Cloudflare answers 403 (runtime-queue RT-CONV-MODEL-SELECT-STALE-API-MODE, 2026-10-19). So a
tier that names a provider carries its own api_mode only while that provider is the one running;
a chat override onto another provider derives the api_mode from the provider it selected, by
the rule ``persona set-model`` persists (``hermes_cli/harness_parts/persona/
model_and_skills_commands.py::_model_api_mode`` delegates here).
"""
from __future__ import annotations

__layer__ = "stores"


def model_api_mode(provider: str | None, model: str | None, profile_api_mode: str | None) -> str | None:
    """The ``api_mode`` persisted beside *model*. An OpenCode family routes PER MODEL
    (``opencode_model_api_mode``: Claude on ``anthropic_messages``, GPT on ``codex_responses``), so
    its provider profile's single ``api_mode`` is right for one model at most; every other
    provider keeps the profile's."""
    from hermes_cli.models import opencode_model_api_mode, opencode_provider_family

    if provider and model and opencode_provider_family(provider):
        return opencode_model_api_mode(provider, model)
    return profile_api_mode


def _provider_profile(provider: str | None):
    if not provider:
        return None
    from agent_runtime.local_llama_adapter import is_local_llama_provider

    if is_local_llama_provider(provider):
        from agent_runtime.local_llama_adapter.provider import provider_profile

        return provider_profile()
    from providers import get_provider_profile

    return get_provider_profile(str(provider).strip().lower())


def canonical_provider(provider: str | None) -> str | None:
    """The provider profile's name (``claude`` -> ``anthropic``), else the id as given."""
    profile = _provider_profile(provider)
    if profile is not None:
        return str(profile.name)
    return str(provider).strip().lower() if provider else None


def selected_api_mode(provider: str | None, model: str | None) -> str | None:
    """The api_mode for *provider*/*model* as a fresh selection: the provider profile's, through
    :func:`model_api_mode`. ``None`` for an unknown provider (the runtime resolver then decides)."""
    profile = _provider_profile(provider)
    if profile is None:
        return None
    profile_api_mode = str(getattr(profile, "api_mode", "") or "") or None
    return model_api_mode(str(profile.name), model, profile_api_mode)


def turn_api_mode(tier_provider: str | None, tier_api_mode: str | None,
                  provider: str | None, model: str | None) -> str | None:
    """The api_mode a turn on *provider*/*model* runs with, given the tier that supplied
    *tier_api_mode* was chosen with *tier_provider*.

    The same provider keeps the tier's api_mode (an operator's explicit choice, and an OpenCode
    relay's per-model transport is decided downstream by ``opencode_transport``). A different
    provider — a chat override onto another lane — never inherits it. With either provider
    unknown nothing says the pair moved, and the tier's value stands."""
    if (provider is None or tier_provider is None
            or canonical_provider(provider) == canonical_provider(tier_provider)):
        return tier_api_mode
    return selected_api_mode(provider, model)
