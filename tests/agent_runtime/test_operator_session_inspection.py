"""Native instance inspection preserves account, profile and transcript ownership."""
from contextlib import closing
from dataclasses import replace
import json

from agent_runtime import paths, serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_session import _persist_chat_model_override
from agent_runtime.store import AgentStore
from hermes_cli import profiles
from hermes_constants import get_hermes_home
from tests.agent_runtime.test_serve_rpc_open_chat import (
    PERSONA, WORKSPACE, _call, _device, qa_persona, placed_agent,
)
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OWNER, OTHER
from tests.agent_runtime.test_skill_inspection import put_skill


def target(instance, persona=PERSONA):
    session = _call(dict(persona_id=persona, persona_instance_id=instance,
        new_session=True, idempotency_key=f"inspect-{instance}", client_scope=OWNER))["result"]
    return dict(install_id=ensure_install_identity(paths.store_root()).install_id,
                workspace_id=WORKSPACE, persona_id=persona, persona_instance_id=instance,
                session_id=session["session_id"], client_scope=OWNER)


def inspect(operation, params, caller=None):
    return serve_rpc.handle_request(dict(jsonrpc="2.0", id="inspect",
        method=f"runtime.operator.conversation.{operation}", params=params),
        context=serve_rpc.RpcContext(caller=caller or LOCAL_CONSOLE))


def test_settings_read_the_existing_override_without_mutation_or_cross_owner_access(placed_agent):
    params = target(placed_agent["persona_instance_id"])
    personas = AgentStore()
    persona = personas.get(PERSONA)
    persona.model, persona.provider = "agent-model", "openai"
    personas.save(persona)
    instances = PersonaInstanceStore()
    instance = instances.get(params["persona_instance_id"])
    instances.update(replace(instance, model="instance-model"))
    expected_instance = instances.get(instance.id)
    initial = inspect("settings", params)
    assert "result" in initial, initial
    assert initial["result"]["model"]["effective_model"] == "instance-model"
    with closing(default_persona_session_db()) as db:
        _persist_chat_model_override(session_db=db, session_id=params["session_id"],
            override={"provider": "anthropic", "model": "chat-model", "source": "session"})
        before = db.get_session(params["session_id"])
    result = inspect("settings", params)["result"]
    assert result["client_scope"] == OWNER
    assert result["model"]["effective_model"] == "chat-model"
    assert result["model"]["effective_provider"] == "anthropic"
    assert result["model"]["agent_model"] == "instance-model"
    assert result["model"]["default_model"] == "agent-model"
    assert result["usage"]["total_tokens"] == 0
    for operation, extra in (("settings", {}), ("skills", {"operation": "list"}),
                              ("skills", {"operation": "history"})):
        refused = inspect(operation, {**params, **extra, "client_scope": OTHER})
        assert refused["error"]["data"]["reason"] == "conversation_owner_changed"
        refused = inspect(operation, {**params, **extra, "install_id": "other"})
        assert refused["error"]["data"]["reason"] == "installation_changed"
        assert "error" in inspect(operation, {**params, **extra}, _device("read"))
    with closing(default_persona_session_db()) as db:
        assert db.get_session(params["session_id"]) == before
    assert instances.get(instance.id) == expected_instance


def test_skills_use_the_named_profile_and_durable_session_evidence(placed_agent, tmp_path, monkeypatch):
    from agent.skill_utils import PROJECT_SKILLS_SUBDIRS

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    native_home = get_hermes_home()
    personas = AgentStore()
    source = personas.get(PERSONA)
    targets = []
    for name in ("alpha", "beta"):
        home = profiles._get_profiles_root() / name
        home.mkdir(parents=True)
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")
        put_skill(home, name, f"Complete {name} instructions\nLast line")
        persona = replace(source, id=name, hermes_profile=name)
        personas.save(persona)
        created = serve_rpc.handle_request(dict(jsonrpc="2.0", id="create",
            method="runtime.agent.create", params=dict(persona_id=name, workspace_id=WORKSPACE,
            position=[2.0, 3.0], idempotency_key=name)))
        assert "result" in created, created
        targets.append(target(created["result"]["persona_instance_id"], persona=name))
    for params, other in ((targets[0], "beta"), (targets[1], "alpha"), (targets[0], "beta")):
        name = params["persona_id"]
        result = inspect("skills", {**params, "operation": "list"})
        assert "result" in result, result
        ids = {row["id"] for row in result["result"]["skills"]}
        assert name in ids and other not in ids
        detail = inspect("skills", {**params, "operation": "detail", "skill_id": name})["result"]["skill"]
        assert detail["content"].replace("\r\n", "\n").endswith(f"Complete {name} instructions\nLast line")
        assert detail["source"] == "profile_local"
        assert get_hermes_home() == native_home
        assert not (profiles.get_profile_dir(name) / "skills" / ".usage.json").exists()
        assert "error" in inspect("skills", {**params, "operation": "detail", "skill_id": "../config.yaml"})
    params = targets[0]
    workspace = tmp_path / "project"
    (workspace / ".git").mkdir(parents=True)
    project_skill = workspace / PROJECT_SKILLS_SUBDIRS[0] / "workspace-review" / "SKILL.md"
    project_skill.parent.mkdir(parents=True)
    project_skill.write_text("---\nname: workspace-review\ndescription: Review project code\n---\nRead and review code.",
                             encoding="utf-8")
    (profiles.get_profile_dir("alpha") / "config.yaml").write_text(json.dumps({"skills": {
        "trusted_project_dirs": [str(workspace)]}}), encoding="utf-8")
    with closing(default_persona_session_db()) as db:
        db.update_session_cwd(params["session_id"], str(workspace))
        db.append_message(params["session_id"], "assistant", "", tool_calls=[{
            "id": "load-one", "type": "function", "function": {"name": "skill_view",
                "arguments": json.dumps({"name": "alpha"})}}])
        db.append_message(params["session_id"], "tool", json.dumps({"success": True}), tool_call_id="load-one")
    assert inspect("skills", {**params, "operation": "detail", "skill_id": "workspace-review"})["result"]["skill"]["content"].endswith("Read and review code.")
    assert "error" in inspect("skills", {**targets[1], "operation": "detail", "skill_id": "workspace-review"})
    history = inspect("skills", {**params, "operation": "history"})["result"]
    assert history["loaded"] == [{"id": "alpha", "count": 1}] and history["historyComplete"]
    persist_mission_chat_turn(session_id=params["session_id"], client_message_id="in-progress",
        turn_id="in-progress", state="running", elements=[])
    assert not inspect("skills", {**params, "operation": "history"})["result"]["historyComplete"]
    assert inspect("skills", {**targets[1], "operation": "history"})["result"]["loaded"] == []
