"""The chat-family method twins — one implementation each, the argv row on the wire.

``runtime.persona.chat.history``, ``runtime.persona.instance.create``,
``runtime.chat.turn.resolve``, ``runtime.chat.queue_skill`` and
``runtime.persona.chat.delete`` (argv census rows 11-15).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE_METHODS, TIER_CONSOLE
from agent_runtime.chat_verbs import queue_skill as queue_skill_verb
from agent_runtime.chat_verbs import turn_resolve as turn_resolve_verb
from agent_runtime.mission_chat_door import CHAT_DELETE_VERB, INSTANCE_CREATE_VERB, bind_chat_verb
from agent_runtime.mission_chat_turns import transition_mission_chat_turn
from agent_runtime.mission_chat_turns.reads import mission_chat_turn_record
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT, ERR_HANDLER_FAILED, ERR_INVALID_PARAMS, ERR_NOT_FOUND
from hermes_cli.harness_parts.mission_chat_door_binding import bind_mission_chat_door
from hermes_cli.harness_parts.persona import (
    chat_coordinator,
    chat_delete,
    chat_open,
    chat_target,
    chat_tickets_commands,
    lifecycle_commands,
)
from hermes_cli.harness_parts import runtime_commands
from tests.agent_runtime.test_persona_assignments import _TranscriptDB, _assignment_config

METHODS = (
    "runtime.persona.chat.history",
    "runtime.persona.instance.create",
    "runtime.chat.turn.resolve",
    "runtime.chat.queue_skill",
    "runtime.persona.chat.delete",
)


def _rpc(method: str, params, rid: str = "cv"):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})


@pytest.fixture
def chat_db(monkeypatch, isolate_agent_runtime_root, persisted_persona_samples):
    cfg = _assignment_config()
    db = _TranscriptDB()
    for module in (chat_delete, chat_open, chat_target, lifecycle_commands):
        monkeypatch.setattr(module, "load_agent_runtime_config", lambda: cfg)
    for module in (chat_delete, chat_open, lifecycle_commands, turn_resolve_verb):
        monkeypatch.setattr(module, "_default_persona_session_db", lambda: db)
    bind_mission_chat_door()
    yield db


# ── registration ─────────────────────────────────────────────────────────────


def test_all_five_are_advertised_at_the_console_tier_and_remote_answerable():
    manifest = serve_rpc.manifest()
    for name in METHODS:
        assert name in manifest["methods"]
        assert manifest["tiers"][name] == TIER_CONSOLE
        assert name not in LOCAL_CONSOLE_METHODS
    assert manifest["contract"] == 1


# ── history ──────────────────────────────────────────────────────────────────


def test_history_method_and_argv_read_one_page_function(monkeypatch, capsys):
    calls: list[dict] = []

    def page(**kwargs):
        calls.append(kwargs)
        return {"ok": True, "session_id": kwargs["session_id"], "messages": [], "count": 0}

    monkeypatch.setattr("agent_runtime.persona_chat_history.persona_chat_session_messages", page)
    result = _rpc("runtime.persona.chat.history", {"session_id": "s1", "limit": 500, "before": "c1"})["result"]
    args = SimpleNamespace(session_id="s1", limit=500, before="c1", json=True)
    assert runtime_commands._cmd_persona_chat_history(args) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(json.dumps(result))
    assert calls == [{"session_id": "s1", "limit": 40, "before": "c1"}] * 2
    assert "chat_scope" in result and "resolution" in result


def test_history_refusals_are_typed(monkeypatch):
    bad = _rpc("runtime.persona.chat.history", {"session_id": "s1", "limit": True})
    assert bad["error"]["code"] == ERR_INVALID_PARAMS and bad["error"]["data"]["reason"] == "invalid_request"
    monkeypatch.setattr(
        "agent_runtime.persona_chat_history.persona_chat_session_messages",
        lambda **kw: {"ok": False, "error_kind": "session_db_unavailable", "error": "no db", "session_id": "s1"},
    )
    failed = _rpc("runtime.persona.chat.history", {"session_id": "s1"})["error"]
    assert failed["code"] == ERR_HANDLER_FAILED
    assert failed["data"]["reason"] == "session_db_unavailable" and failed["message"] == "no db"


# ── queue skill ──────────────────────────────────────────────────────────────


def test_queue_skill_method_and_argv_reach_one_implementation(monkeypatch, capsys):
    seen: list[dict] = []

    def queue(**kwargs):
        seen.append(kwargs)
        return {"ok": True, "skills": list(kwargs["skills"])}

    monkeypatch.setattr(queue_skill_verb, "queue_skills_next_turn", queue)
    params = {"persona_id": "dev", "session_id": "s1", "skills": ["a"], "skill": "b", "persona_instance_id": "pi"}
    assert _rpc("runtime.chat.queue_skill", params)["result"] == {"ok": True, "skills": ["b", "a"]}
    args = SimpleNamespace(persona_id="dev", session_id="s1", skills=["a"], skill=["b"], persona_instance_id="pi",
                           json=True)
    assert chat_coordinator._cmd_mission_chat_queue_skill(args) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "skills": ["b", "a"]}
    assert seen[0] == seen[1]


def test_queue_skill_refuses_unloadable_skills_and_queues_nothing(monkeypatch, isolate_agent_runtime_root):
    from agent_runtime.queued_skills import pending_skills_for_next_turn
    import tools.skills_tool as skills_tool

    monkeypatch.setattr(skills_tool, "_find_all_skills", lambda: [])
    error = _rpc("runtime.chat.queue_skill",
                 {"persona_id": "dev", "session_id": "s1", "skills": ["missing-skill"]})["error"]
    assert error["code"] == ERR_INVALID_PARAMS
    assert error["data"]["reason"] == "skills_not_loadable"
    assert set(error["data"]["rejected_skills"]) == {"missing-skill"}
    assert pending_skills_for_next_turn(persona_id="dev", session_id="s1") == []
    empty = _rpc("runtime.chat.queue_skill", {"persona_id": "dev", "session_id": "s1", "skills": "x"})["error"]
    assert empty["data"]["reason"] == "invalid_request"


# ── turn resolve ─────────────────────────────────────────────────────────────


def _ambiguous_turn(db):
    owner = PersonaInstanceStore().open_chat(persona_id="dev", session_id="persona_chat_personainst_dev")
    foreign = PersonaInstanceStore().add_instance(persona_id="qa", placement_id="foreign-placement_agent_2")
    db.create_session(owner.session_id, "agent_runtime_persona_chat",
                      model_config=json.dumps({"source": "agent_runtime_persona_chat",
                                               "persona_instance_id": owner.id}))
    for state in ("pending", "executing", "outcome_unknown"):
        transition_mission_chat_turn(session_id=owner.session_id, client_message_id="c1", turn_id="c1", state=state)
    return owner, foreign


def _resolve_params(owner, instance_id):
    return {"session_id": owner.session_id, "client_message_id": "c1", "turn_id": "c1", "action": "abandon",
            "persona_instance_id": instance_id}


def test_turn_resolve_fences_the_owner_then_abandons(chat_db):
    owner, foreign = _ambiguous_turn(chat_db)
    refused = _rpc("runtime.chat.turn.resolve", _resolve_params(owner, foreign.id))["error"]
    assert refused["code"] == ERR_CONFLICT and refused["data"]["reason"] == "foreign_chat_session"
    assert mission_chat_turn_record(session_id=owner.session_id, client_message_id="c1")["state"] == "outcome_unknown"
    result = _rpc("runtime.chat.turn.resolve", _resolve_params(owner, owner.id))["result"]
    assert result["journal_state"] == "abandoned" and result["resolution"] == "abandon"
    record = mission_chat_turn_record(session_id=owner.session_id, client_message_id="c1")
    assert record["state"] == "abandoned" and record["resolution_actor"] == owner.id
    again = _rpc("runtime.chat.turn.resolve", _resolve_params(owner, owner.id))["error"]
    assert again["data"]["reason"] == "chat_turn_resolution_mismatch"


def test_turn_resolve_argv_and_method_reach_one_implementation(monkeypatch, capsys):
    seen: list[dict] = []

    def resolve(**kwargs):
        seen.append(kwargs)
        return {"ok": True, "resolution": "abandon"}

    monkeypatch.setattr(turn_resolve_verb, "resolve_chat_turn", resolve)
    fields = {"session_id": "s", "client_message_id": "c", "turn_id": "t", "action": "abandon",
              "persona_instance_id": "pi", "reason": "r"}
    assert _rpc("runtime.chat.turn.resolve", fields)["result"] == {"ok": True, "resolution": "abandon"}
    assert chat_tickets_commands._cmd_mission_chat_turn_resolve(SimpleNamespace(json=True, **fields)) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "resolution": "abandon"}
    assert seen == [fields, fields]


# ── delete and create (through the mission-chat door) ───────────────────────


def test_delete_runs_the_argv_handler_and_returns_its_row(chat_db, capsys):
    instance = PersonaInstanceStore().create_operator_chat(persona_id="profile:reviewer", display_name="Reviewer")
    chat_db.create_session(instance.session_id, "agent_runtime_persona_chat")
    chat_db.append_message(instance.session_id, "user", "delete this")
    params = {"session_id": instance.session_id, "persona_id": instance.persona_id,
              "persona_instance_id": instance.id}
    result = _rpc("runtime.persona.chat.delete", params)["result"]
    assert capsys.readouterr().out == ""
    assert result["deleted_session"] is True and result["cleared_bindings"] == [instance.id]
    assert instance.session_id not in chat_db.sessions
    gone = _rpc("runtime.persona.chat.delete", params)["error"]
    assert gone["code"] == ERR_NOT_FOUND and gone["data"]["reason"] == "not_found"


def test_delete_refuses_a_root_owned_by_another_instance(chat_db):
    owner = PersonaInstanceStore().create_operator_chat(persona_id="dev", display_name="Dev")
    chat_db.create_session(owner.session_id, "agent_runtime_persona_chat")
    other = PersonaInstanceStore().add_instance(persona_id="qa", placement_id="other-placement_agent_9")
    error = _rpc("runtime.persona.chat.delete",
                 {"session_id": owner.session_id, "persona_instance_id": other.id})["error"]
    assert error["code"] == ERR_CONFLICT and error["data"]["reason"] == "foreign_chat_session"
    assert owner.session_id in chat_db.sessions


def test_create_mints_an_agent_profile_with_its_chat_root(chat_db, capsys):
    # ``profile:`` ids skip the roster check by decision D-U1; a bare id must be on it.
    reply = _rpc("runtime.persona.instance.create",
                 {"persona_id": "profile:reviewer", "display_name": "Dev two"})
    assert "result" in reply, reply
    result = reply["result"]
    assert capsys.readouterr().out == ""
    instance = PersonaInstanceStore().get(result["persona_instance_id"])
    assert instance.display_name == "Dev two"
    assert result["session_id"] == instance.default_chat_session_id
    assert result["session_id"] in chat_db.sessions
    assert result["add_instance"] is False


def test_create_refusals_carry_the_argv_rows_reason(chat_db):
    missing = _rpc("runtime.persona.instance.create", {"display_name": "x"})["error"]
    assert missing["code"] == ERR_INVALID_PARAMS and missing["data"]["reason"] == "invalid_request"
    unknown = _rpc("runtime.persona.instance.create", {"persona_id": "no_such_persona", "display_name": "x"})["error"]
    assert unknown["code"] == ERR_NOT_FOUND and unknown["data"]["reason"] == "persona_not_found"
    placement = _rpc("runtime.persona.instance.create",
                     {"persona_id": "profile:reviewer", "display_name": "x", "add_instance": True})["error"]
    assert placement["code"] == ERR_INVALID_PARAMS and "placement_id" in placement["message"]


def test_an_unbound_door_is_a_typed_refusal_not_a_silent_success(chat_db):
    bind_chat_verb(CHAT_DELETE_VERB, None)
    bind_chat_verb(INSTANCE_CREATE_VERB, None)
    try:
        for name, params in (("runtime.persona.chat.delete", {"session_id": "s"}),
                             ("runtime.persona.instance.create", {"persona_id": "dev", "display_name": "x"})):
            error = _rpc(name, params)["error"]
            assert error["code"] == ERR_HANDLER_FAILED
            assert error["data"]["reason"] == "mission_chat_door_unbound"
    finally:
        bind_mission_chat_door()
