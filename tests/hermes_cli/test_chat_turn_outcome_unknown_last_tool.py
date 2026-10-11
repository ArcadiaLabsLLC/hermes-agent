"""An outcome_unknown resend refusal names the last tool the dead executor ran.

2026-10-02 (hermes 9eeb00b048): a turn whose executor died after a tool step was
answered with the generic "the prior provider outcome cannot be proven" sentence;
the journal's tool elements already held where it stopped.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime.mission_chat_turns.records import _safe_elements
from agent_runtime.mission_chat_turns.states import TURN_STATE_OUTCOME_UNKNOWN
from hermes_cli.harness_parts.persona.chat_turn_commit.admit import _SETTLED_REFUSALS


def _turn(elements):
    journal = {"turn_id": "t1", "elements": _safe_elements(elements)}
    return SimpleNamespace(journal_state=TURN_STATE_OUTCOME_UNKNOWN, journal=journal,
                           session_id="persona_chat_x", client_message_id="cm1")


def _tool(seq, name, status, exit_code=None):
    return {"kind": "tool", "id": f"tool-{seq}", "turn_id": "t1", "seq": seq, "name": name,
            "status": status, "exit_code": exit_code, "summary": f"{name} {status}"}


def test_the_refusal_names_the_last_tool_and_its_outcome():
    payload = _SETTLED_REFUSALS[TURN_STATE_OUTCOME_UNKNOWN](_turn([
        _tool(1, "read_file", "completed"),
        {"kind": "segment", "id": "seg-2", "turn_id": "t1", "seq": 2, "text": "running it"},
        _tool(3, "terminal", "failed", exit_code=1),
    ]))
    assert payload["last_tool"]["name"] == "terminal"
    assert payload["last_tool"]["status"] == "failed" and payload["last_tool"]["exit_code"] == 1
    assert "the last tool this turn ran was 'terminal' (failed, exit 1)" in payload["error"]
    assert "'terminal' left behind" in payload["next_expected"]
    assert payload["next_expected"].startswith("resolve the exact outcome_unknown turn with action=abandon")


def test_a_turn_that_ran_no_tool_keeps_the_plain_refusal():
    payload = _SETTLED_REFUSALS[TURN_STATE_OUTCOME_UNKNOWN](_turn([]))
    assert payload["last_tool"] is None
    assert payload["error"] == "the prior provider outcome cannot be proven; resolve this turn before resending"
