"""``providers.<name>.enabled: false`` holds for the provider ``auto`` resolves to, not only the requested name."""

import pytest

from hermes_cli import runtime_provider as rp


def _config_with_ai_gateway(monkeypatch, *, enabled: bool) -> None:
    monkeypatch.setattr(rp._config_mod, "load_config",
                        lambda: {"providers": {"ai-gateway": {"enabled": enabled}}})
    monkeypatch.setattr(rp, "resolve_provider", lambda *a, **k: "ai-gateway")
    monkeypatch.setattr(rp, "_get_model_config", lambda: {})
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-ai-gw-key")


def test_auto_does_not_resolve_to_a_disabled_provider(monkeypatch):
    """The disabled guard ran only against the REQUESTED name, so ``auto`` (never a key under
    ``providers:``) walked the ladder onto ``providers.<name>.enabled: false`` and sent the turn
    there anyway. The ladder's pick is now held to the same guard."""
    _config_with_ai_gateway(monkeypatch, enabled=False)

    with pytest.raises((ValueError, rp.AuthError), match="providers.ai-gateway.enabled: false"):
        rp.resolve_runtime_provider(requested="auto")


def test_auto_still_resolves_to_an_enabled_provider(monkeypatch):
    _config_with_ai_gateway(monkeypatch, enabled=True)

    assert rp.resolve_runtime_provider(requested="auto")["provider"] == "ai-gateway"
