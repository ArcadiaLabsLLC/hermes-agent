"""A person archives one saved agent chat, and it leaves the Chat history but stays recoverable.

Row ``RT-A-PERSONA-CHAT-CAN-BE-ARCHIVED-FROM-ETERNIA`` (owner 2026-11-21, review w1118a.74). Driven through the
dispatcher: ``runtime.persona.chat.archive`` / ``.unarchive`` over ``set_session_archived``, and the listing
Eternia's Chat history reads (``runtime.operator.conversation.list``).

Killing mutations (run 2026-11-21):
- drop the listing's archived clause (``instance_history._history_page``) ->
  ``test_an_archived_chat_leaves_the_history_and_unarchive_brings_it_back`` red;
- drop the loaded-chat refusal (``chat_verbs.archive``) -> ``test_an_instances_loaded_chat_is_not_archived`` red;
- write without the root lease -> ``test_a_chat_a_turn_is_running_on_is_not_archived`` red.
- skip the archived-only predicate (2026-11-25) ->
  ``test_archive_only_pages_deliberate_archives_for_the_current_account`` returns an active chat.
"""

from __future__ import annotations

from contextlib import closing

from agent_runtime import serve_rpc
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_continuity import persona_chat_root_lease
from tests.agent_runtime.test_instance_conversation_owner import chat_head  # noqa: F401 — autouse fixture
from tests.agent_runtime.test_instance_history import OWNER, OTHER, create, default_persona_session_db, read_history
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # noqa: F401 — fixtures


def _archive(session_id: str, *, method: str = "runtime.persona.chat.archive", **params) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "arc", "method": method,
                                     "params": {"session_id": session_id, **params}})


def _listed(**params) -> set[str]:
    return {row["session_id"] for row in read_history(**params)["result"]["conversations"]}


def _two_chats(placed_agent) -> tuple[str, str]:
    """``(saved, loaded)``: an older chat in the history, and the one now open on the instance."""

    saved = create(placed_agent, "first")
    loaded = create(placed_agent, "second")
    assert PersonaInstanceStore().get(placed_agent["persona_instance_id"]).default_chat_session_id == loaded
    return saved, loaded


def test_an_archived_chat_leaves_the_history_and_unarchive_brings_it_back(placed_agent):
    saved, loaded = _two_chats(placed_agent)
    assert {saved, loaded} <= _listed()

    reply = _archive(saved, persona_instance_id=placed_agent["persona_instance_id"], client_scope=OWNER)

    assert reply["result"]["archived"] is True and reply["result"]["changed"] is True, reply
    assert saved not in _listed() and loaded in _listed()
    archived_rows = read_history(include_archived=True)["result"]["conversations"]
    assert next(row for row in archived_rows if row["session_id"] == saved)["state"] == "archived"

    back = _archive(saved, method="runtime.persona.chat.unarchive", client_scope=OWNER)

    assert back["result"]["archived"] is False and back["result"]["changed"] is True, back
    assert saved in _listed()


def test_an_instances_loaded_chat_is_not_archived(placed_agent):
    _saved, loaded = _two_chats(placed_agent)

    reply = _archive(loaded, client_scope=OWNER)

    assert reply["error"]["data"]["reason"] == "chat_is_loaded", reply
    assert reply["error"]["data"]["persona_instance_id"] == placed_agent["persona_instance_id"]
    assert loaded in _listed()


def test_archive_only_pages_deliberate_archives_for_the_current_account(placed_agent):
    first = create(placed_agent, "first-archive")
    second = create(placed_agent, "second-archive")
    other = create(placed_agent, "other-archive", OTHER)
    idle = create(placed_agent, "idle")
    live = create(placed_agent, "live")
    for saved, owner in ((first, OWNER), (second, OWNER), (other, OTHER)):
        assert _archive(saved, client_scope=owner)["result"]["archived"]
    # Idle-sweep archive has its own provenance on the same stored row.
    with closing(default_persona_session_db()) as db:
        assert db.get_session(live) is not None
        db._write_sql("UPDATE sessions SET archived=1, auto_archived=1 WHERE id=?", (idle,))

    page = read_history(archived_only=True, limit=1)["result"]
    assert len(page["conversations"]) == 1
    cursor = page["next_cursor"]
    assert cursor is not None
    assert "error" in read_history(before=cursor, limit=1)
    last = read_history(archived_only=True, before=cursor, limit=1)["result"]
    assert last["next_cursor"] is None
    assert {row["session_id"] for row in page["conversations"] + last["conversations"]} == {first, second}
    assert {live, idle} <= _listed()

    assert _archive(first, method="runtime.persona.chat.unarchive", client_scope=OWNER)["result"]["changed"]
    assert _listed(archived_only=True) == {second}


def test_a_chat_a_turn_is_running_on_is_not_archived(placed_agent):
    saved, _loaded = _two_chats(placed_agent)

    with persona_chat_root_lease(saved, owner_id="turn-in-flight", observer_kind="turn"):
        reply = _archive(saved, client_scope=OWNER)

    assert reply["error"]["data"]["reason"] == "chat_busy", reply
    assert saved in _listed()


def test_another_accounts_chat_and_a_wrong_pin_are_refused(placed_agent):
    saved, _loaded = _two_chats(placed_agent)

    other = _archive(saved, client_scope=OTHER)
    pinned = _archive(saved, persona_instance_id="personainst_someone_else", client_scope=OWNER)
    missing = _archive("persona_chat_no_such_root", client_scope=OWNER)

    assert other["error"]["data"]["reason"] == "conversation_owner_changed"
    assert pinned["error"]["data"]["reason"] == "foreign_chat_session"
    assert missing["error"]["data"]["reason"] == "not_found"
    assert saved in _listed()


def test_both_verbs_are_console_tier_writes_in_the_manifest():
    manifest = serve_rpc.manifest()
    for method in ("runtime.persona.chat.archive", "runtime.persona.chat.unarchive"):
        assert method in manifest["methods"]
        assert manifest["tiers"][method] == "console"
    assert {"include_archived", "archived_only"} <= set(manifest["params"]["runtime.operator.conversation.list"])
