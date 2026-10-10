"""Native projection retains upstream representation through real flush/replay."""
from copy import deepcopy
import json

import pytest

from agent.context_compressor import _DB_PERSISTED_MARKER
from agent.session_persistence import SessionPersistenceMixin
from agent_runtime.persona_chat_continuity import native_wire_row, safe_native_history
from agent_runtime.persona_chat_session import _persona_chat_native_history
from hermes_state import SessionDB


class _Agent(SessionPersistenceMixin):
    def __init__(self, db, *, native=True):
        self.session_id = "native" if native else "upstream"
        self._session_db = db
        self._session_db_created = True
        self._last_flushed_db_idx = 0
        if native:
            self._persona_chat_root_session_id = self.session_id
            self._persona_chat_client_message_id = "operator-one"
            self._persona_chat_turn_id = "turn-one"
        db.create_session(self.session_id, "test")


@pytest.fixture
def db(tmp_path):
    store = SessionDB(tmp_path / "state.db")
    try:
        yield store
    finally:
        store.close()


def _tool_turn(count=1):
    return [
        {"role": "user", "content": "Inspect"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call-{i}", "type": "function", "function": {
                "name": "inspect", "arguments": json.dumps({"index": i}),
            }} for i in range(count)
        ]},
        *[{"role": "tool", "tool_call_id": f"call-{i}", "tool_name": "inspect",
           "content": f"result-{i}"} for i in range(count)],
    ]


def _replay(agent):
    return safe_native_history(_persona_chat_native_history(agent._session_db, agent.session_id))


def test_every_valid_call_and_result_survives_live_flush_and_cold_replay(db):
    messages = _tool_turn(65)
    # Bad entries still fail admission to the call list, regardless of position.
    messages[1]["tool_calls"].insert(0, "malformed")
    messages[1]["tool_calls"].append({"id": "missing-function"})
    agent = _Agent(db)
    assert agent._flush_messages_to_session_db(messages)
    assert agent._flush_messages_to_session_db(messages)
    expected_ids = [f"call-{i}" for i in range(65)]
    for rows in (messages, _replay(agent)):
        assert [call["id"] for call in rows[1]["tool_calls"]] == expected_ids
        assert [row["tool_call_id"] for row in rows[2:]] == expected_ids
        assert [row["content"] for row in rows[2:]] == [f"result-{i}" for i in range(65)]
        assert rows[1]["content"] is None
    assert len(db.get_messages_as_conversation(agent.session_id)) == 67


@pytest.mark.parametrize("kind", ["user_parts", "tool_envelope", "json_data"])
def test_structured_live_content_and_durable_projection_match_upstream(db, kind):
    # Prefix deliberately matches the upstream secret scanner: opaque media
    # must not be scanned as ordinary text or its payload becomes corrupt.
    opaque = "gAAAA" + "z" * 60
    parts = [
        {"type": "text", "text": "readable text"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + opaque}},
        {"type": "input_audio", "input_audio": {"data": opaque, "format": "wav"}},
    ]
    messages = _tool_turn()
    index = 0 if kind == "user_parts" else 2
    content = {
        "user_parts": parts,
        "tool_envelope": {"_multimodal": True, "content": parts, "text_summary": "readable text"},
        "json_data": {"count": 0, "enabled": False, "missing": None, "items": [1, "plain"]},
    }[kind]
    messages[index]["content"] = deepcopy(content)
    upstream_messages = deepcopy(messages)
    native = _Agent(db)
    upstream = _Agent(db, native=False)
    assert upstream._flush_messages_to_session_db(upstream_messages)
    assert native._flush_messages_to_session_db(messages)
    assert messages[index]["content"] == upstream_messages[index]["content"] == content
    assert _replay(native)[index]["content"] == _replay(upstream)[index]["content"]


def test_metadata_reaches_upstream_storage_and_survives_cold_projection(db):
    messages = _tool_turn()
    opaque = "gAAAA" + "q" * 60
    metadata = {
        "reasoning": "provider reasoning",
        "reasoning_content": "provider reasoning content",
        "reasoning_details": [{"type": "reasoning.encrypted", "data": opaque}],
        "codex_reasoning_items": [{"type": "reasoning", "encrypted_content": opaque}],
        "codex_message_items": [{"type": "message", "id": "provider-message"}],
        "display_kind": "hidden",
        "display_metadata": {"reason": "diagnostic"},
        "message_uid": "durable-assistant",
        "_tool_call_uids": {"call-0": "durable-call"},
        "_absorbed_message_uids": ["absorbed-assistant"],
        "_compressed_summary": True,
        "timestamp": 1234.5,
    }
    messages[1].update(deepcopy(metadata))
    messages[2].update(effect_disposition="succeeded", _tool_call_uid="durable-call")
    agent = _Agent(db)
    assert agent._flush_messages_to_session_db(messages)
    for rows in (messages, _replay(agent)):
        assert {key: rows[1].get(key) for key in metadata} == metadata
        assert rows[2]["effect_disposition"] == "succeeded"
        assert rows[2]["_tool_call_uid"] == "durable-call"


def test_rewriting_a_native_row_keeps_upstream_durable_identity(db):
    agent = _Agent(db)
    messages = [{"role": "assistant", "content": "draft", "message_uid": "stable-answer"}]
    assert agent._flush_messages_to_session_db(messages)
    original = db.get_messages(agent.session_id)[0]
    messages[0].pop(_DB_PERSISTED_MARKER)
    messages[0]["content"] = "final answer"
    assert agent._flush_messages_to_session_db(messages)
    stored = db.get_messages(agent.session_id)
    assert len(stored) == 1
    assert stored[0]["id"] == original["id"]
    assert stored[0]["message_uid"] == "stable-answer"
    assert _replay(agent)[0]["content"] == "final answer"


def test_native_content_redacts_text_without_flattening_or_mutating_the_input():
    source = {"role": "tool", "content": {"_multimodal": True, "content": [
        {"type": "text", "text": 'api_key=short-secret'},
        {"type": "image", "source": {"data": "gAAAA" + "a" * 60}},
    ], "text_summary": "api_key=short-secret"}}
    original = deepcopy(source)
    bound = native_wire_row(source)
    assert source == original
    assert isinstance(bound.row["content"], dict)
    assert "short-secret" not in json.dumps(bound.row)
    assert bound.row["content"]["content"][1] == source["content"]["content"][1]
    assert bound.holds and bound.notes == ()
    assert native_wire_row(bound.row).row == bound.row
    data = {"role": "tool", "content": {"api_key": "tiny", "enabled": False, "nested": [None, 0]}}
    assert native_wire_row(data).row["content"] == {"api_key": "[redacted]", "enabled": False, "nested": [None, 0]}


def test_upstream_extensions_survive_without_another_field_allowlist():
    opaque = "gAAAA" + "b" * 60
    row = _tool_turn()[1]
    row["provider_extension"] = {"signed_payload": opaque}
    row["tool_calls"][0]["provider_extension"] = {"signature": opaque}
    row["tool_calls"][0]["function"]["provider_extension"] = {"format": "next-version"}
    bound = native_wire_row(row)
    assert bound.row == row
    assert bound.holds


def test_plain_json_arrays_keep_types_and_redact_nested_credentials():
    value = [{"api_key": "tiny", "nested": [{"password": "short"}]}, False, None, 0]
    original = deepcopy(value)
    bound = native_wire_row({"role": "tool", "content": value})
    assert value == original
    assert bound.row["content"] == [
        {"api_key": "[redacted]", "nested": [{"password": "[redacted]"}]}, False, None, 0,
    ]
    assert bound.holds


def test_distinct_durable_messages_are_not_deduplicated_by_equal_text():
    rows = [
        {"role": "assistant", "client_message_id": "turn", "content": "same", "message_uid": "first"},
        {"role": "assistant", "client_message_id": "turn", "content": "same", "message_uid": "second"},
    ]
    assert safe_native_history(rows) == rows
