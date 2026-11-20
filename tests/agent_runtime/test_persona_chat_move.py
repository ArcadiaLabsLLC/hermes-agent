"""A saved chat moves to another instance of its agent — ``persona_chat_move.move_chat``.

Row ``RT-A-SAVED-CHAT-CAN-MOVE-TO-ANOTHER-INSTANCE-OF-ITS-AGENT`` (owner
2026-11-19, "Reuse idle, else new"). Driven through the entry point Eternia
uses, ``runtime.persona.instance.open_chat`` with ``move: true``:

* a chat of instance A opens on instance B of the same agent, B holds it, A lets
  it go, and it is the SAME transcript row with its history (never copied);
* after the move B opens and resolves it as its own without ``move``
  (``assert_bindable``, ``_persona_chat_session_owner``,
  ``resolve_default_chat_session_id_for_instance``);
* a chat of a DIFFERENT agent is still refused, and nothing moves;
* a chat with a turn running in it (its root lease held) does not move;
* a relay sent from a moved chat names the instance holding it.

UNCOVERED SEAM: the ``hermes harness persona instance open-chat --move`` argv
door is the same handler (``chat_open._cmd_persona_instance_open_chat``) and is
not driven separately here.
"""

from __future__ import annotations

import pytest

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE
from agent_runtime.chat_heads import resolve_conversation_chat_scope
from agent_runtime.mission_chat_outcome import ChatErrorKind
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    resolve_default_chat_session_id_for_instance,
)
from agent_runtime.persona_assignments.chat_moves import load_chat_moves
from agent_runtime.persona_chat_continuity import persona_chat_root_lease
from agent_runtime.persona_chat_durability import (
    default_persona_session_db,
    persona_session_db_for,
)
from agent_runtime.persona_chat_session import _persona_chat_session_owner, _session_model_config
from agent_runtime.persona_open_chat import OPEN_CHAT_METHOD
from agent_runtime.serve_rpc import ERR_CONFLICT, RpcContext
from tests.agent_runtime.office_seed import seed_workspace_record

WORKSPACE = "ws_chat_move_test"


def _rpc(method: str, params: dict, rid: str = "r") -> dict:
    return serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": rid, "method": method, "params": params},
        context=RpcContext(caller=LOCAL_CONSOLE),
    )


def _save_persona(persona_id: str, name: str) -> None:
    from agent_runtime.models import AgentPersona
    from agent_runtime.store import AgentStore

    AgentStore().save(
        AgentPersona(id=persona_id, display_name=name, role=persona_id, model=None,
                     provider=None, api_mode=None, system_prompt_path="")
    )


def _place(persona_id: str, key: str) -> dict:
    """One more instance of the EXISTING agent (``runtime.agent.place``), with its chat."""

    reply = _rpc(
        "runtime.agent.place",
        {"persona_id": persona_id, "workspace_id": WORKSPACE, "idempotency_key": key},
        rid=key,
    )
    assert "result" in reply, reply
    placed = reply["result"]
    assert placed["persona_id"] == persona_id
    if not placed.get("default_chat_session_id"):
        opened = _rpc(OPEN_CHAT_METHOD, {"persona_id": persona_id, "new_session": True,
                                         "persona_instance_id": placed["persona_instance_id"],
                                         "idempotency_key": f"{key}-chat"})
        assert "result" in opened, opened
        placed = {**placed, "default_chat_session_id": opened["result"]["session_id"]}
    return placed


def _db(session_id: str):
    return persona_session_db_for(
        resolve_conversation_chat_scope(session_id=session_id), process=default_persona_session_db
    )


@pytest.fixture
def two_qa_instances(isolate_agent_runtime_root):
    from agent_runtime.office_store import OfficeStore

    _save_persona("qa", "QA Agent")
    seed_workspace_record(WORKSPACE)
    OfficeStore().ensure_surface(WORKSPACE, created_by="seed")
    first = _place("qa", "move-a")
    second = _place("qa", "move-b")
    assert first["persona_instance_id"] != second["persona_instance_id"]
    return first, second


def test_a_saved_chat_moves_to_another_instance_of_its_agent_with_its_history(two_qa_instances):
    first, second = two_qa_instances
    chat = first["default_chat_session_id"]
    db = _db(chat)
    db.append_message(chat, "user", "hello from the first instance")
    sessions_before = len(db.list_sessions_rich(limit=100)) if hasattr(db, "list_sessions_rich") else None

    reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                                    "session_id": chat, "move": True})

    assert "result" in reply, reply
    result = reply["result"]
    assert result["persona_instance_id"] == second["persona_instance_id"]
    assert result["session_id"] == chat
    assert result["moved_from_persona_instance_id"] == first["persona_instance_id"]
    store = PersonaInstanceStore()
    assert store.get(second["persona_instance_id"]).default_chat_session_id == chat
    assert store.get(first["persona_instance_id"]).default_chat_session_id is None
    db = _db(chat)
    assert [m["content"] for m in db.get_messages(chat)] == ["hello from the first instance"]
    assert _session_model_config(db, chat)["persona_instance_id"] == second["persona_instance_id"]
    assert _persona_chat_session_owner(db, chat) == second["persona_instance_id"]
    if sessions_before is not None:
        assert len(db.list_sessions_rich(limit=100)) == sessions_before


def test_after_the_move_the_new_instance_opens_the_chat_as_its_own(two_qa_instances):
    first, second = two_qa_instances
    chat = first["default_chat_session_id"]
    _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                            "session_id": chat, "move": True})

    again = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                                    "session_id": chat})
    assert again["result"]["persona_instance_id"] == second["persona_instance_id"]
    assert resolve_default_chat_session_id_for_instance(
        PersonaInstanceStore(), persona_id="qa", persona_instance_id=second["persona_instance_id"]
    ) == chat
    # The instance it left no longer holds it.
    refused = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": first["persona_instance_id"],
                                      "session_id": chat})
    assert refused["error"]["data"]["reason"] == ChatErrorKind.FOREIGN_CHAT_SESSION


def test_a_chat_of_a_different_agent_is_still_refused_and_nothing_moves(two_qa_instances):
    first, _second = two_qa_instances
    _save_persona("qb", "QB Agent")
    other = _place("qb", "move-c")
    chat = other["default_chat_session_id"]

    for persona in ("qa", "qb"):
        reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": persona, "persona_instance_id": first["persona_instance_id"],
                                        "session_id": chat, "move": True})
        assert reply["error"]["code"] == ERR_CONFLICT
        assert reply["error"]["data"]["reason"] == ChatErrorKind.FOREIGN_CHAT_SESSION
    assert load_chat_moves() == {}
    assert PersonaInstanceStore().get(first["persona_instance_id"]).default_chat_session_id == first["default_chat_session_id"]
    assert _persona_chat_session_owner(_db(chat), chat) == other["persona_instance_id"]


def test_a_chat_with_a_turn_running_in_it_does_not_move(two_qa_instances):
    first, second = two_qa_instances
    chat = first["default_chat_session_id"]

    with persona_chat_root_lease(chat, owner_id="running-turn", observer_kind="turn"):
        reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                                        "session_id": chat, "move": True})

    assert reply["error"]["code"] == ERR_CONFLICT
    assert reply["error"]["data"]["reason"] == ChatErrorKind.CHAT_BUSY
    assert load_chat_moves() == {}
    assert _persona_chat_session_owner(_db(chat), chat) == first["persona_instance_id"]
    assert PersonaInstanceStore().get(first["persona_instance_id"]).default_chat_session_id == chat


def test_without_move_a_sibling_chat_is_refused_as_before(two_qa_instances):
    first, second = two_qa_instances
    reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                                    "session_id": first["default_chat_session_id"]})
    assert reply["error"]["data"]["reason"] == ChatErrorKind.FOREIGN_CHAT_SESSION
    assert load_chat_moves() == {}


def test_a_relay_sent_from_a_moved_chat_names_the_instance_that_holds_it(two_qa_instances):
    from hermes_cli.harness_parts.persona.chat_history_writes import _resolve_relay_sender_marker

    first, second = two_qa_instances
    chat = first["default_chat_session_id"]
    _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                            "session_id": chat, "move": True})

    marker = _resolve_relay_sender_marker(
        f"agent:{chat}", instance_store=PersonaInstanceStore(), relay_chain_in=None
    )
    assert second["persona_instance_id"] in marker
    assert first["persona_instance_id"] not in marker


def test_an_old_chat_of_a_retired_instance_opens_on_another_instance_of_its_agent(two_qa_instances):
    """RT-FU-A-DELETED-INSTANCES-OLD-CHAT-OPENS-ON-ANOTHER-INSTANCE (review w1118a.56 D13): the holder's
    agent is read from its retirement archive, so the chat moves with its history.
    Mutation: ``_holder_agent`` without the archive fallback → ``foreign_chat_session``."""

    first, second = two_qa_instances
    chat = first["default_chat_session_id"]
    _db(chat).append_message(chat, "user", "written before the retire")
    store = PersonaInstanceStore()
    store.retire(first["persona_instance_id"], reason="chat panel x")
    assert store.retired_instance_row(first["persona_instance_id"]).persona_id == "qa"

    reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                                    "session_id": chat, "move": True})

    assert "result" in reply, reply
    assert reply["result"]["persona_instance_id"] == second["persona_instance_id"]
    assert reply["result"]["moved_from_persona_instance_id"] == first["persona_instance_id"]
    assert PersonaInstanceStore().get(second["persona_instance_id"]).default_chat_session_id == chat
    db = _db(chat)
    assert [m["content"] for m in db.get_messages(chat)] == ["written before the retire"]
    assert _persona_chat_session_owner(db, chat) == second["persona_instance_id"]
    again = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                                    "session_id": chat})
    assert again["result"]["persona_instance_id"] == second["persona_instance_id"]


def test_a_retired_instances_chat_never_moves_to_a_different_agent(two_qa_instances):
    """Mutation: ``move_chat``'s agent check reduced to ``holder_persona is None`` → the move goes through."""

    first, _second = two_qa_instances
    _save_persona("qb", "QB Agent")
    other = _place("qb", "move-d")
    chat = first["default_chat_session_id"]
    PersonaInstanceStore().retire(first["persona_instance_id"], reason="chat panel x")

    for persona in ("qa", "qb"):
        reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": persona, "persona_instance_id": other["persona_instance_id"],
                                        "session_id": chat, "move": True})
        assert reply["error"]["data"]["reason"] == ChatErrorKind.FOREIGN_CHAT_SESSION, reply
    assert load_chat_moves() == {}


def test_a_retired_instances_chat_without_move_is_still_refused(two_qa_instances):
    first, second = two_qa_instances
    PersonaInstanceStore().retire(first["persona_instance_id"], reason="chat panel x")
    reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": second["persona_instance_id"],
                                    "session_id": first["default_chat_session_id"]})
    assert "error" in reply, reply
    assert load_chat_moves() == {}
