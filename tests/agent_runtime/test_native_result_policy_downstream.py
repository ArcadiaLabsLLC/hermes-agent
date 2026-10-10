"""Upstream result policy survives the native SQLite flush and cold replay.

No provider or live profile is needed: use the production persistence mixin,
SessionDB, spill functions and native history projection with hermetic homes.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from agent.session_persistence import SessionPersistenceMixin
from agent_runtime import native_persistence
from agent_runtime.persona_chat_continuity import (
    BOUND_ACTION_TRUNCATED, BOUND_PART_CONTENT, ContentBoundNote,
    native_wire_row, safe_native_history,
)
from hermes_state import SessionDB
from tools.budget_config import BudgetConfig
from tools.tool_result_storage import (
    enforce_turn_budget, extract_persisted_path, maybe_persist_tool_result,
)


class _NativeAgent(SessionPersistenceMixin):
    def __init__(self, db):
        self.session_id = "native-result-policy"
        self._persona_chat_root_session_id = self.session_id
        self._persona_chat_client_message_id = "turn-input"
        self._persona_chat_turn_id = "turn-one"
        self._session_db = db
        self._session_db_created = True
        self._last_flushed_db_idx = 0
        db.create_session(self.session_id, "test")


@pytest.fixture
def native_agent(tmp_path):
    db = SessionDB(tmp_path / "state.db")
    try:
        yield _NativeAgent(db)
    finally:
        db.close()


def _turn(results):
    arguments = json.dumps({"source": "-- authored behavior\n" * 700 + "return 42"})
    calls = [
        {"id": f"call-{i}", "type": "function", "function": {
            "name": "launcher_generated_inspect", "arguments": arguments,
        }}
        for i in range(len(results))
    ]
    return [
        {"role": "user", "content": "Inspect the authored behavior"},
        {"role": "assistant", "content": "Inspecting", "tool_calls": calls},
        *[{"role": "tool", "tool_name": "launcher_generated_inspect",
           "tool_call_id": f"call-{i}", "content": content}
          for i, content in enumerate(results)],
    ]


def _flush_and_replay(agent, messages):
    assert agent._flush_messages_to_session_db(messages) is True
    # Repeat persistence too: removal of clipping must not disturb dedup.
    assert agent._flush_messages_to_session_db(messages) is True
    history = agent._session_db.get_messages_as_conversation(agent.session_id)
    replay = safe_native_history(history)
    assert len(replay) == len(messages)
    return replay


@pytest.mark.parametrize("chars", [30_000, 120_000])
def test_upstream_result_and_arguments_survive_flush_and_replay(native_agent, chars, caplog):
    original = json.dumps({"data": {"text": "x" * chars + " RESULT TAIL"}})
    result = maybe_persist_tool_result(original, "launcher_generated_inspect", "call-0", env=None)
    messages = _turn([result])
    arguments = messages[1]["tool_calls"][0]["function"]["arguments"]
    assert len(arguments) > 12_000
    with caplog.at_level(logging.WARNING):
        replay = _flush_and_replay(native_agent, messages)
    for rows in (messages, replay):
        assert rows[2]["content"] == result
        assert rows[2]["tool_call_id"] == rows[1]["tool_calls"][0]["id"] == "call-0"
        assert rows[1]["tool_calls"][0]["function"]["arguments"] == arguments
        assert json.loads(rows[1]["tool_calls"][0]["function"]["arguments"])["source"].endswith("return 42")
        assert native_wire_row(rows[2]).notes == ()
        assert native_wire_row(rows[2]).drift_row() is None
    assert "wire boundary cut" not in caplog.text
    path = extract_persisted_path(result)
    if chars == 30_000:
        assert path is None and result == original
    else:
        assert path and Path(path).read_text(encoding="utf-8") == original


def test_aggregate_budget_remains_upstream_owned(native_agent):
    originals = ["a" * 30_000 + " FIRST TAIL", "b" * 35_000 + " SECOND TAIL"]
    messages = _turn(originals)
    tool_rows = messages[2:]
    enforce_turn_budget(tool_rows, env=None, config=BudgetConfig(turn_budget=40_000))
    expected = [row["content"] for row in tool_rows]
    paths = [extract_persisted_path(content) for content in expected]
    assert sum(path is not None for path in paths) == 1
    replay = _flush_and_replay(native_agent, messages)
    assert [row["content"] for row in replay[2:]] == expected
    for i, path in enumerate(paths):
        if path:
            assert Path(path).read_text(encoding="utf-8") == originals[i]
        else:
            assert expected[i] == originals[i]


@pytest.mark.parametrize("role", ["assistant", "system", "tool"])
def test_non_user_content_has_no_replacement_ceiling(native_agent, role):
    content = "ordinary text " * 23_000 + " CONTENT TAIL"
    assert len(content) > 262_144
    messages = _turn([content]) if role == "tool" else [{"role": role, "content": content}]
    replay = _flush_and_replay(native_agent, messages)
    assert messages[-1]["content"] == replay[-1]["content"] == content


def test_redaction_and_pairing_survive_large_arguments(native_agent):
    messages = _turn([json.dumps({"api_key": "private-value", "text": "x" * 30_000 + " TAIL"})])
    function = messages[1]["tool_calls"][0]["function"]
    args = json.loads(function["arguments"])
    args["api_key"] = "private-value"
    function["arguments"] = json.dumps(args)
    replay = _flush_and_replay(native_agent, messages)
    for rows in (messages, replay):
        assert "private-value" not in json.dumps(rows)
        assert json.loads(rows[2]["content"])["text"].endswith(" TAIL")
        assert json.loads(rows[1]["tool_calls"][0]["function"]["arguments"])["source"] == args["source"]
        assert rows[2]["tool_call_id"] == rows[1]["tool_calls"][0]["id"]


def test_flush_keeps_cut_and_drift_receipts(native_agent, monkeypatch, caplog):
    def damaged_projection(message):
        bound = native_wire_row(message)
        return replace(bound, redacted_chars=30_000, wire_chars=10_000, notes=(
            ContentBoundNote(BOUND_PART_CONTENT, BOUND_ACTION_TRUNCATED, 30_000, 20_000, 20_000),
        ))

    monkeypatch.setattr(native_persistence, "native_wire_row", damaged_projection)
    with caplog.at_level(logging.WARNING):
        assert native_agent._flush_messages_to_session_db(_turn(["CONTENT-SENTINEL"])) is True
    assert "10000 unaccounted chars" in caplog.text
    assert "tool=launcher_generated_inspect" in caplog.text
    assert "30000->20000/20000" in caplog.text
    assert "CONTENT-SENTINEL" not in caplog.text
