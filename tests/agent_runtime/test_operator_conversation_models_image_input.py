"""RT-CONV-MODELS-IMAGE-INPUT: ``runtime.operator.conversation.models`` facts carry the turn's
``decide_image_input_mode`` answer for the effective model, under the persona's profile config."""
from contextlib import contextmanager

import pytest

from agent_runtime import operator_session_models as models


@pytest.mark.parametrize("configured", ["native", "text"])
def test_facts_carry_the_image_input_mode_the_turn_would_decide(monkeypatch, configured):
    """Killing mutation: drop ``image_input_mode`` from ``operator_model_facts`` -> KeyError, red."""
    from hermes_cli import config as hermes_config

    seen = {}

    @contextmanager
    def session_read(params):
        yield object(), None

    @contextmanager
    def profile(instance):
        seen["profile"] = True
        yield

    settings = {"model": {"effective_provider": "openrouter", "effective_model": "m-1", "agent_provider": "openrouter",
                          "agent_model": "m-1", "effective_reasoning_effort": None, "reasoning_effort_source": None,
                          "reasoning_capabilities": None, "model_is_default": True}}
    monkeypatch.setattr(models, "inspect_operator_settings", lambda params: settings)
    monkeypatch.setattr(models, "operator_session_read", session_read)
    monkeypatch.setattr(models, "operator_model_inventory", lambda instance: {})
    monkeypatch.setattr(models, "facts", lambda session_id, info, inventory: {"session_id": session_id})
    monkeypatch.setattr(models, "_model_profile", profile)
    monkeypatch.setattr(hermes_config, "load_config_readonly",
                        lambda *a, **k: {"agent": {"image_input_mode": configured}})
    monkeypatch.setattr(hermes_config, "is_managed", lambda: False)

    result = models.operator_model_facts({"session_id": "s1"})

    assert result["facts"]["image_input_mode"] == configured
    assert seen["profile"] is True  # read under the persona's profile, not the serve's


def test_no_resolved_model_reports_none():
    assert models._image_input_mode(object(), "", "m") is None
