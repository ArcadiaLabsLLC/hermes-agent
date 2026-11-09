"""A harness notice steered into a turn reaches the operator transcript as a typed, titled notice.

RT-RUNTIME-NOTICE-ROW-SHIPS-RAW-NOTE: a ``display_kind: runtime_notice`` row (the wall-budget
checkpoint, the MCP availability update) used to ship as a plain system message whose body was the
model-facing note, envelope and all, while its operator title went unused.
RT-ITERATION-LIMIT-NUDGE-STORED-AS-USER: the tool-iteration limit's summary request was a plain
role-user row the transcript served as the operator's own message.
"""

from __future__ import annotations

from types import SimpleNamespace

from agent.steering import RUNTIME_NOTE_ENVELOPE, PendingSteer
from agent_runtime.operator_channels.history_messages import _conversation_history_message
from agent_runtime.persona_chat_history.curation import _safe_curated_messages
from tools.process_registry_notifications import TimelineNotification

NOTE = "[harness] Wall budget nearly exhausted: 12s left. Wrap up."


def _project(rows):
    db = SimpleNamespace(get_messages=lambda _: rows)
    history, _, error = _safe_curated_messages(db, session_id="chat")
    assert error is None
    return [_conversation_history_message(row, channel_id="channel", index=index,
                                          persona_id="profile_dev", persona_instance_id="dev")
            for index, row in enumerate(history)]


def _notice_row(kind="runtime_notice", title="Time budget checkpoint"):
    row = PendingSteer.from_text(TimelineNotification(NOTE, title, kind, "diagnostic")).rows()[0]
    assert row["content"] == RUNTIME_NOTE_ENVELOPE + NOTE  # the model still reads the envelope
    return row


def test_a_runtime_notice_is_typed_and_titled_with_its_note_as_the_body():
    messages = _project([{"role": "user", "content": "Start", "platform_message_id": "prompt"}, _notice_row()])
    notice = messages[-1]
    assert notice["role"] == "system"
    assert notice["kind"] == "runtime_notice"
    assert notice["actor_persona_id"] == "harness" and notice["actor_instance_id"] is None
    assert notice["display_title"] == "Time budget checkpoint"
    assert notice["display_text"] == NOTE
    assert notice["notification_category"] == "diagnostic"


def test_another_timeline_notification_keeps_its_kind_and_gains_its_title():
    messages = _project([_notice_row(kind="process_completed", title="Build finished")])
    notice = messages[-1]
    assert notice["kind"] == "system_message"
    assert notice["display_title"] == "Build finished"
    assert notice["display_text"] == NOTE


def test_an_operator_message_carries_no_notice_fields():
    messages = _project([{"role": "user", "content": RUNTIME_NOTE_ENVELOPE + "typed by me",
                          "platform_message_id": "prompt"}])
    assert messages[0]["role"] == "operator"
    assert messages[0]["display_title"] == ""
    assert "notification_category" not in messages[0]


def test_the_iteration_limit_nudge_is_a_runtime_notice_not_an_operator_message(monkeypatch):
    from agent import chat_completion_helpers as helpers
    from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST

    captured = []

    def stop(agent, api_messages):
        captured.extend(m for m in api_messages if m.get("content") == MAX_ITERATIONS_SUMMARY_REQUEST)
        raise RuntimeError("stop after the nudge")

    monkeypatch.setattr(helpers, "_iteration_summary_api_messages", stop)
    agent = SimpleNamespace(max_iterations=3, suppress_status_output=True, api_mode="chat_completions")
    messages = [{"role": "user", "content": "do the work", "platform_message_id": "prompt"}]
    try:
        helpers.handle_max_iterations(agent, messages, 3)
    except Exception:
        pass
    # Upstream appends the nudge as a plain role-user row (its own bytes); the transcript types it
    # on read, by its content (FH-UPSTREAM-FOOTPRINT-UNLEDGERED-AUX-UNAVAILABLE).
    nudge = next(m for m in messages if m.get("content") == MAX_ITERATIONS_SUMMARY_REQUEST)
    assert nudge["role"] == "user"
    projected = _project([messages[0], nudge])
    assert [m["kind"] for m in projected] == ["operator_message", "runtime_notice"]
    assert projected[1]["display_title"] == "Tool-iteration limit reached"
    assert projected[1]["display_text"] == MAX_ITERATIONS_SUMMARY_REQUEST


def test_an_operator_row_that_only_resembles_the_nudge_stays_the_operators():
    from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST

    projected = _project([{"role": "user", "content": MAX_ITERATIONS_SUMMARY_REQUEST + " please",
                           "platform_message_id": "prompt"}])
    assert [m["kind"] for m in projected] == ["operator_message"]


def _checkpoint_turn(monkeypatch, trigger):
    from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST
    from agent_runtime.persona_chat_history import history_evidence

    record = {"client_message_id": "turn1", "turn_id": "turn1", "state": "projected", "budget_exhausted": True,
              "budget_trigger": trigger}
    monkeypatch.setattr(history_evidence, "mission_chat_turn_records", lambda **_: [record])
    notice = {**_notice_row(), "platform_message_id": "turn1:input:3"}
    return _project([
        {"role": "user", "content": "do the work", "platform_message_id": "turn1"},
        notice,
        {"role": "user", "content": MAX_ITERATIONS_SUMMARY_REQUEST, "platform_message_id": "turn1"},
        {"role": "assistant", "content": "Here is where I got to.", "platform_message_id": "turn1:assistant:5"},
    ])


def test_a_checkpoint_drained_turn_does_not_also_say_it_hit_the_iteration_limit(monkeypatch):
    """RT-CHECKPOINT-DRAIN-NUDGE-TYPED-AS-ITERATION-LIMIT: the checkpoint drains the iteration budget to
    stop new tool work; the summary request that follows is its mechanism, hidden. The checkpoint's own
    notice stays the turn's account.

    MUTATION: drop the ``_CHECKPOINT_TRIGGERS`` arm in ``_typed_iteration_limit_nudge`` and this reddens
    (a "Tool-iteration limit reached" notice beside "Time budget checkpoint")."""

    titles = [m["display_title"] for m in _checkpoint_turn(monkeypatch, "wall_budget_tool_gate")]
    assert "Time budget checkpoint" in titles
    assert "Tool-iteration limit reached" not in titles


def test_a_hard_wall_turn_keeps_the_iteration_limit_notice(monkeypatch):
    """Only a checkpoint trigger hides it: a turn the wall killed outright drained nothing."""

    titles = [m["display_title"] for m in _checkpoint_turn(monkeypatch, "wall_budget_hard_wall")]
    assert "Tool-iteration limit reached" in titles


def test_a_notice_sits_where_it_was_stored_in_its_turn_not_after_the_reply():
    """RT-RUNTIME-NOTICE-OUTSIDE-ITS-TURN-POSITION (live 2026-11-09): the checkpoint notice stored as
    ``<turn>:input:11`` projected a turn of its own and, on a clock 8 ms later than the reply's,
    ordered after it; the iteration-limit nudge, carrying the operator's id, sorted beside the
    operator row above the agent's tool-call step.

    MUTATION: stamp TURN_SEQ_TERMINAL for every member in ``_place_by_stored_position`` and this
    reddens (the notice sorts after the reply); drop the ``_STEERED_INPUT_ID`` arm and it reddens
    the same way (the notice is a turn of its own, ``turn1_input_3``, ordered after the reply)."""

    from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST

    stamp = "2026-11-09T12:00:{}Z".format
    rows = [
        {"role": "user", "content": "do the work", "platform_message_id": "turn1", "timestamp": stamp("01.000")},
        {"role": "assistant", "content": "Looking at the files first.", "platform_message_id": "turn1:assistant:1",
         "timestamp": stamp("02.000")},
        {"role": "user", "content": MAX_ITERATIONS_SUMMARY_REQUEST, "platform_message_id": "turn1",
         "timestamp": stamp("03.000")},
        {**_notice_row(), "platform_message_id": "turn1:input:3", "timestamp": stamp("24.500")},
        {"role": "assistant", "content": "Here is where I got to.", "platform_message_id": "turn1:assistant:5",
         "timestamp": stamp("24.492")},
    ]
    messages = _project(rows)
    assert [m["display_title"] or m["display_text"] for m in messages] == [
        "do the work", "Looking at the files first.", "Tool-iteration limit reached", "Time budget checkpoint",
        "Here is where I got to.",
    ]
    assert {m["turn_id"] for m in messages} == {"turn1"}
    assert messages[-1]["turn_seq"] == 1_000_000


def _coded_row(text, title, code):
    from agent_runtime.persona_chat_history.vocabulary import runtime_notice

    return PendingSteer.from_text(runtime_notice(text, title=title, code=code)).rows()[0]


def test_each_runtime_notice_says_which_notice_it_is(monkeypatch):
    """RT-RUNTIME-NOTICE-CODE-ON-ROW: Eternia placed the wall checkpoint in the turn's Harness card by
    matching the title "Time budget checkpoint", the only mark on the wire; every runtime notice now
    carries a typed ``notice_code``.

    MUTATION: drop the ``notice_code`` arm in ``_OperatorCurator.after_row`` and this reddens (no
    ``notice_code`` on any row); drop the ``code=`` read in ``PendingSteer.from_text`` and the stored row
    carries no code (the stored-row assertion reddens)."""

    from agent.context_compressor import MAX_ITERATIONS_SUMMARY_REQUEST

    stored = _coded_row(NOTE, "Time budget checkpoint", "wall_checkpoint")
    assert stored["display_metadata"]["notice_code"] == "wall_checkpoint"
    messages = _project([
        {"role": "user", "content": "do the work", "platform_message_id": "turn1"},
        {**stored, "platform_message_id": "turn1:input:2"},
        {**_coded_row("[harness] qa server unavailable", "Tool availability update", "tool_availability"),
         "platform_message_id": "turn1:input:3"},
        {"role": "user", "content": MAX_ITERATIONS_SUMMARY_REQUEST, "platform_message_id": "turn1"},
    ])
    assert [m.get("notice_code") for m in messages] == [None, "wall_checkpoint", "tool_availability",
                                                       "iteration_limit"]


def test_the_engaged_checkpoint_and_the_mcp_notice_steer_their_codes(monkeypatch):
    """The two runtime emitters stamp their codes: ``WallBudgetCheckpoint.engage`` and the MCP lane's
    execution-time admission notice.

    MUTATION: pass ``RUNTIME_NOTICE_TOOL_AVAILABILITY`` in ``budget.py``'s engage and this reddens
    (recorded red 2026-11-09); drop the ``code=`` read in ``PendingSteer.from_text`` and it reddens too."""

    from agent_runtime import mcp_admission
    from agent_runtime.profile_runner.budget import WallBudgetCheckpoint
    from agent_runtime.profile_runner.mcp_lane import _steer_mcp_admission_notice
    from agent_runtime.turn_budget import TurnWallBudget

    steered = []
    agent = SimpleNamespace(steer=steered.append)
    checkpoint = WallBudgetCheckpoint(TurnWallBudget(total_seconds=540.0, deadline_epoch=1_540.0),
                                      clock=lambda: 1_500.0)
    checkpoint.bind(agent)
    assert checkpoint.engage(trigger="wall_budget_tool_gate")
    monkeypatch.setattr(mcp_admission, "render_mcp_admission_line", lambda *_a, **_k: "- qa: unavailable")
    assert _steer_mcp_admission_notice(agent, None, SimpleNamespace(degraded=True))
    assert [(n.display_text, n.notice_code) for n in steered] == [
        ("Time budget checkpoint", "wall_checkpoint"), ("Tool availability update", "tool_availability")]
    assert [PendingSteer.from_text(n).rows()[0]["display_metadata"]["notice_code"] for n in steered] == [
        "wall_checkpoint", "tool_availability"]


def test_a_notice_stored_before_the_code_reads_its_code_from_its_title():
    """An older stored row (no ``notice_code``) still reads, and gets the code its title names."""

    messages = _project([_notice_row(), _notice_row(title="Tool availability update"),
                         _notice_row(title="Something new")])
    assert [m.get("notice_code") for m in messages] == ["wall_checkpoint", "tool_availability", None]
    assert [m["kind"] for m in messages] == ["runtime_notice"] * 3


def test_a_steered_notification_that_is_not_a_runtime_notice_carries_no_code():
    messages = _project([_notice_row(kind="process_completed", title="Time budget checkpoint")])
    assert messages[0]["kind"] == "system_message"
    assert "notice_code" not in messages[0]
