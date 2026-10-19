"""The ``messaging_turn`` running-work lane (p10-messaging M4): a queued platform message is a row until it settles.

Killing mutation: drop the lane's row from ``running_work.surface._COLLECTORS`` →
``test_a_queued_message_is_a_messaging_turn_row`` red.
"""

from __future__ import annotations

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime.running_work import KIND_MESSAGING_TURN, RUNNING_WORK_SOURCES, build_running_work, split_work_id

ROOT = "persona_chat_root_rw_msg"
ORIGIN = {"owner": None, "gateway": False, "kind": "messaging",
          "messaging": {"platform": "telegram", "chat_id": "-1001", "thread_id": "9", "user_id": "42",
                        "message_id": "7", "update_id": 1000}}


def _rows() -> list[dict]:
    return [row for row in build_running_work()["rows"] if row["kind"] == KIND_MESSAGING_TURN]


def test_the_kind_is_on_the_wire_and_reports_a_source():
    assert KIND_MESSAGING_TURN == "messaging_turn" and KIND_MESSAGING_TURN in RUNNING_WORK_SOURCES
    assert build_running_work()["sources"][KIND_MESSAGING_TURN]["status"] == "ok"


def test_a_queued_message_is_a_messaging_turn_row():
    send_queue.enqueue(ROOT, "msg-telegram-1000", {send_queue.ORIGIN_ARG: ORIGIN, "message": "hi"})
    [row] = _rows()
    assert split_work_id(row["work_id"]) == ("messaging_turn", f"{ROOT}/msg-telegram-1000")
    assert row["platform"] == "telegram" and row["chat_id"] == "-1001" and row["thread_id"] == "9"
    assert row["phase"] == "queued" and row["status"] == "running" and row["label"] == "telegram: message"
    assert row["owner"]["session_id"] == ROOT and "hi" not in str(row)
    send_queue.mark(ROOT, "msg-telegram-1000", state=send_queue.STATE_RUNNING)
    assert _rows()[0]["phase"] == "running"
    send_queue.remove(ROOT, "msg-telegram-1000")
    assert _rows() == []


def test_an_operator_send_or_a_scheduled_fire_is_not_a_messaging_turn():
    send_queue.enqueue(ROOT, "operator-1", {send_queue.ORIGIN_ARG: {"owner": "operator"}, "message": "hi"})
    send_queue.enqueue(ROOT, "schedule-f1", {send_queue.ORIGIN_ARG: {"schedule": "standup"}, "message": "hi"})
    assert _rows() == []
