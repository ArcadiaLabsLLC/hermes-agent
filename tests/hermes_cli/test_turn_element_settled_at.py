"""Each settled turn element carries its own settle time (RT-TURN-ELEMENT-TIMESTAMPS).

Before this, a reloaded turn's ``turn_elements`` had no per-element time, so the
launcher's history rows for one turn all showed the agent message's single
timestamp. The emitter now stamps ``settled_at`` when a segment ends and when a
tool finishes, and the turn store keeps it through ``_safe_elements``.

Killing mutations (recorded in the landing commit): drop the ``settled_at`` key
from ``records._safe_element`` -> the round-trip test reds; drop the stamp in
``_tool_finished`` -> the emitter test reds on the tool element.
"""

from __future__ import annotations

import itertools

from agent_runtime.mission_chat_turns import (
    MissionChatTurnPersistOutcome,
    mission_chat_turn_record,
    persist_mission_chat_turn,
)
from hermes_cli.harness_parts.persona import chat_events


def _stamps(monkeypatch):
    counter = itertools.count(1)
    monkeypatch.setattr(
        chat_events, "now_iso_micro", lambda: f"2026-10-26T10:00:0{next(counter)}.000000Z"
    )


def _drive_turn():
    item = chat_events._ChatProtocolV2Emitter(
        turn_id="turn_1", client_message_id="client_1", emit_frames=False
    )
    item.delta("looking")
    item.progress({"type": "run.tool.started", "tool_name": "terminal", "summary": "ls"})
    item.progress({"type": "run.tool.finished", "tool_name": "terminal", "status": "ok"})
    item.delta("done")
    item.finish(state="completed")
    return item.elements


def test_emitter_stamps_each_element_when_it_settles(monkeypatch):
    _stamps(monkeypatch)
    elements = _drive_turn()
    assert [(e["kind"], e.get("settled_at")) for e in elements] == [
        ("segment", "2026-10-26T10:00:01.000000Z"),
        ("tool", "2026-10-26T10:00:02.000000Z"),
        ("segment", "2026-10-26T10:00:03.000000Z"),
    ]


def test_settle_times_survive_the_turn_store(monkeypatch):
    _stamps(monkeypatch)
    outcome = persist_mission_chat_turn(
        session_id="s_settled",
        client_message_id="client_1",
        turn_id="turn_1",
        elements=_drive_turn(),
        state="completed",
    )
    assert outcome is MissionChatTurnPersistOutcome.PERSISTED
    stored = mission_chat_turn_record(session_id="s_settled", client_message_id="client_1")["elements"]
    assert [e.get("settled_at") for e in stored] == [
        "2026-10-26T10:00:01.000000Z",
        "2026-10-26T10:00:02.000000Z",
        "2026-10-26T10:00:03.000000Z",
    ]


def test_an_unstamped_legacy_element_gains_no_key():
    """Positive control for the absent-when-absent rule: the same store path,
    an element with no stamp, and no ``settled_at`` is invented."""

    persist_mission_chat_turn(
        session_id="s_legacy",
        client_message_id="m1",
        turn_id="t1",
        elements=[{"kind": "segment", "id": "t1_seg_1", "turn_id": "t1", "seq": 1, "text": "hi"}],
        state="completed",
    )
    (element,) = mission_chat_turn_record(session_id="s_legacy", client_message_id="m1")["elements"]
    assert "settled_at" not in element
