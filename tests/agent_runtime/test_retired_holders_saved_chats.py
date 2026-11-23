"""An agent's saved chats stay in Chat history after the copy that held them is retired.

Row ``RT-AN-AGENTS-SAVED-CHATS-STAY-IN-CHAT-HISTORY-AFTER-THE-COPY-THAT-HELD-THEM-IS-RETIRED`` (plan
``agent-template-vs-canonical-instance-2026-11-21`` §5(ii); owner RULED 2026-11-21: "a live chat belongs to
an instance, because chat history is still a thing"; reviews w1118a.78 and .79). Read in code before it:
``persona_chat_history/summary.py`` listed a session only through a LIVE instance, so a retired holder's chat
was dropped (``instance_retired``) when its agent had no other instance, and listed as ANOTHER instance's
chat when it had one. The fixture places real instances (``runtime.agent.place``), writes a turn into the
real chat store, retires the holder through the first-class verb, and reads the projection the snapshot's
Chat history frame reads, over the live roster.
"""

from __future__ import annotations

import pytest

from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_history import persona_chat_history_summary
from tests.agent_runtime.test_persona_chat_move import OPEN_CHAT_METHOD, _db, _place, _rpc, _save_persona

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root")


@pytest.fixture
def qa_workspace():
    from agent_runtime.office_store import OfficeStore
    from tests.agent_runtime.office_seed import seed_workspace_record
    from tests.agent_runtime.test_persona_chat_move import WORKSPACE

    _save_persona("qa", "QA Agent")
    seed_workspace_record(WORKSPACE)
    OfficeStore().ensure_surface(WORKSPACE, created_by="seed")


def _history(chat: str) -> dict | None:
    rows = persona_chat_history_summary(persona_instances=PersonaInstanceStore().list_all())
    return next((row for row in rows if row["session_id"] == chat), None)


def _retired_chat(key: str) -> tuple[dict, str]:
    placed = _place("qa", key)
    chat = placed["default_chat_session_id"]
    _db(chat).append_message(chat, "user", "written before the retire")
    PersonaInstanceStore().retire(placed["persona_instance_id"], reason="desk removed")
    return placed, chat


def test_a_retired_holders_chat_lists_under_its_agent(qa_workspace):
    """The agent has no other instance. Kill-mutation: drop the retired-holder arm in
    ``HistorySummary.session_candidates`` → the chat is dropped, red."""
    placed, chat = _retired_chat("hist-a")
    row = _history(chat)
    assert row is not None
    assert (row["persona_id"], row["persona_instance_id"], row["holder_retired"]) == (
        "qa", placed["persona_instance_id"], True)
    assert row["message_count"] >= 1  # its turns came with it (the transcript was read)


def test_with_another_live_instance_the_chat_stays_the_agents_not_that_instances(qa_workspace):
    """Kill-mutation: ask ``instances_by_persona`` before the retired-holder arm → the chat is listed
    as the live sibling's, red."""
    placed, chat = _retired_chat("hist-b")
    sibling = _place("qa", "hist-c")
    row = _history(chat)
    assert row is not None
    assert row["persona_instance_id"] == placed["persona_instance_id"] != sibling["persona_instance_id"]
    assert row["holder_retired"] is True
    assert "holder_retired" not in (_history(sibling["default_chat_session_id"]) or {})


def test_it_opens_onto_a_placement_with_its_turns(qa_workspace):
    """Opening it is the existing ``open_chat`` with ``move: true`` onto a placement; the row then
    lists as that live instance's chat, no longer flagged."""
    _, chat = _retired_chat("hist-d")
    target = _place("qa", "hist-e")
    reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": target["persona_instance_id"],
                                    "session_id": chat, "move": True})
    assert "result" in reply, reply
    row = _history(chat)
    assert row["persona_instance_id"] == target["persona_instance_id"]
    assert "holder_retired" not in row
    assert [m["content"] for m in _db(chat).get_messages(chat)] == ["written before the retire"]


def test_an_operator_channel_does_not_warn_about_a_retired_holders_chat(qa_workspace):
    """Kill-mutation: drop the ``holder_retired`` arm in ``operator_channel_summary`` → the channel
    carries ``history_without_instance``, red."""
    from agent_runtime.operator_channels.summary import operator_channel_summary

    _, chat = _retired_chat("hist-f")
    instances = PersonaInstanceStore().list_all()
    channels = operator_channel_summary(
        persona_instances=instances,
        persona_chat_history=persona_chat_history_summary(persona_instances=instances),
        persona_chat_trace=[],
    )
    codes = [w.get("code") for channel in channels for w in (channel.get("warnings") or [])]
    assert "history_without_instance" not in codes


def _directory_row(chat: str) -> dict | None:
    from agent_runtime import paths, serve_rpc
    from agent_runtime.call_authorization import LOCAL_CONSOLE
    from agent_runtime.gateway_identity import ensure_install_identity

    install = ensure_install_identity(paths.store_root()).install_id
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "dir", "method": "runtime.operator.conversation.list",
                                      "params": {"install_id": install, "all_accounts": True}},
                                     serve_rpc.RpcContext(caller=LOCAL_CONSOLE))
    assert "result" in reply, reply
    return next((row for row in reply["result"]["conversations"] if row["session_id"] == chat), None)


def test_a_retired_holders_chat_says_so_in_the_directory(qa_workspace):
    """Row RT-FU-A-RETIRED-HOLDERS-CHAT-SAYS-SO-IN-THE-CHAT-DIRECTORY: ``runtime.operator.conversation.list``
    (Eternia's AI Chat history) flags the retired holder as the snapshot's Chat history does, and a live
    holder's chat says ``False``. Kill-mutation: answer ``holder_retired=False`` in
    ``_project_instance_history`` -> red."""
    placed, chat = _retired_chat("dir-a")
    live = _place("qa", "dir-b")
    row = _directory_row(chat)
    assert row is not None
    assert (row["persona_id"], row["persona_instance_id"], row["available"], row["holder_retired"]) == (
        "qa", placed["persona_instance_id"], False, True)
    # the workspace and name the retired instance had, so a client lists it where the chat lived
    assert (row["workspace_id"], row["display_name"]) == (placed["workspace_id"], placed["display_name"])
    assert row["workspace_id"] is not None
    live_row = _directory_row(live["default_chat_session_id"])
    assert live_row is not None and (live_row["available"], live_row["holder_retired"]) == (True, False)


def test_a_holder_gone_without_a_retire_is_not_flagged(qa_workspace):
    """A holder whose row vanished without the retire verb (no tombstone) is unavailable, never
    ``holder_retired``: only the archive says an instance was retired. Kill-mutation: answer
    ``holder_retired=instance is None`` -> red."""
    from agent_runtime import paths

    placed = _place("qa", "dir-c")
    chat = placed["default_chat_session_id"]
    _db(chat).append_message(chat, "user", "written before the row vanished")
    (paths.persona_instances_dir() / (placed["persona_instance_id"] + ".json")).unlink()
    row = _directory_row(chat)
    assert row is not None and (row["available"], row["holder_retired"]) == (False, False)


# --- A retired holder whose chats live in its OWN profile (a ``per_profile`` head) -------------------------
#
# Row RT-FU-A-RETIRED-HOLDERS-CHAT-IN-ITS-OWN-PROFILE-STAYS-IN-THE-CHAT-LISTS (seen live 2026-11-22 by
# w1122d-mcfu: Neko's only instance retired, its chat only in ``profiles/neko/state.db``, gone from Chat
# history). The tests above place instances on the process head, so they never reach this case. Here the
# holder records the profile ``alice`` as its head (checked by a probe), its chat is written ONLY there, and
# no live instance of its agent is left: both chat-list readers must still open that head.

PROFILE_CHAT = "persona_chat_personainst_qa_agent_1_00000000000b"
PROCESS_CHAT = "persona_chat_personainst_dev_agent_1_00000000000a"


@pytest.fixture
def profile_heads(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    base, alice = root / "profiles" / "base", root / "profiles" / "alice"
    for path in (base, alice):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(base))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    return {"base": base, "alice": alice}


def _write_chat(home, persona_id: str, session_id: str, text: str, *, client_scope: str | None = None) -> None:
    from contextlib import closing

    from hermes_state import SessionDB

    from agent_runtime.persona_chat_durability import ensure_persona_chat_session

    with closing(SessionDB(db_path=home / "state.db")) as db:
        ensure_persona_chat_session(session_db=db, session_id=session_id, persona_id=persona_id,
                                    title=f"{persona_id} saved chat", required=True, client_scope=client_scope)
        db.append_message(session_id=session_id, role="user", content=text)


def _retired_profile_holder(profile_heads, *, client_scope: str | None = None) -> str:
    """``dev`` lives on the process head; ``qa``'s ONLY instance holds a chat in ``alice`` and is retired."""

    from agent_runtime.chat_session_scope import resolve_instance_chat_scope
    from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE

    store = PersonaInstanceStore()
    store.open_chat(persona_id="dev", persona_instance_id="personainst_dev_agent_1", session_id=PROCESS_CHAT)
    _write_chat(profile_heads["base"], "dev", PROCESS_CHAT, "from base")
    holder = store.open_chat(persona_id="qa", persona_instance_id="personainst_qa_agent_1", session_id=PROFILE_CHAT)
    holder.chat_head_home, holder.chat_head_kind = str(profile_heads["alice"]), CHAT_HEAD_KIND_PER_PROFILE
    store.update(holder)
    _write_chat(profile_heads["alice"], "qa", PROFILE_CHAT, "saved in its own profile", client_scope=client_scope)
    # The probe: the holder reads and writes on alice's head, and the process store never saw the chat.
    assert resolve_instance_chat_scope(store.get(holder.id)).db_path == profile_heads["alice"] / "state.db"
    from contextlib import closing

    from hermes_state import SessionDB

    with closing(SessionDB(db_path=profile_heads["base"] / "state.db")) as base_db:
        assert base_db.get_session(PROFILE_CHAT) is None
    store.retire(holder.id, reason="desk removed")
    assert [i.persona_id for i in store.list_all()] == ["dev"]  # no live instance of qa is left
    return holder.id


@pytest.fixture
def archive_reads(monkeypatch):
    """How many times one read lists the retirement archive and decodes each tombstone."""

    from collections import Counter

    from agent_runtime.persona_assignments import retire

    counts: Counter = Counter()
    real_ids, real_row = retire.retired_persona_instance_ids, retire.retired_instance_row

    def ids():
        counts["listing"] += 1
        return real_ids()

    def row(store, instance_id):
        counts[instance_id] += 1
        return real_row(store, instance_id)

    monkeypatch.setattr(retire, "retired_persona_instance_ids", ids)
    monkeypatch.setattr(retire, "retired_instance_row", row)
    return counts


def test_a_retired_holders_chat_in_its_own_profile_stays_in_the_snapshots_chat_history(profile_heads, archive_reads):
    """Kill-mutations: drop ``retired.rows(...)`` from ``chat_heads.holder_read_heads``; or call
    ``per_profile_read_heads`` over the live instances in ``persona_chat_history_summary``; or ask the
    retired-holder arm on the process pass only (``instance is None and head is None``) -> red."""
    holder = _retired_profile_holder(profile_heads)
    row = _history(PROFILE_CHAT)
    assert row is not None
    assert (row["persona_id"], row["persona_instance_id"], row["holder_retired"]) == ("qa", holder, True)
    assert row["title"] == "qa saved chat"
    assert row["messages"][-1]["text"] == "saved in its own profile"
    # One build lists the archive once and decodes the tombstone once, though it both opened the
    # holder's head and flagged its row. Kill-mutation: a fresh ``RetiredHolders`` in
    # ``HistorySummary._retired_holder`` -> red.
    assert (archive_reads["listing"], archive_reads[holder]) == (1, 1)


def test_a_retired_holders_chat_in_its_own_profile_stays_in_the_chat_directory(profile_heads, archive_reads):
    """``runtime.operator.conversation.list`` (Eternia's AI Chat history). Kill-mutations: drop
    ``retired.rows(...)`` from ``chat_heads.holder_read_heads``; or call ``per_profile_read_heads``
    over ``scan.instances`` in ``list_instance_conversations`` -> red."""
    holder = _retired_profile_holder(profile_heads)
    row = _directory_row(PROFILE_CHAT)
    assert row is not None
    assert (row["persona_id"], row["persona_instance_id"], row["available"], row["holder_retired"]) == (
        "qa", holder, False, True)
    assert row["title"] == "qa saved chat"
    assert row["last_message_preview"] == "saved in its own profile"
    # One page lists the archive once and decodes the tombstone once. Kill-mutation: project the rows
    # with ``retired=None`` in ``list_instance_conversations`` -> red.
    assert (archive_reads["listing"], archive_reads[holder]) == (1, 1)


# --- Opening that retired holder's chat moves it onto a live instance of its agent --------------------------
#
# Row RT-FU-A-REMOVED-INSTANCES-SAVED-CHAT-MOVES-ONTO-A-LIVE-INSTANCE-OF-ITS-AGENT (seen live 2026-11-22 by
# w1122d-gonechat: Neko's instance removed by its x, a new Neko placed by a send, the old chat's
# ``open_chat`` with ``move: true`` answered ``unknown_chat_session``). ``resolve_conversation_chat_scope``
# named the retired holder from the session id, found no live row and answered the PROCESS scope, where a
# ``per_profile`` holder's chat is not. Driven through Eternia's entry point, ``runtime.persona.instance.open_chat``.

OWNER_SCOPE, OTHER_SCOPE = "a" * 64, "b" * 64
TARGET_CHAT = "persona_chat_personainst_qa_agent_2_00000000000c"


def _live_profile_instance(profile_heads, persona_id: str, instance_id: str, session_id: str) -> str:
    """A live instance of ``persona_id`` on the same ``alice`` head, holding a chat of its own."""

    from agent_runtime.models import CHAT_HEAD_KIND_PER_PROFILE

    store = PersonaInstanceStore()
    placed = store.open_chat(persona_id=persona_id, persona_instance_id=instance_id, session_id=session_id)
    placed.chat_head_home, placed.chat_head_kind = str(profile_heads["alice"]), CHAT_HEAD_KIND_PER_PROFILE
    store.update(placed)
    _write_chat(profile_heads["alice"], persona_id, session_id, "the new instance's own chat")
    return placed.id


def _alice_db(profile_heads):
    from hermes_state import SessionDB

    return SessionDB(db_path=profile_heads["alice"] / "state.db")


def _moved_events() -> list[dict]:
    import json

    from agent_runtime import paths
    from agent_runtime.persona_chat_move import CHAT_MOVED_EVENT

    log = paths.store_root() / "events.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [e for e in map(json.loads, lines) if e.get("type") == CHAT_MOVED_EVENT]


def test_a_retired_holders_chat_in_its_own_profile_moves_onto_a_live_instance_of_its_agent(profile_heads):
    """Kill-mutation: ``chat_heads._load_instance`` returns ``None`` where it now falls back to
    ``retired_instance_row`` -> ``unknown_chat_session`` (the process store answered), red."""
    from contextlib import closing

    from agent_runtime.persona_chat_session import _persona_chat_session_owner

    holder = _retired_profile_holder(profile_heads)
    target = _live_profile_instance(profile_heads, "qa", "personainst_qa_agent_2", TARGET_CHAT)

    reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": target,
                                    "session_id": PROFILE_CHAT, "move": True})

    assert "result" in reply, reply
    assert (reply["result"]["persona_instance_id"], reply["result"]["moved_from_persona_instance_id"]) == (
        target, holder)
    assert PersonaInstanceStore().get(target).default_chat_session_id == PROFILE_CHAT
    with closing(_alice_db(profile_heads)) as db:
        assert [m["content"] for m in db.get_messages(PROFILE_CHAT)] == ["saved in its own profile"]
        assert _persona_chat_session_owner(db, PROFILE_CHAT) == target
    moved = _moved_events()
    assert [(e["payload"]["session_id"], e["payload"]["from_persona_instance_id"],
             e["payload"]["to_persona_instance_id"]) for e in moved] == [(PROFILE_CHAT, holder, target)]


def test_a_retired_holders_chat_in_its_own_profile_never_moves_to_a_different_agent(profile_heads):
    """With the holder's own store now found, the same-agent check runs on it. Kill-mutation:
    ``personas_equal(owner_persona, persona_id)`` in ``chat_open`` answered ``True`` -> the move goes through, red."""
    from contextlib import closing

    from agent_runtime.persona_chat_session import _persona_chat_session_owner

    holder = _retired_profile_holder(profile_heads)
    other = _live_profile_instance(profile_heads, "qb", "personainst_qb_agent_1",
                                   "persona_chat_personainst_qb_agent_1_00000000000d")

    for persona in ("qa", "qb"):
        reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": persona, "persona_instance_id": other,
                                        "session_id": PROFILE_CHAT, "move": True})
        assert reply["error"]["data"]["reason"] == "foreign_chat_session", reply
    assert _moved_events() == []
    with closing(_alice_db(profile_heads)) as db:
        assert _persona_chat_session_owner(db, PROFILE_CHAT) == holder


def test_a_retired_holders_chat_in_its_own_profile_never_moves_for_another_account(profile_heads):
    """With the holder's own store now found, the account check runs on it. Kill-mutation: drop
    ``require_session_owner`` in ``chat_open`` -> the other account's move goes through, red."""
    from contextlib import closing

    from agent_runtime.persona_chat_session import _persona_chat_session_owner

    holder = _retired_profile_holder(profile_heads, client_scope=OWNER_SCOPE)
    target = _live_profile_instance(profile_heads, "qa", "personainst_qa_agent_2", TARGET_CHAT)

    reply = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": target, "session_id": PROFILE_CHAT,
                                    "move": True, "client_scope": OTHER_SCOPE})

    assert reply["error"]["data"]["reason"] == "conversation_owner_changed", reply
    assert _moved_events() == []
    with closing(_alice_db(profile_heads)) as db:
        assert _persona_chat_session_owner(db, PROFILE_CHAT) == holder
    owned = _rpc(OPEN_CHAT_METHOD, {"persona_id": "qa", "persona_instance_id": target, "session_id": PROFILE_CHAT,
                                    "move": True, "client_scope": OWNER_SCOPE})
    assert "result" in owned, owned
