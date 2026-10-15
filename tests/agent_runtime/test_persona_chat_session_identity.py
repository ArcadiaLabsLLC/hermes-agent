"""Session bookkeeping must not invalidate actors; resolved choices must."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent_runtime.persona_chat_continuity.runtime_registry import (
    PersonaChatRuntimeRegistry,
)
from agent_runtime.persona_chat_session import (
    _chat_effective_model_payload,
    _chat_model_override_from_config,
)
from tests.agent_runtime.test_mission_chat_turn_context import (
    _Config,
    _build,
    _instance,
    _persona,
)

OVERRIDE = "mission_control_chat_model_override"
CHOICE = {"provider": "anthropic", "model": "opus", "updated_at": "before"}


def _context(config):
    persona, instance, defaults = _persona(), _instance(), _Config()
    selection = _chat_effective_model_payload(
        persona=persona,
        instance=instance,
        config=defaults,
        override=_chat_model_override_from_config(config),
    )
    return _build(session_model_config=config, model_selection=selection)


def _acquire(registry, context, factory):
    return registry.acquire(
        root_session_id="chat-root-1",
        active_session_id="chat-root-1",
        revision="same-history",
        signature=context.runtime_signature,
        signature_components=context.runtime_signature_digests,
        factory=factory,
    )


@pytest.mark.parametrize(
    "patch",
    [
        {
            "_usage_anchor": {
                "prompt_tokens": 200,
                "completion_tokens": 10,
                "base_count": 3,
            }
        },
        {"_proactive_prune_rearm_tokens": 4096},
        {"codex_thread_id": "native-thread"},
        {"future_bookkeeping": {"counter": 2}},
        {OVERRIDE: {**CHOICE, "updated_at": "after", "source": "session"}},
    ],
)
def test_bookkeeping_reuses_the_same_actor_without_mutating_session_data(patch):
    config = {OVERRIDE: dict(CHOICE)}
    updated = {**config, **patch}
    original = deepcopy(updated)
    factory = Mock(side_effect=lambda: SimpleNamespace(close=Mock()))
    registry = PersonaChatRuntimeRegistry()
    first, *_ = _acquire(registry, _context(config), factory)

    second, reused, reason, moved = _acquire(registry, _context(updated), factory)

    assert reused and second.agent is first.agent
    assert reason is None and moved == ()
    assert factory.call_count == 1
    assert updated == original


@pytest.mark.parametrize(
    "choice, component",
    [
        ({**CHOICE, "model": "sonnet"}, "model"),
        ({**CHOICE, "provider": "openai"}, "provider"),
    ],
)
def test_resolved_chat_choice_rebuilds_and_closes_the_old_actor(choice, component):
    factory = Mock(side_effect=lambda: SimpleNamespace(close=Mock()))
    registry = PersonaChatRuntimeRegistry()
    first, *_ = _acquire(registry, _context({OVERRIDE: CHOICE}), factory)

    second, reused, reason, moved = _acquire(
        registry, _context({OVERRIDE: choice}), factory
    )

    assert not reused and second.agent is not first.agent
    assert reason == "runtime_signature_changed" and component in moved
    first.agent.close.assert_called_once_with()
    assert factory.call_count == 2


def test_named_session_input_preserves_absent_null_and_value(monkeypatch):
    from agent_runtime import persona_chat_identity

    monkeypatch.setattr(
        persona_chat_identity, "SESSION_MODEL_CONFIG_IDENTITY_FIELDS", ("actor_option",)
    )
    signatures = {
        _context(config).runtime_signature
        for config in ({}, {"actor_option": None}, {"actor_option": "enabled"})
    }
    assert len(signatures) == 3
