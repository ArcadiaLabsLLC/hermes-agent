"""A stopped turn and a turn whose model returned nothing are not replies.

RT-STOPPED-TURN-SETTLES-AS-A-REPLY: an operator Stop reaches the agent's interrupt seam and
the run RETURNS (``interrupted: True``) with ``final_response`` ``None``, upstream's
"waiting for model response" banner, or the half-written text. The lane settled all three as
an ordinary reply (the first as the text ``None``).

RT-EMPTY-MODEL-REPLY-SETTLES-AS-A-REPLY: after its retries upstream returns the literal
``(empty)`` (also the stored assistant row), and the lane settled it as a reply.

The handler, lease, journal and history projection are the production ones; only the
provider is stubbed, with result dicts in upstream's shape passed through the runner's own
``_normalize_result``.
"""

from __future__ import annotations

import pytest

from agent.conversation_loop import INTERRUPT_WAITING_FOR_MODEL_PREFIX
from agent_runtime import chat_root_send_queue
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from agent_runtime.persona_chat_history.markers import _terminal_turn_marker_rows
from agent_runtime.persona_chat_history.vocabulary import (
    PERSONA_TURN_INTERRUPTED_KIND,
    STOPPED_TURN_MARKER_TEXT,
    TERMINAL_TURN_MARKERS,
)
from agent_runtime.profile_runner.runner import _normalize_result
from agent_runtime.turn_visibility import classify_persisted_turn_row, classify_turn_visibility
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT, _args, _install_chat_lane

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _turn(monkeypatch, client_message_id: str, result: dict) -> tuple[int, dict]:
    """Run one real turn whose provider returns ``result`` (upstream's run-result shape)."""

    handler = _install_chat_lane(monkeypatch)

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            return _normalize_result({"messages": [], "api_calls": 1, **result}, agent=None)

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    payloads: list[dict] = []
    args = _args(client_message_id)
    args.payload_sink = payloads.append
    code = handler._cmd_mission_chat_message(args)
    assert payloads, "the turn emitted no terminal frame"
    return code, payloads[-1]


def _marker(client_message_id: str) -> dict:
    rows = _terminal_turn_marker_rows(session_id=ROOT, assistant_client_message_ids=set())
    return next(row for row in rows if row["client_message_id"] == client_message_id)


@pytest.mark.parametrize(
    "final_response",
    [None, f"{INTERRUPT_WAITING_FOR_MODEL_PREFIX}3.2s elapsed)."],
    ids=["nothing_written", "upstream_banner"],
)
def test_a_stopped_turn_with_nothing_written_is_recorded_stopped(
    monkeypatch, isolate_agent_runtime_root, final_response
):
    code, frame = _turn(
        monkeypatch, "cm-stopped",
        {"final_response": final_response, "interrupted": True, "turn_exit_reason": "interrupted_by_user"},
    )

    assert code == 0 and frame["ok"] is True
    assert frame["stopped"] is True and frame["execution_state"] == "stopped"
    assert frame["reply"] == "", "a stop wrote a reply nobody said"
    assert frame["turn_visibility"]["state"] == "silent"
    assert frame["turn_visibility"]["reason"] == "stopped"
    assert frame["turn_resolution_required"] is False

    record = mission_chat_turn_record(session_id=ROOT, client_message_id="cm-stopped")
    assert record["state"] == "interrupted" and record["stopped"] is True
    assert "stored_reply" not in record

    marker = _marker("cm-stopped")
    assert marker["kind"] == PERSONA_TURN_INTERRUPTED_KIND
    assert marker["stopped"] is True and marker["text"] == STOPPED_TURN_MARKER_TEXT


def test_a_stopped_turn_keeps_the_text_already_written(monkeypatch, isolate_agent_runtime_root):
    code, frame = _turn(
        monkeypatch, "cm-stopped-partial",
        {"final_response": "Here is the first half", "interrupted": True},
    )

    assert code == 0 and frame["stopped"] is True and frame["execution_state"] == "stopped"
    assert frame["reply"] == "Here is the first half"
    assert frame["turn_visibility"]["state"] == "visible"
    record = mission_chat_turn_record(session_id=ROOT, client_message_id="cm-stopped-partial")
    assert record["state"] == "interrupted" and record["stopped"] is True
    assert record["stored_reply"] == "Here is the first half"


def test_a_crashed_turns_marker_is_not_called_stopped(monkeypatch, isolate_agent_runtime_root):
    """The twin: an ``interrupted`` record with no ``stopped`` keeps the crash sentence."""

    from agent_runtime.mission_chat_turns import (
        mark_stale_inflight_turns_interrupted,
        transition_mission_chat_turn,
    )

    transition_mission_chat_turn(
        session_id=ROOT, client_message_id="cm-crashed", turn_id="cm-crashed", state="pending")
    assert mark_stale_inflight_turns_interrupted(
        session_id=ROOT, active_client_message_id="cm-other") == ["cm-crashed"]
    marker = _marker("cm-crashed")
    assert "stopped" not in marker
    assert marker["text"] == TERMINAL_TURN_MARKERS["interrupted"].text


def test_a_leftover_steer_of_a_stopped_turn_is_still_queued(monkeypatch, isolate_agent_runtime_root):
    code, _frame = _turn(
        monkeypatch, "cm-stopped-steer",
        {"final_response": None, "interrupted": True, "pending_steer": "and then the logs"},
    )
    assert code == 0
    entry = chat_root_send_queue.find(ROOT, "steer-next-cm-stopped-steer")
    assert entry is not None and entry.args["message"] == "and then the logs"


@pytest.mark.parametrize(
    "final_response",
    ["(empty)", "The model returned no content after several attempts."],
    ids=["sentinel", "upstream_explainer_sentence"],
)
def test_a_model_that_returned_nothing_settles_silent_not_as_a_reply(
    monkeypatch, isolate_agent_runtime_root, final_response
):
    code, frame = _turn(
        monkeypatch, "cm-empty",
        {"final_response": final_response, "turn_exit_reason": "empty_response_exhausted"},
    )

    assert code == 0
    assert frame["reply"] == "", "the empty-reply sentinel was sent as the agent's reply"
    assert frame["turn_visibility"]["state"] == "silent"
    assert frame["turn_visibility"]["reason"] == "empty"
    assert "stopped" not in frame
    record = mission_chat_turn_record(session_id=ROOT, client_message_id="cm-empty")
    assert record["state"] == "projected" and record["stored_reply"] == ""


def test_a_real_reply_is_untouched(monkeypatch, isolate_agent_runtime_root):
    """Positive control's twin: neither arm fires on an ordinary reply."""

    code, frame = _turn(
        monkeypatch, "cm-real", {"final_response": "all done", "turn_exit_reason": "text_response(finish_reason=stop)"})
    assert code == 0 and frame["reply"] == "all done" and "stopped" not in frame
    assert frame["execution_state"] == "completed" and frame["turn_visibility"]["state"] == "visible"


def test_the_stored_empty_sentinel_row_reads_as_a_silent_turn():
    """Reload: upstream stores the sentinel as the assistant row; history must not show it as a reply."""

    stored = classify_persisted_turn_row(content="(empty)", finish_reason="stop")
    assert stored is not None and stored.is_silent and stored.reason.value == "empty"
    assert classify_persisted_turn_row(content="(empty) but more", finish_reason="stop").is_visible
    assert classify_turn_visibility(reply_text="(empty)").is_silent
