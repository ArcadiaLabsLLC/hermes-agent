"""A phone agent is not shown as missing a provider library the phone never uses.

RT-PHONE-AGENT-READINESS-ASKS-FOR-PROVIDER-LIBRARIES-THE-PHONE-DOES-NOT-USE: read 2026-11-19 from a
bundled-phone android_x86_64 bundle under ``python -I -S`` with the phone profile's config — the turn
preflight passed an openai-mode persona while its readiness read "Missing runtime packages: openai".
Both now ask ``agent.transports.httpx_client.packages_this_build_needs``, the one answer.

Killing mutation (applied, red recorded, reverted — see the commit message): skip
``packages_this_build_needs`` in ``profile_readiness._runtime_dependency_issue`` → the first case reddens.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import profile_readiness, provider_health


def _persona(provider: str, api_mode: str):
    return SimpleNamespace(provider=provider, api_mode=api_mode, model="m")


@pytest.fixture()
def nothing_installed(monkeypatch):
    from hermes_cli import runtime_environment

    monkeypatch.setattr(runtime_environment, "module_available", lambda _module: False)


def _sdks(monkeypatch, enabled: bool) -> None:
    from hermes_cli import config_switches

    monkeypatch.setattr(config_switches, "config_switch",
                        lambda section, key, default=True: enabled if (section, key) == ("agent", "provider_sdks")
                        else default)


def test_sdk_free_readiness_names_no_replaced_sdk_but_keeps_the_rest(monkeypatch, nothing_installed):
    _sdks(monkeypatch, False)
    assert profile_readiness._runtime_dependency_issue(_persona("openai-api", "codex_responses")) is None
    assert profile_readiness._runtime_dependency_issue(_persona("anthropic", "anthropic_messages")) is None
    issue = profile_readiness._runtime_dependency_issue(_persona("bedrock", "bedrock_converse"))
    assert issue is not None and "boto3" in issue[1], issue
    issue = profile_readiness._runtime_dependency_issue(_persona("vertex", ""))
    assert issue is not None and "google-auth" in issue[1], issue


def test_readiness_and_the_turn_preflight_give_one_answer(monkeypatch, nothing_installed):
    for enabled in (False, True):
        _sdks(monkeypatch, enabled)
        for persona in (_persona("openai-api", "codex_responses"), _persona("anthropic", "anthropic_messages"),
                        _persona("bedrock", "bedrock_converse")):
            ready = profile_readiness._runtime_dependency_issue(persona) is None
            assert ready == provider_health.provider_health_for_personas([persona])["ok"], (enabled, persona)


def test_sdks_on_readiness_still_names_the_sdk(monkeypatch, nothing_installed):
    _sdks(monkeypatch, True)  # the desktop: the SDK is how the turn talks to the provider
    issue = profile_readiness._runtime_dependency_issue(_persona("openai-api", "codex_responses"))
    assert issue is not None and "openai" in issue[1], issue
