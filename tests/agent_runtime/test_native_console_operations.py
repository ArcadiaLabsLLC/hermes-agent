"""Paired-device twins use the same stores/guards without global stdout capture."""
from tests.agent_runtime.test_operator_session_models import placed_agent, qa_persona
from agent_runtime.serve_rpc import console_operations as rpc
from agent_runtime.serve_rpc.registry import method_tier
from agent_runtime.serve_rpc.protocol import ERR_INVALID_PARAMS


def test_native_instance_model_persists_and_refuses_malformed_params(placed_agent, capsys):
    from agent_runtime.persona_assignments import PersonaInstanceStore
    identifier = placed_agent["persona_instance_id"]
    reply = rpc.instance_model("write", {"persona_instance_id":identifier,
                                        "model":"paired-model", "reasoning_effort":"high"})
    assert "result" in reply, reply
    stored = PersonaInstanceStore().get(identifier)
    assert (stored.model, stored.reasoning_effort) == ("paired-model", "high")
    assert not capsys.readouterr().out
    invalid = rpc.instance_model("bad", {"persona_instance_id":identifier, "use_default":"yes"})
    assert invalid["error"]["code"] == ERR_INVALID_PARAMS
    assert PersonaInstanceStore().get(identifier).model == "paired-model"
    assert method_tier("runtime.persona.instance.set_model") == "console"


def test_permission_one_turn_uses_native_store(placed_agent, capsys):
    from agent_runtime.persona_assignments import PersonaInstanceStore
    instance = PersonaInstanceStore().get(placed_agent["persona_instance_id"])
    params = {"persona_id":instance.persona_id, "session_id":"paired-session", "mode":"unbounded",
              "reason":"operator once", "turns":1}
    reply = rpc.permission_set("once", params)
    assert "result" in reply, reply
    assert reply["result"]["permission"]["turns_remaining"] == 1
    from agent_runtime.tool_permissions import ChatToolPermissionStore
    store = ChatToolPermissionStore()
    assert store.get(persona_id=instance.persona_id, session_id="paired-session").turns_remaining == 1
    store.consume_turn(persona_id=instance.persona_id, session_id="paired-session")
    expired = store.get(persona_id=instance.persona_id, session_id="paired-session")
    assert (expired.mode, expired.turns_remaining, expired.source) == ("profile_default", 0, "operator:elevation_expired")
    assert not capsys.readouterr().out
    bad = rpc.permission_set("bad", {**params, "turns":0})
    assert bad["error"]["code"] == ERR_INVALID_PARAMS
    assert method_tier("runtime.persona.permission.set") == "console"


def test_native_read_twins_use_public_owners_and_honest_misses(monkeypatch):
    from agent_runtime import prompt_observability
    from agent_runtime.snapshot import details
    monkeypatch.setattr(prompt_observability, "load_persisted_context_row", lambda key: None)
    monkeypatch.setattr(details, "persona_instance_detail_for_id", lambda key: None)
    monkeypatch.setattr(prompt_observability, "skills_catalog_by_hash", lambda key, materialize: [{"name":"safe"}])
    assert rpc.prompt_context("p", {"context_id":"gone"})["result"] == {"found":False,"context_id":"gone"}
    assert rpc.instance_detail("i", {"instance_id":"gone"})["result"]["found"] is False
    assert rpc.skills_catalog("s", {"content_hash":"catalog"})["result"] == {
        "hash":"catalog", "found":True, "skills":[{"name":"safe"}]}
    assert method_tier("runtime.prompt_context.show") == "console"
    assert method_tier("runtime.persona.instance.detail") == "read"
    assert method_tier("runtime.skills.catalog") == "read"


def test_persona_model_and_permission_preview_share_cli_owners(qa_persona, capsys):
    from agent_runtime.store import AgentStore
    from agent_runtime.tool_permissions import ChatToolPermissionStore
    result = rpc.persona_model("model", {"persona_id":qa_persona.id, "model":"inherited"})
    assert "result" in result, result
    assert AgentStore().get(qa_persona.id).model == "inherited"
    preview = rpc.permission_preview("preview", {"persona_id":qa_persona.id,
        "session_id":"preview-only", "mode":"read_only"})
    assert "tool_visibility" in preview["result"], preview
    assert ChatToolPermissionStore().get(persona_id=qa_persona.id, session_id="preview-only") is None
    assert not capsys.readouterr().out


def test_device_authorization_cannot_bypass_console_tier():
    from agent_runtime import serve_rpc
    from agent_runtime.serve_rpc.protocol import RpcContext
    from tests.agent_runtime.test_serve_rpc_open_chat import _device
    frame = {"jsonrpc":"2.0", "id":"gate", "method":"runtime.persona.instance.set_model",
             "params":{"persona_instance_id":"missing", "model":"x"}}
    denied = serve_rpc.handle_request(frame, context=RpcContext(caller=_device("read")))
    assert "error" in denied
    from agent_runtime.call_authorization import REASON_SCOPE_DENIED
    assert denied["error"]["data"]["reason"] == REASON_SCOPE_DENIED
