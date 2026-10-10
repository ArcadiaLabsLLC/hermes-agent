"""A retried turn's lineage on the transcript rows (D2.04 S2).

``retry_of`` is stored ONCE, on the retry's own journal record; the interrupted
turn's record is terminal and is never written again. ``retried_as`` on the old
turn's marker row is therefore a LOOKUP over the session's records, done where
the projection already holds them all. Plan
``docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md`` § D2.04.
"""

from __future__ import annotations

from agent_runtime.mission_chat_turns import mission_chat_turn_record
from agent_runtime.mission_chat_turns.journal import persist_mission_chat_turn
from agent_runtime.operator_channels import _conversation_history_message
from agent_runtime.persona_chat_history.history_rows import _safe_recent_messages
from tests.agent_runtime.test_persona_chat_history_curation import FakeSessionDB

SESSION = "s-retry"


def _seed_turn(cmid: str, state: str, **metadata) -> None:
    persist_mission_chat_turn(
        session_id=SESSION,
        client_message_id=cmid,
        turn_id=cmid,
        elements=[],
        state=state,
        metadata=metadata or None,
    )


def _operator(cmid: str, text: str) -> dict:
    return {"id": f"op-{cmid}", "role": "user", "content": text, "platform_message_id": cmid}


def _reply(cmid: str, text: str) -> dict:
    return {"id": f"agent-{cmid}", "role": "assistant", "content": text, "platform_message_id": cmid}


def _rows(messages):
    rows, status, _unread = _safe_recent_messages(FakeSessionDB(messages), session_id=SESSION)
    assert status == "safe"
    return rows


def test_the_interrupted_marker_names_its_retry_and_the_retry_names_its_origin(
    isolate_agent_runtime_root,
):
    _seed_turn("cm-orig", "interrupted")
    _seed_turn("cm-retry", "projected", retry_of="cm-orig")

    rows = _rows([
        _operator("cm-orig", "do the thing"),
        _operator("cm-retry", "do the thing"),
        _reply("cm-retry", "done"),
    ])

    marker = next(row for row in rows if row.get("settled_state") == "interrupted")
    assert marker["client_message_id"] == "cm-orig"
    assert marker["retried_as"] == "cm-retry"
    retry_operator = next(
        row for row in rows if row["role"] == "operator" and row["client_message_id"] == "cm-retry"
    )
    assert retry_operator["retry_of"] == "cm-orig"
    original_operator = next(
        row for row in rows if row["role"] == "operator" and row["client_message_id"] == "cm-orig"
    )
    assert "retry_of" not in original_operator
    # The old record is never written: lineage is read, not stamped back.
    assert "retried_as" not in mission_chat_turn_record(session_id=SESSION, client_message_id="cm-orig")


def test_a_retry_of_a_retry_chains_and_the_newest_retry_wins(isolate_agent_runtime_root):
    _seed_turn("cm-1", "interrupted")
    _seed_turn("cm-2", "interrupted", retry_of="cm-1")
    _seed_turn("cm-3", "projected", retry_of="cm-2")

    rows = _rows([
        _operator("cm-1", "go"),
        _operator("cm-2", "go"),
        _operator("cm-3", "go"),
        _reply("cm-3", "went"),
    ])

    markers = {row["client_message_id"]: row for row in rows if row.get("settled_state")}
    assert markers["cm-1"]["retried_as"] == "cm-2"
    assert markers["cm-2"]["retried_as"] == "cm-3"
    assert markers["cm-2"].get("retry_of") is None  # a marker names its successor only


def test_a_marker_nobody_retried_carries_no_retried_as(isolate_agent_runtime_root):
    _seed_turn("cm-alone", "budget_exhausted")
    rows = _rows([_operator("cm-alone", "think hard")])
    marker = next(row for row in rows if row.get("settled_state") == "budget_exhausted")
    assert "retried_as" not in marker


def test_the_operator_conversation_projection_carries_both_keys():
    def project(row):
        return _conversation_history_message(
            row, channel_id="chan-1", index=0, persona_id="neko",
            persona_instance_id="personainst_neko", display_names={},
        )

    marker = project({
        "id": "s:turn-interrupted:cm-orig", "role": "system", "kind": "turn_interrupted",
        "text": "Agent turn interrupted before a reply was recorded.",
        "timestamp": "2026-10-10T10:00:00+00:00", "redaction_status": "safe",
        "client_message_id": "cm-orig", "turn_id": "cm-orig", "settled_state": "interrupted",
        "retried_as": "cm-retry",
    })
    assert marker is not None and marker["retried_as"] == "cm-retry"
    operator = project({
        "id": "op-cm-retry", "role": "operator", "text": "do the thing",
        "timestamp": "2026-10-10T10:01:00+00:00", "redaction_status": "safe",
        "client_message_id": "cm-retry", "retry_of": "cm-orig",
    })
    assert operator is not None and operator["retry_of"] == "cm-orig"
