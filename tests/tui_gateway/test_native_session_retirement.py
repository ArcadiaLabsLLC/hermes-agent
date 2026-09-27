"""Retirement uses native lifecycle eligibility, independent of replay-cache pressure."""
from contextlib import nullcontext
import threading
from unittest.mock import Mock

import pytest

from hermes_state import SessionDB
from tui_gateway import event_replay, server, server_requests, session_execution, session_retirement


@pytest.fixture
def owner(tmp_path, monkeypatch):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("stored", source="eternia_intelligence")
    db.append_message("stored", "user", "preserve me")
    session = server._deferred_session_record(
        "stored", cols=80, cwd=str(tmp_path), history=[], lease=None, lazy=True)
    monkeypatch.setitem(server._sessions, "live", session)
    monkeypatch.setattr(server, "_session_db", lambda _: nullcontext(db))
    monkeypatch.setattr(server, "_teardown_session", Mock())
    monkeypatch.setattr(server, "_teardown_popped_session", Mock(wraps=server._teardown_popped_session))
    event_replay.reset_replay_state()
    session_execution.admit(session, "execution")
    session_execution.stamp(session, {"method": "event", "params": {
        "type": "message.complete", "payload": {"status": "complete"}}})
    yield session, db
    server_requests.reset_for_tests()
    event_replay.reset_replay_state()
    db.close()


def retire():
    return session_retirement.retire(server, "live", server._sessions["live"], "execution")


@pytest.mark.parametrize("field,value", [
    ("running", True), ("queued_prompt", {"text": "later"}),
    ("queued_prompts", [{"text": "later"}]), ("_compute_host_turn_id", "in-flight"),
    ("_compute_host_open_request", {"id": "question"}),
    ("_run_thread", Mock(is_alive=lambda: True)),
    ("_agent_build_thread", Mock(is_alive=lambda: True)),
])
def test_protected_work_survives_retirement(owner, field, value):
    session, _ = owner
    session[field] = value
    assert retire() == {"status": "protected"}
    assert server._sessions["live"] is session
    server._teardown_popped_session.assert_not_called()


def test_pending_native_question_prevents_retirement(owner):
    request = server_requests.ServerRequest("live", "clarify", {"question": "Continue?"})
    with server_requests._lock:
        server_requests._open[request.id] = request
    assert retire() == {"status": "protected"}


def test_uncertain_and_replaced_executions_are_not_retired(owner):
    session, _ = owner
    session_execution.admit(session, "new")
    assert retire() == {"status": "protected"}
    session.pop("native_execution")
    assert session_retirement.retire(server, "live", session, "new") == {"status": "protected"}
    assert session_retirement.retire(server, "live", session, None) == {"status": "protected"}


def test_generic_native_reapers_also_protect_uncertain_and_queued_work(owner):
    session, _ = owner
    session_execution.admit(session, "uncertain")
    session_execution.uncertain(session, "uncertain")
    assert not server._session_is_lru_evictable("live", session, require_dead_transport=False)
    session_execution.rejected(session)
    session["queued_prompt"] = {"text": "later"}
    assert not server._session_is_lru_evictable("live", session, require_dead_transport=False)


def test_retirement_retry_acknowledges_an_already_removed_session(owner):
    assert retire() == {"status": "retired"}
    assert server._methods["session.retire"]("retry", {
        "session_id": "live", "execution_id": "execution"})["result"] == {"status": "retired"}


def test_ordinary_native_teardown_releases_replay_identity_too(owner):
    event_replay._stamp_event({"method": "event", "params": {
        "session_id": "live", "type": "message.delta", "payload": {"text": "old"}}})
    server._teardown_popped_session(server._pop_session_by_id("live"))
    assert "live" not in event_replay._replay_next_seq
    assert not event_replay.events_since("live", 0)


def test_retirement_releases_replay_not_transcript_or_execution_evidence(owner):
    session, db = owner
    event_replay._stamp_event({"method": "event", "params": {
        "session_id": "live", "type": "message.delta", "payload": {"text": "word"}}})
    assert retire() == {"status": "retired"}
    assert "live" not in server._sessions
    assert "live" not in event_replay._replay_next_seq
    assert db.get_messages("stored")[0]["content"] == "preserve me"
    restored = {"session_key": "stored", "history_lock": threading.RLock()}
    assert session_execution.snapshot(restored, "execution")["status"] == "complete"
    with server._session_turn_admission(session) as allowed:
        assert not allowed
    server._teardown_popped_session.assert_called_once_with(session, end_reason="idle_timeout")


def test_native_eligibility_is_rechecked_after_child_retirement(owner, monkeypatch):
    session, _ = owner
    session["_compute_host_active"] = True
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda _: True)

    def observe(*args):
        session["queued_prompt"] = {"text": "arrived meanwhile"}
        return {"result": {"status": "retired"}}

    monkeypatch.setattr(server, "_get_compute_host_supervisor", lambda: Mock(observe=observe))
    assert retire() == {"status": "protected"}
    server._teardown_popped_session.assert_not_called()
