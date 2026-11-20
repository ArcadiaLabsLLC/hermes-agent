"""Stopping a request ends the turn it started on the other agent, at once.

RT-FU-A-STOPPED-REQUESTS-TURN-STAYS-RUNNING-AFTER-STOP (review w1118a.59). Seen live 2026-11-20
(w1118a-hrun, Eternia on Linux, account C): Base's request to Neko Mission Lead was stopped, the
request settled ``cancelled`` and its child was gone, but Neko's turn for it
(``chat_turn:agent-dispatch-<id>``) stayed ``running`` in Running work until the serve restarted.
The supervisor now ends that turn when it settles the killed child's request
(``persona_chat_continuity.lease.end_dispatch_turn``): stopped for a Stop, interrupted for a
budget kill, and its transcript closed so the next message is a turn of its own.
"""

from __future__ import annotations

import time

import pytest

from agent_runtime import dispatch_store
from agent_runtime.chat_turn import dispatch_turn_request_id
from agent_runtime.dispatch_store import mint_dispatch_id, record_dispatch
from agent_runtime.mission_chat_turns import mission_chat_turn_record, transition_mission_chat_turn
from agent_runtime.persona_chat_continuity.lease import persona_chat_root_lease
from tools.agent_chat_dispatch import local as local_mod

SENDER_ROOT = "persona_chat_personainst_base_aaaaaaaaaaaa"
TARGET_ROOT = "persona_chat_personainst_neko_bbbbbbbbbbbb"


@pytest.fixture
def store_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    return home


def _request_with_turn_in_flight() -> tuple[str, str]:
    """A request whose child had started the target's turn (journal ``executing``) when it was killed."""

    dispatch_id = mint_dispatch_id()
    record_dispatch(dispatch_id=dispatch_id, sender_session_id=SENDER_ROOT, target_persona="neko", ask="x")
    message = dispatch_turn_request_id(dispatch_id)
    for state in ("pending", "executing"):
        transition_mission_chat_turn(session_id=TARGET_ROOT, client_message_id=message, turn_id=message,
                                     state=state, metadata={"root_chat_session_id": TARGET_ROOT})
    return dispatch_id, message


def _running_work_turn(message: str) -> dict:
    from agent_runtime.running_work.lanes_chat import _collect_chat_turns

    rows, _source = _collect_chat_turns(now=time.time(), accountant=None)
    return next(row for row in rows if row.get("work_id") == f"chat_turn:{message}")


def test_a_stopped_requests_turn_leaves_running_work_as_stopped(store_home):
    """KILLING MUTATION (run 2026-11-20): ``_record_local_outcome`` without the
    ``_end_killed_childs_turn(dispatch_id, stopped=True)`` call -> the turn row stays ``running``, red."""

    dispatch_id, message = _request_with_turn_in_flight()
    assert _running_work_turn(message)["status"] == "running"

    local_mod._record_local_outcome(dispatch_id, 600.0, -9, "", None, "", cancel_reason="operator_cancel")

    assert dispatch_store.get_dispatch(dispatch_id)["state"] == dispatch_store.STATE_CANCELLED
    record = mission_chat_turn_record(session_id=TARGET_ROOT, client_message_id=message)
    assert record["state"] == "interrupted" and record.get("stopped") is True
    row = _running_work_turn(message)
    assert (row["status"], row["outcome"], row["cancellable"]) == ("error", "stopped", False)


def test_a_turn_killed_past_its_budget_is_interrupted_not_stopped(store_home):
    """KILLING MUTATION (run 2026-11-20): the budget branch without its ``_end_killed_childs_turn``
    call -> the record stays ``executing``, red."""

    dispatch_id, message = _request_with_turn_in_flight()

    local_mod._record_local_outcome(dispatch_id, 600.0, -9, "budget_exceeded", None, "", cancel_reason=None)

    record = mission_chat_turn_record(session_id=TARGET_ROOT, client_message_id=message)
    assert record["state"] == "interrupted" and not record.get("stopped")


def test_a_turn_whose_chat_lease_is_held_is_left_alone(store_home):
    """A held lease is a live turn: the end never settles what is still running.

    KILLING MUTATION (run 2026-11-20): ``end_dispatch_turn`` mutating without taking the lease -> the
    record is flipped under a live holder, red."""

    from agent_runtime.persona_chat_continuity.lease import end_dispatch_turn

    dispatch_id, message = _request_with_turn_in_flight()
    with persona_chat_root_lease(TARGET_ROOT, observer_kind="cli"):
        assert end_dispatch_turn(dispatch_id, stopped=True) == []
    assert mission_chat_turn_record(session_id=TARGET_ROOT, client_message_id=message)["state"] == "executing"


def test_a_stopped_turns_unanswered_tool_call_is_closed_as_stopped(store_home):
    """The transcript is closed like the boot sweep's, with a result that says the request was stopped.

    KILLING MUTATION (run 2026-11-20): ``end_dispatch_turn`` passing no ``tool_result`` -> the result
    reads "the runtime restarted", red."""

    from agent_runtime.chat_session_scope import SessionDbAccess, open_chat_session_db, resolve_chat_session_scope
    from agent_runtime.persona_chat_continuity.lease import CUT_OFF_STOPPED_TOOL_RESULT
    from agent_runtime.persona_chat_session import _persona_chat_native_tip

    def _db():
        return open_chat_session_db(resolve_chat_session_scope(session_id=TARGET_ROOT), access=SessionDbAccess.WRITE)

    db = _db()
    try:
        db.ensure_session(TARGET_ROOT, source="persona_chat")
        db.append_message(TARGET_ROOT, "user", "please run it")
        call = {"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}
        db.append_message(TARGET_ROOT, "assistant", "", tool_calls=[call])
    finally:
        db.close()
    dispatch_id, _message = _request_with_turn_in_flight()

    local_mod._record_local_outcome(dispatch_id, 600.0, -9, "", None, "", cancel_reason="operator_cancel")

    db = _db()
    try:
        rows = db.get_messages(_persona_chat_native_tip(db, TARGET_ROOT), limit=4, latest=True)
    finally:
        db.close()
    tool_rows = [row for row in rows if row.get("role") == "tool"]
    assert [(row["tool_call_id"], row["content"]) for row in tool_rows] == [("call_1", CUT_OFF_STOPPED_TOOL_RESULT)]
