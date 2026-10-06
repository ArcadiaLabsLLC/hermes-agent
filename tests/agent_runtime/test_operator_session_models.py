"""Model selection shares native storage and refuses unsettled execution."""
from contextlib import closing
import json
import logging

import pytest

from agent_runtime.chat_turn import CHAT_MESSAGE_METHOD
from agent_runtime.chat_turn_reservations import reserve_chat_turn
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity.lease import persona_chat_root_lease
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_session import (
    _chat_model_override_from_config, _resolve_turn_model_selection, _session_model_config,
)
from agent_runtime.session_model_catalog import model_key
from tests.agent_runtime.test_operator_session_inspection import inspect, target
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, _call, qa_persona, placed_agent
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


def next_turn(params):
    """The model the next turn admits on: the admit phase's own resolver, no provider."""
    from agent_runtime.config import load_agent_runtime_config
    from agent_runtime.operator_session_inspection import _inspection_persona

    config = load_agent_runtime_config()
    instance = PersonaInstanceStore().get(params["persona_instance_id"])
    with closing(default_persona_session_db()) as db:
        return _resolve_turn_model_selection(session_db=db, session_id=params["session_id"],
            requested_override=None, persona=_inspection_persona(instance, config),
            config=config, instance=instance)


def receipts(caplog, prefix):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


def test_select_then_facts_then_the_next_turn_name_one_model(placed_agent, catalog, caplog):
    caplog.set_level(logging.INFO, logger="agent_runtime.persona_chat_session")
    params = target(placed_agent["persona_instance_id"])

    def agree(chat, name, source):
        facts = inspect("models", chat)["result"]["facts"]
        turn = next_turn(chat)
        assert facts["current_model_id"] == model_key(PROVIDER, name)
        assert model_key(turn["effective_provider"], turn["effective_model"]) == model_key(PROVIDER, name)
        assert receipts(caplog, "chat_turn_model")[-1] == (
            f"chat_turn_model root={chat['session_id']} provider={PROVIDER} model={name} source={source}")

    assert "result" in choose(params, "first")
    agree(params, "first", "override")
    assert "result" in choose(params, "second", "agent_default")
    agree(params, "second", "instance")
    fresh = _call(dict(persona_id=PERSONA, persona_instance_id=params["persona_instance_id"],
        new_session=True, idempotency_key="model-pick-new-chat", client_scope=OWNER))["result"]
    assert fresh["session_id"] != params["session_id"]
    agree({**params, "session_id": fresh["session_id"]}, "second", "instance")
    verb = "model_selection verb=runtime.operator.conversation.model.select"
    assert receipts(caplog, verb) == [
        f"{verb} target={params['session_id']} scope=conversation chosen={model_key(PROVIDER, 'first')} "
        "outcome=applied saved=session_override",
        f"{verb} target={params['session_id']} scope=agent_default chosen={model_key(PROVIDER, 'second')} "
        "outcome=applied saved=persona_instance_store+session_override_cleared",
    ]


def test_a_refused_selection_leaves_a_receipt_and_moves_nothing(placed_agent, catalog, caplog):
    caplog.set_level(logging.INFO, logger="agent_runtime.persona_chat_session")
    params = target(placed_agent["persona_instance_id"])
    before = next_turn(params)
    assert choose(params, "unavailable")["error"]["data"]["reason"] == "model_unavailable"
    assert receipts(caplog, "model_selection")[-1].endswith("outcome=refused:model_unavailable saved=-")
    assert next_turn(params)["effective_model"] == before["effective_model"]


def set_effort(instance_id, **change):
    from types import SimpleNamespace
    from hermes_cli.harness_parts.persona.model_and_skills_commands import _cmd_persona_instance_set_model

    assert _cmd_persona_instance_set_model(SimpleNamespace(
        persona_instance_id=instance_id, json=True, requested_by="operator", **change)) == 0


def next_request_effort(params, model="gpt-5.6-luna"):
    """The effort the next request carries on the wire: the run's reasoning_config as the
    runner resolves it (in the persona's profile), through the codex transport's resolver."""
    from agent.transports.codex import _resolve_reasoning
    from agent_runtime.operator_session_models import _model_profile
    from agent_runtime.profile_runner.models import AgentRunRequest
    from agent_runtime.profile_runner.resident_actor import log_turn_effort, turn_reasoning_config
    from types import SimpleNamespace

    instance = PersonaInstanceStore().get(params["persona_instance_id"])
    request = AgentRunRequest(profile=None, model=model, turn_id="t",
        reasoning_effort=getattr(instance, "reasoning_effort", None),  # as chat_turn_commit.run passes it
        root_chat_session_id=params["session_id"])
    with _model_profile(instance):
        config = turn_reasoning_config(request, model)
    log_turn_effort(request, SimpleNamespace(model=model, reasoning_config=config), reused=True)
    effort, enabled = _resolve_reasoning(model, {"reasoning_config": config, "is_codex_backend": True})
    return effort if enabled else "none"


def test_effort_select_facts_and_the_next_request_agree(placed_agent, catalog, caplog, capsys):
    from hermes_constants import get_hermes_home

    caplog.set_level(logging.INFO)
    config = get_hermes_home() / "config.yaml"
    config.write_text(json.dumps({**json.loads(config.read_text(encoding="utf-8")),
                                  "agent": {"reasoning_effort": "high"}}), encoding="utf-8")
    params = target(placed_agent["persona_instance_id"])

    def agree(effort, source):
        facts = inspect("models", params)["result"]["facts"]
        assert (facts["reasoning_effort"], facts["reasoning_effort_source"]) == (effort, source)
        assert next_request_effort(params) == effort
        assert receipts(caplog, "chat_turn_effort")[-1].endswith(f"effort={effort} source={source} actor=reused")

    agree("high", "profile")
    set_effort(params["persona_instance_id"], reasoning_effort="low")
    agree("low", "instance")
    assert receipts(caplog, "model_selection verb=persona.instance.set_model")[-1].endswith(
        "scope=agent_instance chosen=model=-,effort=low outcome=applied saved=persona_instance_store")
    set_effort(params["persona_instance_id"], use_profile_default=True)
    agree("high", "profile")
    capsys.readouterr()


def test_an_effort_change_moves_the_resident_actor_key():
    from dataclasses import replace
    from agent_runtime.models import PersonaInstance
    from agent_runtime.persona_chat_identity import INSTANCE_IDENTITY_FIELDS, identity_revision

    import inspect as _inspect
    fields = {name: None for name in _inspect.signature(PersonaInstance).parameters}
    base = PersonaInstance(**{**fields, "id": "i", "persona_id": "p"})
    assert identity_revision(base, INSTANCE_IDENTITY_FIELDS) != identity_revision(
        replace(base, reasoning_effort="low"), INSTANCE_IDENTITY_FIELDS)
