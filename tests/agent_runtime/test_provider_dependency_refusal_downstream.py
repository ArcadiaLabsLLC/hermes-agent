"""Dependency preflight evidence survives the actual turn mapper and journal."""
from types import SimpleNamespace

import pytest

from agent_runtime import provider_health
from agent_runtime.mission_chat_outcome import classify_turn_failure
from agent_runtime.mission_chat_turns import safe_provider_refusal


def test_dependency_preflight_maps_to_typed_terminal_refusal(monkeypatch):
    persona = SimpleNamespace(provider="opencode-zen", model="claude-opus")
    kinds = (
        "runtime_dependency_missing", "runtime_dependency_corrupt",
        "runtime_dependency_metadata_conflict", "runtime_dependency_metadata_unreadable",
        "runtime_dependency_shadowed",
    )
    for kind in kinds:
        issues = [{"kind": kind, "package": "anthropic", "summary": "hermes pm install --extra anthropic"}]
        monkeypatch.setattr(provider_health, "provider_health_for_persona", lambda _: {"ok": False, "issues": issues})
        with pytest.raises(ImportError) as caught:
            provider_health.assert_provider_health_for_persona(persona)
        for submitted in (False, True):
            outcome = classify_turn_failure(caught.value, provider_submitted=submitted, request_started=False)
            assert outcome.error_kind == "chat_turn_provider_unavailable"
            assert outcome.execution_state == "failed" and outcome.exit_code == 2
            block = outcome.provider_refusal.as_dict()
            assert block["status_code"] == 0 and block["reason"] == kind
            assert block["provider"] == "opencode-zen" and block["model"] == "claude-opus"
            assert block["missing_packages"] == ["anthropic"]
            assert block["repair_hint"] == issues[0]["summary"]
            assert safe_provider_refusal(block) == block
            assert "hermes pm install --extra anthropic" in outcome.provider_refusal.next_expected()
    fallback = classify_turn_failure(ImportError("not configured"), provider_submitted=True, request_started=False)
    assert fallback.provider_refusal.reason == "provider_unavailable"
    assert "missing_packages" not in fallback.provider_refusal.as_dict()
