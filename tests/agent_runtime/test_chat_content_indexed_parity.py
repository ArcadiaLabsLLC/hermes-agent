"""The indexed tool-content read answers exactly what the full display read answers (lineage-stamp plan S2)."""
from __future__ import annotations

import json

import pytest

from agent_runtime.persona_chat_history import content
from hermes_state import SessionDB

IDS = ("call-a", "call-h", "call-b", "call-dup", "call-r", "missing", "call with space")


def _calls(call_id, secret="fixture-private"):
    return [{"id": call_id, "type": "function", "function": {
        "name": "inspect", "arguments": json.dumps({"api_key": secret, "path": call_id})}}]


def _lineage(db):
    """root (compaction-archived generation + hidden + rewound rows) --compression--> tip."""
    db.create_session("root", source="tui")
    db.append_message("root", "user", "q1")
    first = db.append_message("root", "assistant", None, tool_calls=_calls("call-a"))
    second = db.append_message("root", "tool", "result a " * 50, tool_call_id="call-a", tool_name="inspect")
    db.append_message("root", "assistant", None, tool_calls=_calls("call-h"), display_kind="hidden")
    db.append_message("root", "tool", "hidden result", tool_call_id="call-h", tool_name="inspect",
                      display_kind="hidden")
    db.append_message("root", "assistant", None, tool_calls=_calls("call-r"))
    rewound = db.append_message("root", "tool", "rewound result", tool_call_id="call-r", tool_name="inspect")

    def archive(conn):
        # A compaction generation: the protected tail is cloned live, the originals archived.
        db._clone_message_rows(conn, [first, second])
        conn.execute("UPDATE messages SET active = 0, compacted = 1 WHERE id IN (?, ?)", (first, second))
        conn.execute("UPDATE messages SET active = 0, compacted = 0 WHERE id = ?", (rewound,))

    db._execute_write(archive)
    db.end_session("root", "compression")
    db.create_session("tip", source="tui", parent_session_id="root")
    db.append_message("tip", "assistant", None, tool_calls=_calls("call-b") + _calls("call-dup"))
    db.append_message("tip", "tool", "result b", tool_call_id="call-b", tool_name="inspect")
    db.append_message("tip", "tool", "dup one", tool_call_id="call-dup", tool_name="inspect")
    db.append_message("tip", "tool", "dup two", tool_call_id="call-dup", tool_name="inspect")


def _outcome(db, session_id, content_id, field):
    try:
        return "text", content._tool_text(db, session_id, content_id, field=field)
    except content.ContentReadRefused as refused:
        return "refused", str(refused)


@pytest.mark.parametrize("field", ["tool_input", "tool_result"])
def test_indexed_and_full_reads_agree_for_every_tool_id(tmp_path, monkeypatch, field):
    db = SessionDB(tmp_path / "state.db")
    _lineage(db)
    indexed = {(sid, cid): _outcome(db, sid, cid, field) for sid in ("root", "tip") for cid in IDS}
    monkeypatch.setattr("agent_runtime.session_lineage_stamp.lineage_tool_rows", lambda *a, **k: None)
    full = {(sid, cid): _outcome(db, sid, cid, field) for sid in ("root", "tip") for cid in IDS}
    db.close()
    assert indexed == full
    # Positive controls: the fixture really exercises a found row, a lineage ancestor and redaction.
    assert full[("tip", "call-a")][0] == "text" and full[("tip", "call-b")][0] == "text"
    assert all(full[("tip", cid)][0] == "refused" for cid in ("call-h", "missing"))
    # Only the tool RESULT of call-r was rewound; its call stays displayed.
    assert full[("tip", "call-r")][0] == ("refused" if field == "tool_result" else "text")
    assert "fixture-private" not in full[("tip", "call-a")][1]


def test_the_indexed_read_is_actually_taken(tmp_path, monkeypatch):
    """Without this, parity could hold because both sides took the full read."""
    db = SessionDB(tmp_path / "state.db")
    _lineage(db)
    monkeypatch.setattr("agent_runtime.persona_chat_history.curation._read_raw_messages",
                        lambda *a, **k: pytest.fail("full read taken for a plain tool id"))
    assert _outcome(db, "tip", "call-a", "tool_result")[0] == "text"
    assert _outcome(db, "tip", "call-a", "tool_input")[0] == "text"
    db.close()
