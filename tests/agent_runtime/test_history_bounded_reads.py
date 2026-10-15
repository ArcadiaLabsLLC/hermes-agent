"""Differential proof for abandoned IDs and the public latest-eight read."""
from agent_runtime.mission_chat_turns import reads
from agent_runtime.prompt_observability.safe_views import _chat_history_context
from hermes_state import SessionDB


def test_abandoned_ids_preserve_projection_validation_and_suffixes(monkeypatch):
    raw = {
        "a": {"state": "abandoned", "elements": [{"text": "large"}] * 300},
        "a:b": {"state": "abandoned"},
        ":": {"state": "abandoned"},
        "---": {"state": "abandoned", "turn_id": "valid"},
        "---bad": {"state": "unknown"},
        "": {"state": "abandoned"},
        "broken": [],
    }
    monkeypatch.setattr(reads, "_read_session", lambda _: raw)
    expected = frozenset(row["client_message_id"] for row in
        reads.mission_chat_turn_records(session_id="chat") if row["state"] == "abandoned")
    actual = reads.abandoned_mission_chat_message_ids(session_id="chat")
    assert actual == expected
    for message_id in ("a", "a:b", "a:b:c", "ab", "---:suffix", "", "other"):
        assert reads.is_abandoned_mission_chat_message(message_id, actual) == any(
            message_id == key or message_id.startswith(key + ":") for key in expected)
    monkeypatch.setattr(reads, "_safe_record", lambda *a, **k: (_ for _ in ()).throw(AssertionError("full projection")))
    assert reads.abandoned_mission_chat_message_ids(session_id="chat") == expected


def test_prompt_history_limits_materialization_before_empty_filter(tmp_path, monkeypatch):
    db = SessionDB(db_path=tmp_path / "state.db")
    try:
        db.create_session("chat", source="test")
        for index in range(24):
            db.append_message("chat", role="user", content="" if index == 22 else f"row-{index}")
        original = db.get_messages
        expected = original("chat")[-8:]
        seen = []
        def limited(session_id, **kwargs):
            assert kwargs == {"limit": 8, "latest": True}
            result = original(session_id, **kwargs)
            seen.extend(result)
            return result
        monkeypatch.setattr(db, "get_messages", limited)
        rows = _chat_history_context(session_db=db, session_id="chat")
        assert len(seen) == 8
        assert [row["text"] for row in rows] == [row["content"] for row in expected if row["content"]]
        assert [row["timestamp"] for row in rows] == [str(row.get("created_at") or row.get("timestamp") or "") for row in expected if row["content"]]
    finally:
        db.close()
