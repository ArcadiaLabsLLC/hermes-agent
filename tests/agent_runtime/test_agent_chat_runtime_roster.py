"""Inline chat resolves the head's roster, never its sender's execution profile."""

import json
from pathlib import Path

import pytest

from agent_runtime.config import load_agent_runtime_config
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.profile_context import persona_profile_scope, process_home_scope
from agent_runtime.profile_home import (
    PersonaProfileBinding,
    get_hermes_head_home,
    hermes_head_home_is_authoritative,
)
from agent_runtime.profile_runner import AgentRunResult, ProfileAgentRunner
from hermes_cli.config import atomic_config_replace, atomic_config_write
from hermes_constants import get_hermes_home
from tools.agent_chat_tool import agent_chat_open, agent_chat_threads
from tools.registry import registry


@pytest.fixture
def relay_runtime(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    head = root / "profiles" / "base"
    homes = {
        name: root / "profiles" / name for name in ("sender_a", "sender_b", "receiver")
    }
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(head))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))
    # Only the runtime head declares the target. Sender B deliberately declares
    # an unrelated persona: reading its roster must not materialize that agent.
    for home in (head, *homes.values()):
        home.mkdir(parents=True)
        atomic_config_write(home / "config.yaml", {"toolsets": []})
    # The two seeds below REPLACE the bare config written above (dropping its
    # ``toolsets`` key on purpose), so they say so: atomic_config_write refuses
    # a write that deletes a key by omission.
    atomic_config_replace(
        head / "config.yaml",
        {
            "agent_runtime": {
                "personas": {
                    "dev": {
                        "display_name": "Runtime Developer",
                        "role": "developer",
                        "hermes_profile": "receiver",
                        "provider": "test-provider",
                        "model": "head-model",
                    }
                }
            },
        },
    )
    atomic_config_replace(
        homes["sender_b"] / "config.yaml",
        {
            "agent_runtime": {
                "personas": {"sender_only": {"display_name": "Not a runtime target"}}
            },
        },
    )
    store = PersonaInstanceStore()
    siblings = [
        store.add_instance(persona_id="dev", placement_id=f"dev_agent_{n}")
        for n in (1, 2)
    ]
    executed = []

    def model_run(self, request):
        # The real handler and GPTPersonaRuntime constructed this request. Only
        # model execution is replaced; target resolution, stores and sessions run.
        executed.append(request)
        assert get_hermes_home() == head
        assert request.profile == "receiver"
        assert request.model == "head-model"
        return AgentRunResult(
            final_response="Target acknowledged",
            session_id=request.session_id,
            provider=request.provider,
            model=request.model,
            base_url=None,
            messages=[],
        )

    monkeypatch.setattr(ProfileAgentRunner, "run", model_run)
    return head, homes, store, siblings, executed


def _send(target, **kwargs):
    return json.loads(
        registry.get_entry("agent_chat_send").handler({
            "persona_id": target,
            "message": "Please acknowledge",
            "wait": True,
            **kwargs,
        })
    )


def _sender_scope(name, homes):
    return persona_profile_scope(
        PersonaProfileBinding(
            persona_id=f"profile:{name}",
            hermes_profile=name,
            profile_home=homes[name],
            readiness="ready",
            summary="test sender",
        )
    )


def test_real_inline_relay_uses_head_roster_and_keeps_sibling_threads_distinct(
    relay_runtime,
):
    head, homes, store, siblings, executed = relay_runtime
    sessions = {}
    for sender, target in zip(
        ("sender_a", "sender_b", "sender_a"), (siblings[0], siblings[1], siblings[0])
    ):
        with _sender_scope(sender, homes):
            assert "dev" not in load_agent_runtime_config().personas
            roster = json.loads(agent_chat_threads())
            assert any(row["persona_id"] == "dev" for row in roster["threads"])
            assert not any(
                row["persona_id"] == "sender_only" for row in roster["threads"]
            )
            result = _send(target.id, new_session=False)
            assert result["ok"], result
            assert result["persona_instance_id"] == target.id
            session = result["session_id"]
            assert session == store.get(target.id).default_chat_session_id
            if target.id in sessions:
                assert session == sessions[target.id]
            sessions[target.id] = session
            opened = json.loads(
                agent_chat_open(persona_id=target.id, session_id=session)
            )
            assert opened["ok"], opened
            assert opened["session_id"] == session
            assert opened["handle"] == target.id
            assert get_hermes_home() == homes[sender]
            assert get_hermes_head_home() == head
        assert get_hermes_home() == head
    assert len(set(sessions.values())) == 2
    assert len(executed) == 3


def test_inline_head_scope_keeps_target_and_relay_refusals(relay_runtime, monkeypatch):
    head, homes, store, siblings, executed = relay_runtime
    from agent_runtime.relay_policy import RELAY_CHAIN

    original_sessions = {
        target.id: target.default_chat_session_id for target in siblings
    }
    with _sender_scope("sender_a", homes):
        unknown = _send("not_a_runtime_persona")
        assert not unknown["ok"] and unknown["error_kind"] == "unsupported_persona"
        ambiguous = _send("dev")
        assert not ambiguous["ok"] and ambiguous["error_kind"] == "ambiguous_target"
        assert {row["persona_instance_id"] for row in ambiguous["candidates"]} == {
            target.id for target in siblings
        }
        token = RELAY_CHAIN.set(("dev",))
        try:
            cycle = _send(siblings[0].id)
            assert not cycle["ok"] and cycle["error_kind"] == "relay_cycle"
        finally:
            RELAY_CHAIN.reset(token)
        remote = _send("@another-install/dev")
        assert not remote["ok"]
        monkeypatch.setenv("HERMES_AGENT_CHAT_SCOPE", "off")
        disabled = _send(siblings[0].id)
        assert not disabled["ok"] and "disabled" in disabled["error"]
        assert get_hermes_home() == homes["sender_a"]
        assert get_hermes_head_home() == head
    assert not executed
    assert {
        target.id: store.get(target.id).default_chat_session_id for target in siblings
    } == original_sessions


def test_plain_head_caller_keeps_ambiguity_and_exact_handle_admission(
    relay_runtime, monkeypatch,
):
    head, _homes, _store, siblings, executed = relay_runtime
    monkeypatch.delenv("HERMES_HEAD_HOME")
    assert get_hermes_home() == head
    assert not hermes_head_home_is_authoritative()

    ambiguous = _send("dev")
    assert ambiguous["error_kind"] == "ambiguous_target"
    assert {row["persona_instance_id"] for row in ambiguous["candidates"]} == {
        target.id for target in siblings
    }
    assert not executed
    for target in siblings:
        result = _send(target.id)
        assert result["ok"], result
        assert result["persona_instance_id"] == target.id
    assert len(executed) == 2
    assert get_hermes_home() == head
    assert not hermes_head_home_is_authoritative()


def test_unbound_home_override_still_refuses_transcript_creation(
    relay_runtime, monkeypatch,
):
    head, _homes, _store, siblings, executed = relay_runtime
    monkeypatch.delenv("HERMES_HEAD_HOME")
    with process_home_scope(head):
        assert not hermes_head_home_is_authoritative()
        result = _send(siblings[0].id)
        assert not result["ok"]
        assert result["error_kind"] == "chat_session_db_unavailable"
        assert get_hermes_home() == head
    assert not executed
