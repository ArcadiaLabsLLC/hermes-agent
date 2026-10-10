"""Full content uses the real RPC and the same scoped SQLite transcript as history."""
from contextlib import closing
import json

from agent_runtime import serve_rpc
from agent_runtime.serve_rpc.protocol import ERR_CONFLICT
from agent_runtime.persona_chat_history.content import CONTENT_WINDOW_CHARS
from hermes_state import SessionDB
from tests.agent_runtime.test_operator_conversation_attachment import fixture, call


def _read(params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "content",
        "method": "runtime.persona.chat.content", "params": params})


def test_history_preview_and_all_windows_preserve_full_multiline_unicode(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Test")
    text = "  local value = 1\n\treturn value\n🌍\n\n" * 1800 + "TAIL\n"
    with closing(SessionDB(tmp_path / "home" / "state.db")) as db:
        db.append_message(target["session_id"], "assistant", text)
    row = call("read", target)["result"]["messages"][-1]
    assert row["text_truncated"] is True
    assert row["text_total_chars"] == len(text)
    assert text.startswith(row["text"]) and len(row["text"]) <= 20_000
    reference = row["content_ref"]
    offset = 0
    chunks = []
    while True:
        answer = _read({**target, "content_ref": reference, "offset": offset})["result"]
        assert answer["offset"] == offset
        assert len(answer["text"]) <= CONTENT_WINDOW_CHARS
        assert answer["total_chars"] == len(text)
        chunks.append(answer["text"])
        if answer["next_offset"] is None:
            break
        reference, offset = answer["content_ref"], answer["next_offset"]
    assert "".join(chunks) == text
    refused = _read({**target, "content_ref": {**reference, "revision": "changed"}, "offset": 1})
    assert refused["error"]["data"]["reason"] == "content_changed"
    assert refused["error"]["code"] == ERR_CONFLICT


def test_native_tool_read_redacts_and_is_scoped_to_the_requested_session(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Test")
    with closing(SessionDB(tmp_path / "home" / "state.db")) as db:
        db.append_message(target["session_id"], "assistant", None, tool_calls=[{
            "id": "real-call", "type": "function", "function": {
                "name": "inspect", "arguments": json.dumps({"api_key": "fixture-private", "source": "x" * 30000})}}])
        db.append_message(target["session_id"], "tool", "full result " * 3000,
                          tool_call_id="real-call", tool_name="inspect")
        db.patch_session_model_config(target["session_id"], {"client_scope": "a" * 64})
    for kind in ("tool_input", "tool_result"):
        params = {**target, "client_scope": "a" * 64, "content_ref": {"kind": kind, "id": "real-call"}}
        result = _read(params)["result"]
        assert result["next_offset"] is not None
        assert "fixture-private" not in result["text"]
        assert _read({**params, "client_scope": "b" * 64})["error"]["data"]["reason"] == "conversation_owner_changed"
        assert _read({**params, "content_ref": {"kind": kind, "id": "foreign-call"}})["error"]["data"]["reason"] == "content_unavailable"


def test_invalid_windows_and_unreadable_references_are_typed_refusals(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Test")
    for patch in ({"content_ref": {"kind": [], "id": "id"}}, {"offset": -1}, {"offset": True}):
        params = {**target, "content_ref": {"kind": "message", "id": "missing"}, **patch}
        assert _read(params)["error"]["data"]["reason"] == "invalid_content_request"


def test_archived_display_history_is_readable_but_hidden_rows_are_not(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Test")
    body = "Original reply\n" * 2000
    with closing(SessionDB(tmp_path / "home" / "state.db")) as db:
        db.append_message(target["session_id"], "assistant", body)
        db.archive_and_compact(target["session_id"], [
            {"role": "user", "content": "internal handoff", "display_kind": "hidden"}])
        db.append_message(target["session_id"], "tool", "hidden result",
                          tool_call_id="hidden", display_kind="hidden")
    rows = call("read", target)["result"]["messages"]
    row = next(row for row in rows if row.get("text_truncated"))
    result = _read({**target, "content_ref": row["content_ref"]})["result"]
    assert result["text"] == body[:CONTENT_WINDOW_CHARS]
    assert all("internal handoff" not in row["text"] for row in rows)
    refused = _read({**target, "content_ref": {"kind": "tool_result", "id": "hidden"}})
    assert refused["error"]["data"]["reason"] == "content_unavailable"


def test_a_carried_message_keeps_its_reference_across_compaction(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Test")
    body = "Original reply\n" * 2000
    with closing(SessionDB(tmp_path / "home" / "state.db")) as db:
        db.append_message(target["session_id"], "assistant", body)
        original = db.get_messages(target["session_id"])[-1]
    reference = call("read", target)["result"]["messages"][-1]["content_ref"]
    assert reference["id"] == original["message_uid"]
    with closing(SessionDB(tmp_path / "home" / "state.db")) as db:
        db.archive_and_compact(target["session_id"], [original], tail_count=1)
    result = _read({**target, "content_ref": {**reference, "unused": "x" * 30000}})["result"]
    assert result["text"] == body[:CONTENT_WINDOW_CHARS]
    assert result["content_ref"] == reference


def test_database_read_failure_is_unavailable_not_an_empty_result(tmp_path, monkeypatch):
    target = fixture(tmp_path / "home", monkeypatch, "Test")
    def fail(*args, **kwargs):
        raise OSError("fixture-secret must not appear in the refusal")
    monkeypatch.setattr(SessionDB, "get_messages", fail)
    answer = _read({**target, "content_ref": {"kind": "tool_result", "id": "call"}})
    assert answer["error"]["data"]["reason"] == "content_unavailable"
    assert "fixture-secret" not in json.dumps(answer)
