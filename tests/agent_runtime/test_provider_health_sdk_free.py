"""A profile with no provider SDK does not refuse a turn for an SDK the SDK-free client replaces.

RT-PHONE-TURN-REFUSED-FOR-A-PROVIDER-SDK-THE-PHONE-DOES-NOT-USE: from a phone bundle every turn ended
"dependency preflight failed before token spend: runtime_dependency_missing:openai", because the
preflight probed ``find_spec("openai")`` and the phone's ``openai`` stand-in has no ``__spec__``.

Killing mutation (applied, red recorded, reverted — see the commit message): drop the
``_sdk_free_replaced()`` filter in ``provider_health_for_personas`` → the first case reddens.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import provider_health


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


def test_sdks_off_requires_only_what_the_sdk_free_client_cannot_replace(monkeypatch, nothing_installed):
    _sdks(monkeypatch, False)
    personas = [_persona("openai", "codex_responses"), _persona("anthropic", "anthropic_messages"),
                _persona("bedrock", "bedrock_converse")]
    health = provider_health.provider_health_for_personas(personas)
    assert health["required_packages"] == ["boto3"], health
    assert [issue["package"] for issue in health["issues"]] == ["boto3"]


def test_sdks_on_still_requires_the_sdks(monkeypatch, nothing_installed):
    _sdks(monkeypatch, True)  # the desktop: the SDK is how the turn talks to the provider
    health = provider_health.provider_health_for_personas([_persona("openai", "codex_responses")])
    assert health["required_packages"] == ["openai"] and not health["ok"], health
