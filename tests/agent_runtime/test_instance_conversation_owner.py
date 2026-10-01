"""Real mint, transcript and RPC boundaries; no provider or serve process."""
from contextlib import closing

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.conversation_owner import session_client_scope
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_history import persona_chat_history_summary
from tests.agent_runtime.test_serve_rpc_open_chat import (
    PERSONA, WORKSPACE, _call, _device, qa_persona, placed_agent,
)

OWNER = "a" * 64
OTHER = "b" * 64


@pytest.fixture(autouse=True)
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home
    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


def open_params(instance):
    return dict(persona_id=PERSONA, persona_instance_id=instance["persona_instance_id"],
                new_session=True, idempotency_key="new-chat", client_scope=OWNER)


def test_account_mints_are_distinct_retry_stable_and_cannot_rebind_another_owner(placed_agent):
    params = open_params(placed_agent)
    first = _call(params)["result"]
    second = _call({**params, "client_scope": OTHER})["result"]
    assert first["session_id"] != second["session_id"]
    replay = _call(params)["result"]
    assert replay["session_id"] == first["session_id"]
    assert replay["idempotent_replay"] and replay["superseded"]
    assert replay["client_scope"] == OWNER
    with closing(default_persona_session_db()) as db:
        assert session_client_scope(db.get_session(first["session_id"])) == OWNER
        assert session_client_scope(db.get_session(second["session_id"])) == OTHER
        history = persona_chat_history_summary(persona_instances=PersonaInstanceStore().list_all(), session_db=db)
        owners = {row["session_id"]: row.get("client_scope") for row in history}
        assert owners[first["session_id"]] == OWNER
        assert owners[second["session_id"]] == OTHER
    refused = _call(dict(persona_id=PERSONA, persona_instance_id=params["persona_instance_id"],
                        session_id=first["session_id"], client_scope=OTHER))
    assert refused["error"]["data"]["reason"] == "conversation_owner_changed"
    assert PersonaInstanceStore().get(params["persona_instance_id"]).session_id == second["session_id"]
    resumed = _call(dict(persona_id=PERSONA, persona_instance_id=params["persona_instance_id"],
                        session_id=first["session_id"], client_scope=OWNER))
    assert resumed["result"]["session_id"] == first["session_id"]
    assert resumed["result"]["client_scope"] == OWNER
    # The mint receipt does not authorize recreating a deleted conversation.
    with closing(default_persona_session_db()) as db:
        db.delete_session(first["session_id"])
    lost = _call(params)
    assert lost["error"]["data"]["reason"] == "session_not_found"
    with closing(default_persona_session_db()) as db:
        assert db.get_session(first["session_id"]) is None


def test_scoped_read_send_and_stop_refuse_before_side_effects(placed_agent):
    params = open_params(placed_agent)
    session = _call(params)["result"]["session_id"]
    target = dict(install_id=ensure_install_identity(paths.store_root()).install_id,
                  persona_id=PERSONA, persona_instance_id=params["persona_instance_id"],
                  workspace_id=WORKSPACE, session_id=session, client_scope=OTHER,
                  turn_request_id="first-turn", message="Hello")
    effects = []
    context = serve_rpc.RpcContext(spawn_chat_turn=lambda *a: effects.append(a),
                                  interrupt_operator=lambda *a: effects.append(a))
    def call(method, values, context=context):
        return serve_rpc.handle_request(dict(jsonrpc="2.0", id="request", method=method,
                                             params=values), context)
    for method in ("runtime.operator.conversation.read", "runtime.operator.conversation.message",
                   "runtime.operator.conversation.stop", "runtime.chat.message", "runtime.chat.steer"):
        refused = call(method, target)
        assert refused["error"]["data"]["reason"] == "conversation_owner_changed", refused
    assert effects == []
    owned = {**target, "client_scope": OWNER}
    read = call("runtime.operator.conversation.read", owned)
    assert read["result"]["client_scope"] == OWNER
    sent = call("runtime.operator.conversation.message", owned)
    assert sent["result"]["accepted"] and len(effects) == 1
    # Account namespaces do not grant console authority to a monitoring device.
    denied = call("runtime.operator.conversation.read", owned,
                  serve_rpc.RpcContext(caller=_device("read")))
    assert "error" in denied


@pytest.mark.parametrize("owner", [None, "", "account-email@example.test", "A" * 64, 123])
def test_malformed_digest_cannot_mint_a_session(placed_agent, owner):
    params = open_params(placed_agent)
    before = PersonaInstanceStore().get(params["persona_instance_id"]).session_id
    reply = _call({**params, "client_scope": owner})
    assert reply["error"]["data"]["reason"] == "invalid_client_scope"
    assert PersonaInstanceStore().get(params["persona_instance_id"]).session_id == before


def test_global_instance_opens_without_fabricated_workspace_and_checks_install(placed_agent):
    store = PersonaInstanceStore()
    instance = store.get(placed_agent["persona_instance_id"])
    instance.workspace_id = None
    store.update(instance)
    install = ensure_install_identity(paths.store_root()).install_id
    params = {**open_params(placed_agent), "install_id": install}
    before = store.get(instance.id).session_id
    refused = _call({**params, "install_id": "different-install"})
    assert refused["error"]["data"]["reason"] == "installation_changed"
    assert store.get(instance.id).session_id == before
    opened = _call(params)["result"]
    assert opened["install_id"] == install and opened["workspace_id"] is None
    target = dict(install_id=install, persona_id=PERSONA, persona_instance_id=instance.id,
                  session_id=opened["session_id"], client_scope=OWNER)
    read = serve_rpc.handle_request(dict(jsonrpc="2.0", id="read", method="runtime.operator.conversation.read",
                                        params=target), serve_rpc.RpcContext())
    assert read["result"]["workspace_id"] is None and read["result"]["client_scope"] == OWNER
    assert store.get(instance.id).workspace_id is None
    wrong = serve_rpc.handle_request(dict(jsonrpc="2.0", id="wrong", method="runtime.operator.conversation.read",
                                         params={**target, "workspace_id": WORKSPACE}), serve_rpc.RpcContext())
    assert wrong["error"]["data"]["reason"] == "workspace_changed"
