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
