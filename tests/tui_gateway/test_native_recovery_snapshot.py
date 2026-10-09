"""Recovery is a native observation, not prompt replay or another state owner."""
from contextlib import nullcontext
import json
import threading

import pytest

from hermes_state import SessionDB
from tui_gateway import event_replay, server, server_requests, session_execution, session_recovery
from tui_gateway.contracts.recovery import RecoveryHistoryPage, RecoverySnapshot


@pytest.fixture
def owner(tmp_path, monkeypatch):
    db = SessionDB(tmp_path / "state.db")
    db.create_session("stored", source="eternia_intelligence")
    session = server._deferred_session_record(
        "stored", cols=80, cwd=str(tmp_path), history=[], lease=None, lazy=True)
    monkeypatch.setitem(server._sessions, "live", session)
    monkeypatch.setattr(server, "_session_db", lambda _: nullcontext(db))
    event_replay.reset_replay_state()
    yield session, db
    server_requests.reset_for_tests()
    event_replay.reset_replay_state()
    db.close()


def test_checkpoint_returns_detached_json_events_from_frozen_replay(owner):
    frame = {"method": "event", "params": {
        "session_id": "live", "type": "message.delta", "payload": {"text": "original"}}}
    event_replay._stamp_event(frame)
    frame["params"]["payload"]["text"] = "caller mutation"
    page = event_replay.checkpoint("live", 0)
    assert json.loads(json.dumps(page))["events"][0]["payload"]["text"] == "original"
    assert page["events"][0]["seq"] == page["latest_seq"] == 1
    page["events"][0]["payload"]["text"] = "reader mutation"
    assert event_replay.checkpoint("live", 0)["events"][0]["payload"]["text"] == "original"


def test_snapshot_restores_the_exact_live_question_and_execution(owner):
    session, db = owner
    session_execution.admit(session, "execution")
    row = db.append_message("stored", "user", "hello")
    session["_submit_user_row"] = {"_row_id": row}
    session_execution.submitted(session)
    server._start_inflight_turn(session, "hello")
    server._append_inflight_delta(session, "part one")
    request = server_requests.ServerRequest("live", "clarify", {"question": "Continue?"})
    with server_requests._lock:
        server_requests._open[request.id] = request
    result = session_recovery.recover(server, "live", session, "execution")
    RecoverySnapshot.model_validate(result)
    assert result["execution"]["user_row_id"] == row
    assert result["execution"]["id"] == "execution"
    assert result["open_requests"][0]["id"] == request.id
    assert result["inflight_position"] == {"execution_id": "execution", "user": 5, "assistant": 8,
        "reasoning": 0, "revision": 0, "segment_ends": []}
    server_requests.resolve_response({"id": request.id, "result": {"answer": "yes"}}, session_id="live")
    again = session_recovery.recover(server, "live", session, "execution")
    assert not again.get("open_requests")


def test_live_prefix_is_bounded_exact_and_restarts_when_execution_changes(owner):
    session, _ = owner
    session_execution.admit(session, "execution")
    text = "🌍中文" * 70000
    server._start_inflight_turn(session, "hello")
    server._append_inflight_delta(session, text)
    snapshot = session_recovery.recover(server, "live", session, "execution")
    assert len(json.dumps(snapshot)) < 16384
    server._append_inflight_delta(session, "newer")
    offset, chunks = 0, []
    while True:
        page = session_recovery.inflight_page(server, session, {
            "execution_id": "execution", "field": "assistant", "through": len(text), "offset": offset})
        assert len(json.dumps(page)) < 256 * 1024
        chunks.append(page["text"])
        offset = page["offset"]
        if not page["more"]:
            break
    assert "".join(chunks) == text
    server._clear_inflight_turn(session)
    assert session_recovery.inflight_page(server, session, {
        "execution_id": "execution", "field": "assistant", "through": len(text)})["reset"]


def test_checkpoint_cannot_split_partial_text_from_its_event_position(owner):
    session, _ = owner
    session_execution.admit(session, "execution")
    server._start_inflight_turn(session, "hello")
    entered, finish, recovered = threading.Event(), threading.Event(), threading.Event()
    snapshots = []

    def publish():
        with session_execution.checkpoint_guard(session):
            server._append_inflight_delta(session, "delta")
            entered.set()
            assert finish.wait(2)
            event_replay._stamp_event({"method": "event", "params": {
                "session_id": "live", "type": "message.delta", "payload": {"text": "delta"}}})

    thread = threading.Thread(target=publish)
    def recover():
        snapshots.append(session_recovery.recover(server, "live", session, "execution"))
        recovered.set()
    reader = threading.Thread(target=recover)
    thread.start()
    assert entered.wait(2)
    reader.start()
    try:
        assert not recovered.wait(.05)
    finally:
        finish.set()
        thread.join(2)
        reader.join(2)
    assert recovered.is_set()
    snapshot = snapshots[0]
    assert snapshot["inflight_position"]["assistant"] == 5
    assert snapshot["latest_seq"] == 1


def test_history_pages_reconstruct_large_rows_and_exclude_future_output(owner):
    session, db = owner
    db.append_message("stored", "user", "question")
    text = "🌍中文" * 100000
    db.append_message("stored", "assistant", text)
    position = session_recovery.recover(server, "live", session)["history"]
    db.append_message("stored", "user", "future")
    rows = read_history(session, position)
    assert [row["text"] for row in rows] == ["question", text]
    session["history_version"] += 1
    assert session_recovery.history_page(server, session, {"position": position})["reset"]


def read_history(session, position):
    index, offset, rows = 0, 0, {}
    while True:
        page = session_recovery.history_page(server, session, {
            "position": position, "message_index": index, "offset": offset})
        RecoveryHistoryPage.model_validate(page)
        assert len(json.dumps(page)) < 1024 * 1024
        for row in page["chunks"]:
            prior = rows.get(row["index"], "")
            assert len(prior) == row["offset"]
            rows[row["index"]] = prior + row["data"]
        index, offset = page["message_index"], page["offset"]
        if not page["more"]:
            break
    return [json.loads(text) for text in rows.values()]


def test_recovery_uses_native_compacted_lineage_and_display_visibility(owner):
    session, db = owner
    db.append_message("stored", "user", "original question")
    db.append_message("stored", "assistant", "original answer")
    db.archive_and_compact("stored", [{"role": "user", "content": "model scaffold", "display_kind": "hidden"}])
    # A rotation ends the parent ``compression``: since the 2026-09-29 upstream merge the display read
    # walks only that VERIFIED lineage (``SessionDB._resume_lineage_ids``), never a bare parent pointer.
    db.end_session("stored", "compression")
    db.create_session("tip", source="eternia_intelligence", parent_session_id="stored")
    db.append_message("tip", "user", "follow-up")
    db.append_message("tip", "assistant", "new answer")
    session["session_key"] = "tip"
    position = session_recovery.recover(server, "live", session)["history"]
    assert [row["text"] for row in read_history(session, position)] == [
        "original question", "original answer", "follow-up", "new answer"]


def test_checkpoint_preserves_segment_boundaries_and_invalidates_rewritten_prefix(owner):
    session, _ = owner
    session_execution.admit(session, "execution")
    server._start_inflight_turn(session, "hello")
    server._append_inflight_delta(session, "draft")
    stale = session_recovery.recover(server, "live", session)["inflight_position"]

    def emit(kind, text):
        session_execution.stamp(session, {"method": "event", "params": {
            "type": kind, "payload": {"text": text}}})

    emit("reasoning.delta", "reason")
    emit("message.interim", "Polished🌍")
    server._append_inflight_delta(session, "final prefix")
    emit("reasoning.available", "next thought")
    position = session_recovery.recover(server, "live", session)["inflight_position"]
    assert position["segment_ends"] == [{"assistant": 9, "reasoning": 6}]
    assert position["assistant"] == len("Polished🌍final prefix")
    assert position["reasoning"] == len("reasonnext thought")
    assert session_recovery.inflight_page(server, session, {
        "execution_id": "execution", "field": "assistant", "through": stale["assistant"],
        "revision": stale["revision"]})["reset"]
    current = session_recovery.inflight_page(server, session, {
        "execution_id": "execution", "field": "assistant", "through": position["assistant"],
        "revision": position["revision"]})
    assert current["text"] == "Polished🌍final prefix"


def test_native_execution_link_survives_compaction_copy(owner):
    session, db = owner
    session_execution.admit(session, "execution")
    server._persist_submit_user_row(session, "question", None)
    session_execution.submitted(session)
    original = session_execution.snapshot(session, "execution")["user_row_id"]
    history = db.get_messages_as_conversation("stored", include_row_ids=True)
    db.archive_and_compact("stored", history)
    position = session_recovery.recover(server, "live", session)["history"]
    rows = read_history(session, position)
    assert len(rows) == 1
    assert rows[0]["row_id"] != original
    assert rows[0]["display_metadata"]["execution_id"] == "execution"


def test_queued_prompt_does_not_inherit_the_active_execution(owner):
    session, db = owner
    session_execution.admit(session, "active")
    server._persist_submit_user_row(session, "active input", None)
    queued = server._write_submit_user_row(session, "queued input", None)
    assert queued and "display_metadata" not in queued
    rows = db.get_messages_as_conversation("stored")
    assert rows[0]["display_metadata"]["execution_id"] == "active"
    assert "display_metadata" not in rows[1]


def test_explicit_branch_recovery_never_reads_its_parent(owner):
    session, db = owner
    db.append_message("stored", "user", "not in this branch")
    db.create_session("branch", source="eternia_intelligence", parent_session_id="stored",
        model_config={"_branched_from": "stored"})
    db.append_message("branch", "user", "branch input")
    session["session_key"] = "branch"
    position = session_recovery.recover(server, "live", session)["history"]
    assert [row["text"] for row in read_history(session, position)] == ["branch input"]
