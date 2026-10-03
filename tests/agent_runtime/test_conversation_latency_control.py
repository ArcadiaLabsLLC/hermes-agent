"""Broken probe prerequisites must fail before timing can be interpreted."""
import pytest

from tests.agent_runtime.conversation_latency_control import (
    require_instance_registry, require_same_root,
)


def test_probe_rejects_missing_registry(monkeypatch):
    from agent_runtime import persona_chat_continuity as continuity

    monkeypatch.setattr(continuity, "persona_chat_runtime_registry", lambda: None)
    with pytest.raises(AssertionError, match="did not initialize"):
        require_instance_registry()
    registry = object()
    monkeypatch.setattr(continuity, "persona_chat_runtime_registry", lambda: registry)
    assert require_instance_registry() is registry


@pytest.mark.parametrize("record", [{}, {"root_chat_session_id": ""}, {"root_chat_session_id": "other"}])
def test_probe_rejects_missing_or_changed_root(record):
    with pytest.raises(AssertionError, match="changed or omitted"):
        require_same_root(record, "original")
    assert require_same_root({"root_chat_session_id": "original"}, "original") == "original"
