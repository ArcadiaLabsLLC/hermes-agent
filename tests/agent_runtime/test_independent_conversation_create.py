"""Intelligence creation owns a transcript, never the cockpit's selection."""
from contextlib import closing

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_open_chat import CREATE_CONVERSATION_METHOD
from tests.agent_runtime.test_instance_conversation_owner import OWNER, chat_head
from tests.agent_runtime.test_serve_rpc_open_chat import (
    PERSONA, WORKSPACE, _call, _device, qa_persona, placed_agent,
)


def create_params(instance):
    return dict(persona_id=PERSONA, persona_instance_id=instance["persona_instance_id"],
                install_id=ensure_install_identity(paths.store_root()).install_id,
                idempotency_key="independent-chat", client_scope=OWNER)


def request(method, params, context=None):
    return serve_rpc.handle_request(dict(jsonrpc="2.0", id="create", method=method, params=params),
                                    context or serve_rpc.RpcContext())


def pointers(instance):
    row = PersonaInstanceStore().get(instance["persona_instance_id"])
    return row.session_id, row.default_chat_session_id


def test_creation_retry_and_send_keep_cockpit_selection(placed_agent):
    params = create_params(placed_agent)
    before = pointers(placed_agent)
    first = request(CREATE_CONVERSATION_METHOD, params)["result"]
    second = request(CREATE_CONVERSATION_METHOD, {**params, "idempotency_key": "another-chat"})["result"]
    assert first["session_id"] != second["session_id"]
    assert first["session_id"] not in before
    assert not first["selected"] and not first["selection_requested"] and not first["superseded"]
    assert pointers(placed_agent) == before
    # A newly constructed dispatcher reads the durable mint receipt after a lost acknowledgement.
    replay = request(CREATE_CONVERSATION_METHOD, params)["result"]
    assert replay["idempotent_replay"] and replay["session_id"] == first["session_id"]
    assert pointers(placed_agent) == before
    with closing(default_persona_session_db()) as db:
        assert db.get_session(first["session_id"]) is not None
        assert db.get_session(second["session_id"]) is not None
    target = {**params, "session_id": first["session_id"], "workspace_id": WORKSPACE}
    read = request("runtime.operator.conversation.read", target)
    assert read["result"]["session_id"] == first["session_id"]
    effects = []
    context = serve_rpc.RpcContext(spawn_chat_turn=lambda *args: effects.append(args))
    sent = request("runtime.operator.conversation.message",
                   {**target, "turn_request_id": "first-turn", "message": "Hello"}, context)
    assert sent["result"]["accepted"] and len(effects) == 1
    assert pointers(placed_agent) == before
    # Explicit selection remains available, and retries do not undo a later selection.
    selected = _call({**params, "session_id": first["session_id"]})
    assert selected["result"]["session_id"] == first["session_id"]
    replay = request(CREATE_CONVERSATION_METHOD, params)["result"]
    assert replay["selected"] and not replay["selection_requested"]
    assert pointers(placed_agent) == (first["session_id"], first["session_id"])


def test_mint_key_cannot_change_selection_intent(placed_agent):
    params = create_params(placed_agent)
    before = pointers(placed_agent)
    request(CREATE_CONVERSATION_METHOD, params)["result"]
    refused = _call({**params, "new_session": True})
    assert "error" in refused
    assert pointers(placed_agent) == before
    selected = _call({**params, "idempotency_key": "selecting", "new_session": True})["result"]
    refused = request(CREATE_CONVERSATION_METHOD, {**params, "idempotency_key": "selecting"})
    assert "error" in refused
    assert pointers(placed_agent) == (selected["session_id"], selected["session_id"])


@pytest.mark.parametrize("field", ["persona_id", "persona_instance_id", "install_id", "client_scope"])
@pytest.mark.parametrize("invalid", [None, " ", 123])
def test_creation_requires_exact_owned_instance(placed_agent, field, invalid):
    params = create_params(placed_agent)
    before = pointers(placed_agent)
    params[field] = invalid
    assert "error" in request(CREATE_CONVERSATION_METHOD, params)
    assert pointers(placed_agent) == before


def test_creation_is_console_authorized_and_rejects_selection_flags(placed_agent):
    params = create_params(placed_agent)
    before = pointers(placed_agent)
    assert CREATE_CONVERSATION_METHOD in serve_rpc.manifest()["methods"]
    for extra in ({"new_session": True}, {"kill_active": True}, {"select_session": True}):
        assert "error" in request(CREATE_CONVERSATION_METHOD, {**params, **extra})
    assert "error" in request(CREATE_CONVERSATION_METHOD, params,
                               serve_rpc.RpcContext(caller=_device("read")))
    assert pointers(placed_agent) == before
    assert "result" in request(CREATE_CONVERSATION_METHOD, params,
                                serve_rpc.RpcContext(caller=_device("console")))
    assert pointers(placed_agent) == before


def test_retired_instance_cannot_create_an_independent_root(placed_agent):
    params = create_params(placed_agent)
    with closing(default_persona_session_db()) as db:
        before = db.session_count()
    retired = request("runtime.agent.retire", {"persona_instance_id": params["persona_instance_id"],
                                               "reason": "test"})
    assert "result" in retired
    assert "error" in request(CREATE_CONVERSATION_METHOD, params)
    with closing(default_persona_session_db()) as db:
        assert db.session_count() == before

