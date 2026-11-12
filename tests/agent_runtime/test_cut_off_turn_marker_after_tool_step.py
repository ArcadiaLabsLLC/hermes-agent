"""A turn cut off after it had started working still says so when the chat is reloaded.

RT-CRASHED-TURN-WAITS-FOR-NEXT-SEND. The serve-boot sweep (``repair_orphaned_chat_turns``)
already flips a crashed turn's record to ``interrupted`` before the first hydrate. What hid
the report was the history projection: ANY stored assistant row of the turn suppressed its
terminal marker, and a turn that reached one tool call has such a row (the tool request).
So the crashed turn the sweep had just marked reloaded as the operator's message and nothing
else. Only the turn's reply row may stand in for the marker.
"""

from __future__ import annotations

import pytest

from agent_runtime.mission_chat_turns import (
    mark_stale_inflight_turns_interrupted,
    transition_mission_chat_turn,
)
from agent_runtime.persona_chat_history.history_rows import _safe_recent_messages

SESSION = "s-cut-off"
TURN = "cm-cut-off"

_OPERATOR = {"role": "user", "content": "do it", "platform_message_id": TURN}
_TOOL_STEP = [
    {
        "role": "assistant", "content": "", "finish_reason": "tool_calls",
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}],
        "platform_message_id": f"{TURN}:assistant:1",
    },
    {"role": "tool", "content": "out", "tool_call_id": "c1", "platform_message_id": f"{TURN}:tool:2"},
]
_HALF_REPLY = [
    {
        "role": "assistant", "content": "half a reply", "display_metadata": {"interrupted": True},
        "platform_message_id": f"{TURN}:assistant:1",
    }
]
_REPLY = [{"role": "assistant", "content": "all done", "platform_message_id": f"{TURN}:assistant:1"}]


class _DB:
    def __init__(self, messages):
        self._messages = list(messages)

    def get_messages(self, session_id, include_inactive=False):
        return list(self._messages)


def _reload(stored: list[dict]) -> list[dict]:
    """A turn the executor left in flight, swept as the boot sweep sweeps it, then reloaded."""

    transition_mission_chat_turn(
        session_id=SESSION, client_message_id=TURN, turn_id=TURN, state="pending",
        metadata={"root_chat_session_id": SESSION},
    )
    assert mark_stale_inflight_turns_interrupted(session_id=SESSION, active_client_message_id=None) == [TURN]
    rows, _status, _unread = _safe_recent_messages(_DB([_OPERATOR, *stored]), session_id=SESSION)
    return rows


@pytest.mark.parametrize("stored", [[], _TOOL_STEP, _HALF_REPLY], ids=["nothing", "tool_step", "half_reply"])
def test_a_cut_off_turn_reloads_with_its_interrupted_marker(isolate_agent_runtime_root, stored):
    rows = _reload(stored)
    markers = [row for row in rows if row.get("kind") == "turn_interrupted"]
    assert len(markers) == 1, "the cut-off turn reloaded with nothing saying it was cut off"
    assert markers[0]["client_message_id"] == TURN and markers[0]["settled_state"] == "interrupted"
    assert rows[-1] is markers[0], "the marker is not the turn's last row"


def test_the_half_reply_is_still_shown_before_the_marker(isolate_agent_runtime_root):
    rows = _reload(_HALF_REPLY)
    assert [row.get("text") for row in rows if row.get("role") == "agent"] == ["half a reply"]


def test_a_turn_with_its_reply_gets_no_marker(isolate_agent_runtime_root):
    """The twin: a recorded reply still stands in for the marker (a reply or a marker, never both)."""

    rows = _reload(_REPLY)
    assert not [row for row in rows if row.get("kind") == "turn_interrupted"]
