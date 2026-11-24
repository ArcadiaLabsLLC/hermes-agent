"""The agent list carries the two facts Eternia used to poll or read per chat.

* RT-FU-THE-AGENT-LIST-SAYS-WHICH-CHATS-WAIT-FOR-YOUR-ANSWER: every frame chat row carries
  ``clarify_token`` (the waiting question's token, or ``None``), in the core and in the root's
  ``persona_chat_turn`` overlay; an answer clears it, and a dismissal clears it through an event
  that rides that root's overlay.
* RT-FU-A-PENDING-APPROVAL-ARRIVES-AS-AN-UPDATE: a chat turn's approval is in the ``running_work``
  section's ``pending_approvals`` while it waits, announced by ``running_work.approval_raised`` and
  ``running_work.approval_settled``, which ride the section frame (alone) or the turn overlay (in a
  turn batch).

Real stores, the real overlay read, the real gateway queue; no serve or provider process.
Killing mutations, each red recorded in the landing commit: the row stamp writing ``None``; the
``clarify_dismissed`` change kind dropped from ``stream.frames``; ``_notify_root`` without its
``approval_raised`` call; the approval arm of ``_is_running_work_event`` dropped.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from agent_runtime.events import EventLog
from agent_runtime.persona_chat_continuity.clarify_tickets import PersonaChatClarifyTicketStore
from agent_runtime.persona_chat_history import persona_chat_frame_history
from agent_runtime.running_work.approval_presence import EVENT_APPROVAL_RAISED, EVENT_APPROVAL_SETTLED
from agent_runtime.stream.frames import batch_is_running_work_only, batch_turn_roots
from tests.agent_runtime.test_clarify_dismiss import _asked, _dismiss
from tests.agent_runtime.test_persona_chat_frame_bound import INSTANCE, _chats, _instance
from tests.agent_runtime.test_persona_chat_history_curation import FakeHistorySessionDB
from tests.agent_runtime.test_stream_turn_section import home  # noqa: F401 - the fixture
from tests.waiting import wait_until


def _events_since(offset: int):
    return [(int(at), event) for at, event in EventLog().iter_from_offset(offset)]


def _log_end() -> int:
    events = _events_since(0)
    return events[-1][0] if events else 0


def _rows(sessions) -> dict[str, dict]:
    rows = persona_chat_frame_history(persona_instances=[_instance(INSTANCE, "chat_029")],
                                      session_db=FakeHistorySessionDB(sessions))
    return {row["session_id"]: row for row in rows}


def test_a_waiting_question_puts_its_token_on_its_chats_row(isolate_agent_runtime_root):
    sessions = _chats(30)
    store = PersonaChatClarifyTicketStore()
    token = store.mint(chat_session_id="chat_003", question="Which branch?")

    rows = _rows(sessions)

    assert rows["chat_003"]["clarify_token"] == token
    assert {session: row["clarify_token"] for session, row in rows.items() if session != "chat_003"} == {
        session: None for session in rows if session != "chat_003"}

    store.settle(token, client_message_id="answer-1")
    rows = _rows(sessions)
    # Answered: the token clears, and the old chat is no longer pinned into the frame.
    assert "chat_003" not in rows
    assert all(row["clarify_token"] is None for row in rows.values())


def test_the_overlay_row_carries_the_token_and_an_answer_clears_it(isolate_agent_runtime_root, home):  # noqa: F811
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.persona_chat_durability import default_persona_session_db, ensure_persona_chat_session
    from agent_runtime.turn_section_read import read_turn_sections

    db = default_persona_session_db()
    root = f"persona_chat_{INSTANCE}_000000000001"
    assert ensure_persona_chat_session(session_db=db, session_id=root, persona_id="dev", title=root, required=True)
    db.append_message(root, "user", "hello")
    PersonaInstanceStore().open_chat(persona_id="dev", persona_instance_id=INSTANCE, session_id=root)
    store = PersonaChatClarifyTicketStore()
    token = store.mint(chat_session_id=root, persona_instance_id=INSTANCE, question="Ship it?")

    sections, _timings = read_turn_sections(root, named=(INSTANCE,))
    assert sections["persona_chat_history"]["clarify_token"] == token

    store.settle(token, client_message_id="answer-1")
    sections, _timings = read_turn_sections(root, named=(INSTANCE,))
    assert sections["persona_chat_history"]["clarify_token"] is None


def test_a_dismissed_question_rides_its_chats_overlay(tmp_path, monkeypatch):
    chat, token = _asked(tmp_path, monkeypatch)
    start = _log_end()

    assert _dismiss(chat["session_id"], token)["result"]["outcome"] == "dismissed"

    batch = _events_since(start)
    notices = [event for _at, event in batch if event.type == "persona_chat.metadata_updated"]
    assert [event.payload["change_kind"] for event in notices] == ["clarify_dismissed"]
    assert notices[0].payload["persona_instance_id"] == chat["persona_instance_id"]
    # The batch is a turn batch naming the chat's root, so the overlay re-reads that row alone.
    assert [root for root, _offset in batch_turn_roots(batch)] == [chat["session_id"]]
    # A second dismissal changes nothing and tells the stream nothing.
    again = _log_end()
    assert _dismiss(chat["session_id"], token)["result"]["outcome"] == "already_dismissed"
    assert _events_since(again) == []


def _manual_approvals():
    from hermes_constants import get_hermes_home

    home_dir = get_hermes_home()
    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "config.yaml").write_text(json.dumps({"approvals": {"mode": "manual", "timeout": 30}}),
                                          encoding="utf-8")


def test_a_turns_approval_reaches_the_running_work_section(isolate_agent_runtime_root):
    from agent_runtime.running_work import build_running_work
    from agent_runtime.session_controls import session_approval_scope
    from tools.approval import check_all_command_guards, resolve_gateway_approval, unregister_gateway_notify

    _manual_approvals()
    root = "approval-push-chat"
    start = _log_end()

    def guarded():
        with session_approval_scope(root):
            return check_all_command_guards("git reset --hard", "local")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(guarded)
        try:
            pending = wait_until(lambda: build_running_work()["pending_approvals"], what="the pushed approval")
            assert [(row["session_id"], row["command"]) for row in pending] == [(root, "git reset --hard")]
            assert {choice["id"] for choice in pending[0]["choices"]} == {"once", "deny"}
            raised = wait_until(lambda: [event for _at, event in _events_since(start)
                                         if event.type == EVENT_APPROVAL_RAISED], what="the raise notice")
            assert [(event.payload["root_chat_session_id"], event.payload["approval_id"]) for event in raised] == [
                (root, pending[0]["id"])]

            assert resolve_gateway_approval(root, "deny", request_id=pending[0]["id"]) == 1
            assert future.result(timeout=10)["approved"] is False
        finally:
            unregister_gateway_notify(root)
    settled = wait_until(lambda: [event for _at, event in _events_since(start) if event.type == EVENT_APPROVAL_SETTLED],
                         what="the settle notice")
    assert settled[0].payload["approval_id"] == pending[0]["id"]
    assert settled[0].payload["reason"] == "resolved"
    assert build_running_work()["pending_approvals"] == []


def test_an_approval_only_batch_ships_the_running_work_section_and_rides_a_turn_batch(isolate_agent_runtime_root):
    from agent_runtime.running_work.approval_presence import _append_approval_event

    start = _log_end()
    assert _append_approval_event(EVENT_APPROVAL_RAISED, "chat-a", "req-1", None)
    assert _append_approval_event(EVENT_APPROVAL_SETTLED, "chat-a", "req-1", "resolved")
    alone = _events_since(start)

    assert batch_is_running_work_only(alone)
    assert batch_turn_roots(alone) is None  # no root named: the section frame carries it

    from agent_runtime.chat_turn_presence import EVENT_TURN_STARTED
    from agent_runtime.models import Event
    from hermes_time import now

    EventLog().append(Event(type=EVENT_TURN_STARTED, task_id=None, run_id=None, persona_id=None, ts=now(),
                            payload={"persona_instance_id": INSTANCE, "root_chat_session_id": "chat-a",
                                     "client_message_id": "c1", "turn_id": "t1"}, session_id="chat-a"))
    with_turn = _events_since(start)
    assert [root for root, _offset in batch_turn_roots(with_turn)] == ["chat-a"]
