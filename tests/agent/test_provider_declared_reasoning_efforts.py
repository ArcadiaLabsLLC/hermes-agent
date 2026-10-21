"""The route's entry clamp and the providers' declared reasoning vocabularies are one fact.

``ProviderProfile.supported_reasoning_efforts`` is the door a provider declares its levels
through. ``route_supported_efforts`` reads the ``openai-codex`` declaration (falling back to the
static ladder), the ``openai-codex`` profile declares the per-generation Codex ladder, and the
Copilot profile declares what its cached ``/models`` catalog advertises, never fetching.
"""

from __future__ import annotations

import time

import pytest

from agent.reasoning_effort import CODEX_GPT56_EFFORTS, CODEX_LEGACY_EFFORTS, route_supported_efforts


@pytest.fixture
def profiles():
    import model_tools  # plugin discovery registers the provider profiles
    import providers

    return providers.get_provider_profile("openai-codex"), providers.get_provider_profile("copilot")


def test_the_codex_profile_declares_the_per_generation_ladder(profiles):
    codex, _ = profiles
    assert codex.supported_reasoning_efforts("gpt-5.6") == CODEX_GPT56_EFFORTS
    assert codex.supported_reasoning_efforts("gpt-5.5") == CODEX_LEGACY_EFFORTS


def test_the_route_clamp_reads_the_codex_declaration(profiles, monkeypatch):
    codex, _ = profiles
    assert route_supported_efforts("openai-codex", "gpt-5.6") == CODEX_GPT56_EFFORTS
    monkeypatch.setattr(codex, "supported_reasoning_efforts", lambda model: ("low", "max"))
    assert route_supported_efforts("openai-codex", "gpt-5.6") == ("low", "max")
    assert route_supported_efforts("openai-codex", "gpt-5.6", "codex_app_server") == ("low", "max", "ultra")
    # Undeclared (None) keeps the static ladder.
    monkeypatch.setattr(codex, "supported_reasoning_efforts", lambda model: None)
    assert route_supported_efforts("openai-codex", "gpt-5.5") == CODEX_LEGACY_EFFORTS


def test_copilot_declares_its_cached_catalog_and_never_fetches(profiles, monkeypatch):
    from hermes_cli import models

    _, copilot = profiles
    monkeypatch.setattr(models, "fetch_github_model_catalog", lambda *a, **k: pytest.fail("fetched"))
    monkeypatch.setattr(models, "_github_model_catalog_cache", None)
    assert copilot.supported_reasoning_efforts("gpt-6-sol") is None  # cold: undeclared

    catalog = [
        {"id": "gpt-6-sol", "capabilities": {"supports": {"reasoning_effort": ["low", "medium", "high", "max"]}}},
        {"id": "gpt-4.1", "capabilities": {"supports": {}}},
    ]
    monkeypatch.setattr(models, "_github_model_catalog_cache", catalog)
    monkeypatch.setattr(models, "_github_model_catalog_cache_time", time.monotonic())
    assert copilot.supported_reasoning_efforts("gpt-6-sol") == ("low", "medium", "high", "max")
    assert copilot.supported_reasoning_efforts("gpt-4.1") == ()  # the catalog advertises none
    assert copilot.supported_reasoning_efforts("not-listed") is None

    monkeypatch.setattr(models, "_github_model_catalog_cache_time",
                        time.monotonic() - models._GITHUB_MODEL_CATALOG_CACHE_TTL - 1)
    assert copilot.supported_reasoning_efforts("gpt-6-sol") is None  # stale: undeclared
