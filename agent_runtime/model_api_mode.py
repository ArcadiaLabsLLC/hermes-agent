"""The ``api_mode`` a provider/model pair runs on.

Moved unchanged from ``hermes_cli/harness_parts/persona/model_and_skills_commands.py::_model_api_mode``
(which now delegates here) so a runtime-layer caller can reach the rule without importing a CLI module.
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

