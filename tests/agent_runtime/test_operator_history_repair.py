"""Regression checks for review findings: guards, admission and crash evidence."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import threading
from dataclasses import replace
import pytest
from hermes_state import SessionDB
from hermes_state_errors import SessionActiveWriteGuardError, SessionTurnLeaseLostError, SessionCompressionInProgressError
from tests.agent_runtime.test_operator_history_controls import setup
from tests.agent_runtime.test_operator_conversation_attachment import call


@pytest.mark.parametrize("action", ["branch", "rewind"])
@pytest.mark.parametrize("error", [SessionActiveWriteGuardError, SessionTurnLeaseLostError, SessionCompressionInProgressError])
def test_native_write_guards_are_definite_refusals(tmp_path, monkeypatch, action, error):
    target, before, _, request = setup(tmp_path, monkeypatch, action)
    method = "branch_before_message" if action == "branch" else "rewind_user_turn"
    def refuse(*a, **kw):
        raise error("active writer")
    monkeypatch.setattr(SessionDB, method, refuse)
    result = call("history.apply", request)
    assert result["error"]["code"] == 4090
    assert result["error"]["data"]["reason"] == "conversation_busy"
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert db.get_messages(target["session_id"]) == before


def test_in_place_rewind_writer_race_has_no_alternation_or_missing_row_escape(tmp_path, monkeypatch):
    target, before, _, request = setup(tmp_path, monkeypatch, "rewind")
    original = SessionDB.rewind_to_message
    def changed_content(db, session_id, *a, **kw):
        # Same count, roles and target ID. Only the revision pin can reject it.
        db._conn.execute("UPDATE messages SET content = ? WHERE id = ?", ("edited concurrently", before[2]["id"]))
        db._conn.commit()
        return original(db, session_id, *a, **kw)
    monkeypatch.setattr(SessionDB, "rewind_to_message", changed_content)
    result = call("history.apply", request)
    assert result["error"]["data"]["reason"] == "history_changed", result
    with closing(SessionDB(db_path=tmp_path / "home" / "state.db")) as db:
        assert len(db.get_messages(target["session_id"])) == len(before)
        assert db.get_session(target["session_id"])["rewind_count"] == 0


def test_two_short_admissions_wait_instead_of_false_history_conflict(tmp_path, monkeypatch):
    from agent_runtime import paths
    from agent_runtime.chat_turn_reservations import reserve_chat_turn
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    entered, release = threading.Event(), threading.Event()
    def first():
        with reserve_chat_turn(turn_request_id="admission-one", verb="message", session_scope="chat"):
            entered.set()
            assert release.wait(1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(first)
        assert entered.wait(1)
        def second():
            with reserve_chat_turn(turn_request_id="admission-two", verb="message", session_scope="chat") as reservation:
                return reservation.record.session_scope
        b = pool.submit(second)
        try:
            with pytest.raises(TimeoutError):
                b.result(timeout=.1)
        finally:
            release.set()
        a.result(timeout=3)
        assert b.result(timeout=3) == "chat"


def test_dead_accept_owner_settles_once_and_live_owner_remains(tmp_path, monkeypatch):
    from agent_runtime.chat_turn_reservations import reserve_chat_turn, repair_orphaned_chat_receipts, read_chat_turn_receipt, _write
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    for key in ("dead-turn", "live-turn"):
        with reserve_chat_turn(turn_request_id=key, verb="message", session_scope="chat") as reservation:
            record = reservation.mark_accepted({}, request_id=key)
        if key == "dead-turn":
            _write(replace(record, owner_started=record.owner_started - 1000))
    assert repair_orphaned_chat_receipts() == ["chat"]
    assert read_chat_turn_receipt("dead-turn").exit_code == 130
    assert read_chat_turn_receipt("live-turn").state == "accepted"
    assert repair_orphaned_chat_receipts() == []


def test_fence_before_command_crash_is_provably_empty(tmp_path, monkeypatch):
    from agent_runtime.history_recovery import fence_history_operation, pending_history_operation
    target, _, _, _ = setup(tmp_path, monkeypatch)
    fence_history_operation(target["session_id"], "crash-before-command", action="undo")
    result = call("history.pending", target)
    assert result["result"]["pending"] is None, result
    assert pending_history_operation(target["session_id"]) is None
