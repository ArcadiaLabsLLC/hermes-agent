"""RT-CHAT-HEAD-CH5-RELAY-HEAD — a relay turn runs on the TARGET instance's head.

Plan: ``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md``
§2.5. The relay context records the operator who started the nested turn; a
``per_profile`` target answers its own head above it.
"""

from __future__ import annotations

import pytest

from agent_runtime.chat_session_scope import (
    ChatHeadSource,
    resolve_chat_session_scope,
    resolve_conversation_chat_scope,
    resolve_instance_chat_scope,
)
from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE, CHAT_HEAD_KIND_PROCESS
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.profile_home import record_hermes_head_home_if_unset, reset_hermes_head_home

TARGET_ROOT = "persona_chat_personainst_qa_0123456789ab"


@pytest.fixture
def relayed(tmp_path, monkeypatch):
    """Env head ``profiles/base``; a nested relay turn recorded under ``profiles/operator``."""

    root = tmp_path / ".hermes"
    homes = {name: root / "profiles" / name for name in ("base", "operator", "alice")}
    for path in (root / "agent-runtime", *homes.values()):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root / "agent-runtime"))
    monkeypatch.setenv("HERMES_HOME", str(homes["base"]))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(homes["base"]))
    token = record_hermes_head_home_if_unset(homes["operator"])
    try:
        yield homes
    finally:
        reset_hermes_head_home(token)


def _target(kind: str, home):
    store = PersonaInstanceStore()
    instance = store.open_chat(persona_id="qa", session_id=TARGET_ROOT)
    instance.chat_head_home = str(home)
    instance.chat_head_kind = kind
    return store.update(instance)


def test_a_relay_turn_to_a_per_profile_target_runs_on_the_targets_head(relayed):
    instance = _target(CHAT_HEAD_KIND_PER_PROFILE, relayed["alice"])

    for scope in (
        resolve_chat_session_scope(session_id=TARGET_ROOT),
        resolve_instance_chat_scope(instance),
        resolve_conversation_chat_scope(session_id=TARGET_ROOT),
    ):
        assert scope.head_home == relayed["alice"]
        assert scope.source is ChatHeadSource.INSTANCE_RECORDED
        assert scope.per_profile


def test_positive_control_a_relay_turn_to_a_process_target_stays_on_the_operators_head(relayed):
    """Same relay, one variable changed: the target's kind. The relay head must win."""

    instance = _target(CHAT_HEAD_KIND_PROCESS, relayed["alice"])

    for scope in (
        resolve_chat_session_scope(session_id=TARGET_ROOT),
        resolve_instance_chat_scope(instance),
        resolve_conversation_chat_scope(session_id=TARGET_ROOT),
    ):
        assert scope.head_home == relayed["operator"]
        assert scope.source is ChatHeadSource.RELAY_CONTEXT
