"""A steer reaches the model as the bytes its stored row will hold.

RT-REDACTION-REWRITE-MAY-BREAK-PROMPT-CACHE ("read, inferred - measure first"). Measured by
reading the order of sends and flushes. The flush's wire boundary
(``native_persistence.project_native_message``) rewrites the LIVE message with its redacted
row. The turn's user row, each tool request and each tool result are flushed before the next
provider call, so they are never sent in two forms. A steer row is the exception: upstream
appends it after the newest tool result with no persisted mark and flushes it at the NEXT
tool round, after one request has already carried it. A steer the redactor changes was sent
raw, then rewritten, and every later request differed from that row on.

The steer door now redacts first, so the row the model is sent and the row the flush stores
are the same bytes. These tests drive the real door and the real boundary.
"""

from __future__ import annotations

import pytest

from agent_runtime.mission_chat_steer import start_active_mission_chat_turn, submit_mission_chat_steer
from agent_runtime.persona_chat_continuity import native_wire_row
from agent_runtime.persona_chat_continuity.bounds import _redacted

SECRET = "sk-ant-api03-" + "A1b2C3d4" * 6
SECRET_TEXT = f"retry it with key {SECRET} this time"


class _Agent:
    def __init__(self):
        self.steers: list = []

    def steer(self, pending) -> bool:
        self.steers.append(pending)
        return True


def _steer(tmp_path, text: str, *, notification: bool = False):
    agent = _Agent()
    handle = start_active_mission_chat_turn(runtime_root=tmp_path, session_id="s-live", agent=agent)
    try:
        ack = submit_mission_chat_steer(
            runtime_root=tmp_path, session_id="s-live", message=text,
            client_message_id="cm-steer", notification=notification)
    finally:
        handle.close()
    assert ack["ok"] is True
    (pending,) = agent.steers
    return pending


def test_the_control_text_is_one_the_redactor_changes():
    assert _redacted(SECRET_TEXT) != SECRET_TEXT


@pytest.mark.parametrize("notification", [False, True], ids=["operator_steer", "process_notice"])
def test_the_flush_leaves_a_steer_row_byte_identical(tmp_path, notification):
    pending = _steer(tmp_path, SECRET_TEXT, notification=notification)

    rows = pending.rows()
    assert rows, "the steer produced no row"
    for row in rows:
        assert SECRET not in row["content"], "the model is sent the raw secret"
        stored = native_wire_row(row).row["content"]
        assert stored == row["content"], "the flush rewrites a row the model was already sent"


def test_a_steer_with_nothing_to_redact_is_untouched(tmp_path):
    pending = _steer(tmp_path, "also check the logs")
    assert str(pending) == "also check the logs"
