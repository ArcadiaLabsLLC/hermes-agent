"""Model selection shares native storage and refuses unsettled execution."""
from contextlib import closing
import json

import pytest

from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD
from agent_runtime.chat_turn_reservations import reserve_chat_turn
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity.lease import persona_chat_root_lease
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_session import _chat_model_override_from_config, _session_model_config
from agent_runtime.session_model_catalog import model_key
from tests.agent_runtime.test_operator_session_inspection import inspect, target
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OWNER, OTHER

PROVIDER = "custom:test-endpoint"

@pytest.fixture
def catalog(monkeypatch):
    from hermes_cli import inventory as model_inventory
    from hermes_constants import get_hermes_home

    home = get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(json.dumps({"providers": {"test-endpoint": {
        "name": "Test endpoint", "base_url": "http://127.0.0.1:1/v1",
        "key_env": "TEST_ENDPOINT_API_KEY", "discover_models": False,
        "models": {"first": {}, "second": {}},
    }}}), encoding="utf-8")
    (home / ".env").write_text("TEST_ENDPOINT_API_KEY=isolated-test-key\n", encoding="utf-8")
    monkeypatch.setattr(model_inventory, "_prewarm_pricing_async", lambda *args, **kwargs: None)


def choose(params, name="first", scope="conversation"):
    return inspect("model.select", {**params, "model_id": model_key(PROVIDER, name), "scope": scope})


def stored(params):
    with closing(default_persona_session_db()) as db:
        return _session_model_config(db, params["session_id"])


def test_model_controls_reuse_session_and_instance_defaults(placed_agent, catalog):
    params = target(placed_agent["persona_instance_id"])
    original = PersonaInstanceStore().get(params["persona_instance_id"])
    offered = inspect("models", params)["result"]["facts"]
    assert {row["id"] for row in offered["models"] if row["provider_id"] == PROVIDER} == {model_key(PROVIDER, x) for x in ("first", "second")}
    reply = choose(params)
    assert "result" in reply, reply
    assert reply["result"]["facts"]["current_model_id"] == model_key(PROVIDER, "first")
    assert stored(params)["client_scope"] == OWNER
    assert _chat_model_override_from_config(stored(params))["model"] == "first"
    assert PersonaInstanceStore().get(original.id) == original
    reply = choose(params, "second", "agent_default")
    assert "result" in reply, reply
    assert reply["result"]["facts"]["current_model_id"] == model_key(PROVIDER, "second")
    assert reply["result"]["facts"]["default_model_id"] == model_key(PROVIDER, "second")
    assert _chat_model_override_from_config(stored(params)) is None
    assert PersonaInstanceStore().get(original.id).model == "second"
    assert stored(params)["client_scope"] == OWNER


@pytest.mark.parametrize("protected", ["running", "outcome_unknown", "native_committed", "accepted", "lease", "question"])
def test_model_selection_cannot_change_unsettled_work(placed_agent, catalog, protected):
    params = target(placed_agent["persona_instance_id"])
    before = stored(params)
    if protected == "accepted":
        with reserve_chat_turn(turn_request_id="queued", verb=CHAT_MESSAGE_METHOD,
                               session_scope=params["session_id"]) as receipt:
            receipt.mark_accepted({"turn_request_id": "queued"}, request_id="queued")
    elif protected == "question":
        PersonaChatClarifyTicketStore().mint(chat_session_id=params["session_id"],
            persona_instance_id=params["persona_instance_id"], persona_id=params["persona_id"])
    elif protected != "lease":
        persist_mission_chat_turn(session_id=params["session_id"], client_message_id="working",
            turn_id="working", state=protected, elements=[])
    if protected == "lease":
        with persona_chat_root_lease(params["session_id"]):
            reply = choose(params)
    else:
        reply = choose(params)
    assert reply["error"]["data"]["reason"] == "conversation_busy", reply
    assert stored(params) == before


def test_foreign_and_unoffered_choices_never_write(placed_agent, catalog):
    params = target(placed_agent["persona_instance_id"])
    before = stored(params)
    for change, expected in (({"client_scope": OTHER}, "conversation_owner_changed"),
                              ({"install_id": "changed"}, "installation_changed")):
        assert choose({**params, **change})["error"]["data"]["reason"] == expected
    assert choose(params, "unavailable")["error"]["data"]["reason"] == "model_unavailable"
    assert stored(params) == before


def test_real_catalog_is_read_without_minting_a_worker(placed_agent):
    params = target(placed_agent["persona_instance_id"])
    before = stored(params)
    reply = inspect("models", params)
    assert "result" in reply, reply
    assert isinstance(reply["result"]["facts"]["models"], list)
    assert reply["result"]["session_id"] == params["session_id"]
    assert stored(params) == before
