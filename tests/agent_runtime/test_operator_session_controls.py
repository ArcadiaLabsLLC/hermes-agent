"""The native Console seam: exact-owner settings and real guarded actions."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import paths
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner
from agent_runtime.session_control_store import SessionControlStore
from agent_runtime.session_controls import apply_session_speed, resolved_session_controls, speed_options
from agent_runtime.store import AgentStore
from agent_runtime.persona_chat_continuity.lease import persona_chat_root_lease
from tests.agent_runtime.test_operator_session_inspection import inspect, target
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, qa_persona, placed_agent, _device
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OWNER, OTHER
from tests.agent_runtime.test_profile_runner import FakeAgent
from tests.waiting import wait_until


@pytest.fixture
def chat(request):
    placement = request.getfixturevalue("placed_agent")
    persona = AgentStore().get(PERSONA)
    persona.provider, persona.model = "openai", "gpt-6.1-sol"
    AgentStore().save(persona)
    return target(placement["persona_instance_id"])


def set_control(chat, setting, picked_value, **changed):
    return inspect("control.set", {**chat, "setting": setting, "value": picked_value,
        "expected_provider": "openai", "expected_model": "gpt-6.1-sol", **changed})


def test_settings_persist_per_chat_without_rewriting_native_history(chat):
    initial = inspect("controls", chat)
    assert "result" in initial, initial
    facts = initial["result"]["controls"]
    assert facts["approval"]["mode"] == "smart"
    assert facts["approval"]["source"] == "profile"
    # v0.22.2 lists gpt-6.1-sol on openai with an ultrafast tier, so the picker offers it.
    assert {row["id"] for row in facts["speed"]["options"]} == {"", "priority", "ultrafast", "auto", "cold"}
    with closing(default_persona_session_db()) as db:
        before = db.get_session(chat["session_id"])
    selected = set_control(chat, "approval_mode", "manual")
    assert selected["result"]["controls"]["approval"]["mode"] == "manual"
    selected = set_control(chat, "service_tier", "priority")
    assert selected["result"]["controls"]["speed"]["requested"] == "priority"
    assert SessionControlStore().read(chat["session_id"])["service_tier"] == "priority"
    assert resolved_session_controls("another-chat", provider="openai", model="gpt-6.1-sol")["approval"]["mode"] == "smart"
    with closing(default_persona_session_db()) as db:
        assert db.get_session(chat["session_id"]) == before
    assert set_control(chat, "approval_mode", None)["result"]["controls"]["approval"]["source"] == "profile"
    capture = os.getenv("HERMES_TEST_TMP_ROOT")
    if capture:
        Path(capture).mkdir(parents=True, exist_ok=True)
        Path(capture, "console-session-controls-capture.json").write_text(json.dumps(initial["result"], indent=2), encoding="utf-8")


@pytest.mark.parametrize("changed,reason", [
    ({"client_scope": OTHER}, "conversation_owner_changed"),
    ({"expected_model": "another-model"}, "model_changed"),
    ({"value": "invented-tier"}, "setting_unavailable"),
])
def test_unconfirmed_settings_never_write(chat, changed, reason):
    reply = set_control(chat, "service_tier", "priority", **changed)
    assert reply["error"]["data"]["reason"] == reason
    assert SessionControlStore().read(chat["session_id"]) == {}


def test_busy_and_read_only_callers_cannot_change_execution_policy(chat):
    with persona_chat_root_lease(chat["session_id"], observer_kind="test"):
        reply = set_control(chat, "approval_mode", "off")
    assert reply["error"]["data"]["reason"] == "conversation_busy"
    reply = inspect("control.set", {**chat, "setting": "approval_mode", "value": "off"}, caller=_device("read"))
    assert "error" in reply
    assert SessionControlStore().read(chat["session_id"]) == {}


def test_omitted_value_cannot_reset_a_saved_approval_policy(chat):
    SessionControlStore().update(chat["session_id"], "approval_mode", "manual")
    reply = inspect("control.set", {**chat, "setting": "approval_mode",
        "expected_provider": "openai", "expected_model": "gpt-6.1-sol"})
    assert reply["error"]["data"]["reason"] == "invalid_setting"
    assert SessionControlStore().read(chat["session_id"])["approval_mode"] == "manual"
    explicit = set_control(chat, "approval_mode", None)
    assert explicit["result"]["controls"]["approval"]["mode"] == "smart"


def test_speed_is_route_and_transport_specific_and_normal_clears_paid_overrides():
    assert speed_options("openrouter", "openai/gpt-6-astra") == []
    assert speed_options("openai", "gpt-6-astra", "https://proxy.invalid/v1") == []
    assert speed_options("ollama", "local-model") == []
    assert "ultrafast" in {row["id"] for row in speed_options("openai", "gpt-6-astra")}
    assert "ultrafast" not in {row["id"] for row in speed_options("openai-codex", "gpt-6-astra", api_mode="codex_app_server")}
    assert "ultrafast" not in {row["id"] for row in speed_options("openai-codex", "gpt-6-astra")}
    SessionControlStore().update("speed-chat", "service_tier", "priority")
    agent = SimpleNamespace(base_url="https://api.openai.com/v1", request_overrides={"temperature": .2})
    controls = resolved_session_controls("speed-chat", provider="openai", model="gpt-6.1-sol")
    apply_session_speed(agent, controls)
    assert agent.service_tier == "priority"
    assert agent.request_overrides == {"temperature": .2, "service_tier": "priority"}
    SessionControlStore().update("speed-chat", "service_tier", "")
    apply_session_speed(agent, resolved_session_controls("speed-chat", provider="openai", model="gpt-6.1-sol"))
    assert agent.service_tier is None
    assert agent.request_overrides == {"temperature": .2}


@pytest.mark.parametrize("choice,approved", [("once", True), ("deny", False)])
def test_real_runner_waits_for_exact_owner_approval_then_honors_the_answer(chat, monkeypatch, choice, approved):
    from agent_runtime.profile_runner import execute
    from tools.approval import check_all_command_guards, unregister_gateway_notify

    SessionControlStore().update(chat["session_id"], "approval_mode", "manual")
    SessionControlStore().update(chat["session_id"], "service_tier", "priority")
    monkeypatch.setattr(execute, "_resolve_request_runtime", lambda request, timing: {
        "provider": "openai", "model": "gpt-6.1-sol", "base_url": "https://api.openai.com/v1"})

    class GuardAgent(FakeAgent):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.base_url = "https://api.openai.com/v1"

        def run_conversation(self, user_message, system_message=None, task_id=None):
            verdict = check_all_command_guards("git reset --hard", "local")
            return {"final_response": "finished", "session_id": self.session_id,
                    "guard": verdict, "service_tier": self.service_tier,
                    "request_overrides": self.request_overrides}

    runner = ProfileAgentRunner(agent_factory=GuardAgent)
    request = AgentRunRequest(profile=None, provider="openai", model="gpt-6.1-sol",
        root_chat_session_id=chat["session_id"], tool_execution_scope_id=chat["session_id"],
        runtime_root=paths.store_root(), user_message="guarded-action")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner.run, request)
        try:
            approvals = wait_until(lambda: inspect("approvals", chat).get("result", {}).get("approvals"),
                what="runner's native approval queue")
            assert not future.done()
            approval = approvals[0]
            assert approval["command"] == "git reset --hard"
            assert {row["id"] for row in approval["choices"]} == {"once", "deny"}
            foreign = inspect("approval.respond", {**chat, "client_scope": OTHER,
                "approval_id": approval["id"], "choice": "once"})
            assert "error" in foreign
            assert not future.done()
            wrong = inspect("approval.respond", {**chat, "approval_id": "stale", "choice": "once"})
            assert wrong["error"]["data"]["reason"] == "approval_expired"
            reply = inspect("approval.respond", {**chat, "approval_id": approval["id"], "choice": choice})
            assert reply["result"]["accepted"] is True
            result = future.result(timeout=10)
            assert result.raw["guard"]["approved"] is approved
            assert result.raw["service_tier"] == "priority"
            assert result.raw["request_overrides"]["service_tier"] == "priority"
            assert inspect("approvals", chat)["result"]["approvals"] == []
            replay = inspect("approval.respond", {**chat, "approval_id": approval["id"], "choice": choice})
            assert replay["error"]["data"]["reason"] == "approval_expired"
        finally:
            unregister_gateway_notify(chat["session_id"])


def test_off_keeps_native_hardline_and_deny_rule_floors():
    from tools.approval import check_all_command_guards
    from agent_runtime.session_controls import session_approval_scope

    SessionControlStore().update("off-chat", "approval_mode", "off")
    with session_approval_scope("off-chat"):
        assert check_all_command_guards("git reset --hard", "local")["approved"] is True
        assert check_all_command_guards("rm -rf /", "local")["approved"] is False


def test_timeout_and_withdrawal_never_authorize_an_action(monkeypatch):
    from hermes_constants import get_hermes_home
    from tools.approval import check_all_command_guards, list_gateway_approvals, withdraw_gateway_approval, unregister_gateway_notify
    from agent_runtime.session_controls import session_approval_scope

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"approvals": {"mode": "manual", "timeout": 0}}), encoding="utf-8")
    with session_approval_scope("timeout-chat"):
        result = check_all_command_guards("git reset --hard", "local")
    assert result["approved"] is False and result["outcome"] == "timeout"
    (home / "config.yaml").write_text(json.dumps({"approvals": {"mode": "manual", "timeout": 30}}), encoding="utf-8")

    def guarded():
        with session_approval_scope("withdraw-chat"):
            return check_all_command_guards("git reset --hard", "local")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(guarded)
        try:
            waiting = wait_until(lambda: list_gateway_approvals("withdraw-chat"))
            assert withdraw_gateway_approval("withdraw-chat", waiting[0]["request_id"], "turn_stopped")
            result = future.result(timeout=10)
            assert result["approved"] is False and result["outcome"] == "cancelled"
        finally:
            unregister_gateway_notify("withdraw-chat")


def test_host_policy_and_bypass_are_reported_honestly():
    from gateway.hosted_room_execution_policy import RoomExecutionPolicy, bind_room_execution_policy, reset_room_execution_policy
    from tools.approval import enable_session_yolo, disable_session_yolo

    policy = RoomExecutionPolicy(version=1, target_profile="base", enabled_toolsets=("bot_room",),
        approval_mode="manual", max_iterations=10, policy_digest="test-policy")
    token = bind_room_execution_policy(policy)
    try:
        facts = resolved_session_controls("policy-chat", provider="openai", model="gpt-6.1-sol")
        assert facts["approval"]["mode"] == "manual"
        assert facts["approval"]["options"] == [facts["approval"]["options"][0]]
        assert facts["approval"]["options"][0]["id"] == "manual"
        assert facts["approval"]["writable"] is False
    finally:
        reset_room_execution_policy(token)
    enable_session_yolo("policy-chat")
    try:
        facts = resolved_session_controls("policy-chat", provider="openai", model="gpt-6.1-sol")
        assert facts["approval"]["mode"] == "off"
        assert facts["approval"]["source"] == "bypass"
        assert facts["approval"]["writable"] is False
    finally:
        disable_session_yolo("policy-chat")
