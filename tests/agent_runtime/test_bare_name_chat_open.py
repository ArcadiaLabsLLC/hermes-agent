"""A chat opened on an agent's bare name goes through placement — row
``RT-FU-A-CHAT-OPENED-ON-AN-AGENTS-BARE-NAME-NO-LONGER-MAKES-A-HELD-ROW``.

Owner RULED 2026-11-22 ("yes b but remember if there is already an idle instance it replaces its chat with
the one you selected"). Driven through the entry point Eternia uses, ``runtime.persona.instance.open_chat``
(``chat_open._cmd_persona_instance_open_chat``):

* no idle instance of the agent in the Default workspace: one is placed, the selected chat becomes its
  live chat, and the placement announces ``persona_instance.created`` once;
* an idle instance there: no instance is made and nothing is announced; the selected chat replaces the
  chat that instance had;
* a refused placement answers ``agent_not_placed`` and writes no row;
* in no case is a row made under the bare id ``personainst_<persona>`` (the old held row).

"Idle" is ``agent_create.staff.idle_instances`` — the list Eternia asks over
``runtime.agent.idle_instances``: an instance of the agent seated in the Default workspace, not in a
running group chat, with no live run binding and no turn holding (or queued on) its chat root.
"""

from __future__ import annotations

import pytest

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE
from agent_runtime.chat_heads import resolve_conversation_chat_scope
from agent_runtime.default_scope import DEFAULT_WORKSPACE_ID, ensure_default_scope
from agent_runtime.events import EventLog
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_id_for
from agent_runtime.persona_chat_durability import (
    default_persona_session_db,
    ensure_persona_chat_session,
    persona_session_db_for,
)
from agent_runtime.persona_open_chat import OPEN_CHAT_METHOD
from agent_runtime.serve_rpc import RpcContext

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

BARE = persona_instance_id_for("dev")


def _rpc(params: dict) -> dict:
    return serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "r", "method": OPEN_CHAT_METHOD, "params": params},
        context=RpcContext(caller=LOCAL_CONSOLE),
    )


def _saved_chat_on_the_bare_name() -> str:
    """A saved chat minted for the agent's bare id, as a namespace from before the hidden copy went has."""

    chat = f"persona_chat_{BARE}_0123456789ab"
    db = persona_session_db_for(resolve_conversation_chat_scope(session_id=chat), process=default_persona_session_db)
    assert ensure_persona_chat_session(session_db=db, session_id=chat, persona_id="dev", title="old", required=True)
    db.append_message(chat, "user", "hello from before")
    return chat


def _all_events() -> list:
    return [evt for _, evt in EventLog().iter_from_offset(0)]


def _created_events() -> list[str]:
    return [e.payload.get("persona_instance_id") for e in _all_events() if e.type == "persona_instance.created"]


def _dev_rows() -> list[str]:
    return sorted(i.id for i in PersonaInstanceStore().list_all() if i.persona_id == "dev")


def test_a_bare_open_with_no_idle_instance_places_one_and_announces_it():
    """Kill-mutations: drop the door's placement in ``chat_open`` (the canonical arm's ``bare_agent``) →
    ``foreign_chat_session``, red; drop the announce in ``chat_binding._commit_chat_opened`` → no
    ``persona_instance.created``, red."""

    ensure_default_scope(seed_active_pointers=False)
    chat = _saved_chat_on_the_bare_name()

    reply = _rpc({"persona_id": "dev", "session_id": chat})

    assert "result" in reply, reply
    placed = reply["result"]["persona_instance_id"]
    assert placed.startswith(f"{BARE}_agent_")
    row = PersonaInstanceStore().get(placed)
    assert row.workspace_id == DEFAULT_WORKSPACE_ID
    assert row.default_chat_session_id == chat
    assert _dev_rows() == [placed]
    assert _created_events() == [placed]


def test_a_saved_chat_on_an_agents_bare_name_replaces_the_idle_instances_chat():
    """Kill-mutations: drop the move lane's bare-holder arm in ``persona_chat_move._holder_agent`` → the
    move refuses (``foreign_chat_session``), red; skip the reuse in ``staff.reuse_or_place`` → a second
    instance is placed and announced, red."""

    from agent_runtime.agent_create.staff import reuse_or_place

    ensure_default_scope(seed_active_pointers=False)
    idle, refusal = reuse_or_place("dev")
    assert refusal is None
    store = PersonaInstanceStore()
    its_chat = store.get(idle).default_chat_session_id
    assert its_chat
    announced_before = _created_events()
    chat = _saved_chat_on_the_bare_name()

    reply = _rpc({"persona_id": "dev", "session_id": chat})

    assert "result" in reply, reply
    result = reply["result"]
    assert result["persona_instance_id"] == idle
    assert result["previous_session_id"] == its_chat
    assert store.get(idle).default_chat_session_id == chat
    assert _dev_rows() == [idle]
    assert _created_events() == announced_before


def test_a_bare_open_whose_placement_is_refused_says_it_is_not_placed():
    """No Default workspace to place in: the open answers ``agent_not_placed`` in its own words and writes
    no row. Kill-mutation: answer ``foreign_chat_session`` in ``chat_open._place_for_bare_open`` → red."""

    chat = _saved_chat_on_the_bare_name()

    reply = _rpc({"persona_id": "dev", "session_id": chat})

    error = reply.get("error") or {}
    data = error.get("data") or {}
    assert data.get("error_kind") == "agent_not_placed", reply
    assert data.get("persona_instance_id") == BARE
    assert _dev_rows() == []


def test_a_bare_open_never_makes_a_row_under_the_bare_id():
    """Placed, then reused: nothing lands under ``personainst_<persona>``. Kill-mutation: drop the store guard
    in ``chat_binding._load_or_mint_chat_instance`` together with the door's canonical-arm placement → the
    open binds the bare id and makes the held row, red."""

    ensure_default_scope(seed_active_pointers=False)
    chat = _saved_chat_on_the_bare_name()
    assert "result" in _rpc({"persona_id": "dev", "session_id": chat})
    assert "result" in _rpc({"persona_id": "dev", "session_id": chat})
    assert BARE not in _dev_rows()


def test_a_placements_batch_stays_patch_coverable(monkeypatch):
    """The announce rides beside the create upsert as a covered domain event, so a placement's batch still
    ships as a patch frame for a client that folds creates. Kill-mutation: drop ``persona_instance.created``
    from ``patch_coverage.LIVE_COVERED_DOMAIN_EVENT_TYPES`` → red."""

    import agent_runtime.state_patches as sp
    from agent_runtime.agent_create.staff import reuse_or_place
    from agent_runtime.config import load_agent_runtime_config
    from agent_runtime.patch_coverage import PERSONA_INSTANCE_CREATE_CAPABILITY, batch_is_patch_coverable

    def _loader(*args, **kwargs):
        cfg = load_agent_runtime_config(*args, **kwargs)
        cfg.read_model.delta_patches = True
        return cfg

    monkeypatch.setattr(sp.emit, "load_root_runtime_config", _loader)
    ensure_default_scope(seed_active_pointers=False)
    floor = len(_all_events())
    placed, refusal = reuse_or_place("dev")
    assert refusal is None
    batch = [
        e for e in _all_events()[floor:]
        if (e.type == "state.patched" and (e.payload or {}).get("entity") == "persona_instance")
        or e.type in {"persona_instance.created", "persona_instance.chat_opened"}
    ]
    assert [e.type for e in batch].count("persona_instance.created") == 1
    assert "state.patched" in [e.type for e in batch]
    assert batch_is_patch_coverable(batch, fold_entities=["persona_instance", PERSONA_INSTANCE_CREATE_CAPABILITY])
