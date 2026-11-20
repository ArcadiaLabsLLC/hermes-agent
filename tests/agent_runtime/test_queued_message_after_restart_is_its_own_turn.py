"""After a restart, a message that waited behind a cut-off reply reaches the model as its own turn.

RT-FU-A-QUEUED-MESSAGE-RUN-AFTER-A-RESTART-IS-ANSWERED-AS-ITSELF (review w1118a.58 D9). Seen live
2026-11-20 (lane w1118a-hwin, sandbox ``harness serve``, fake model): a lead chat busy with a slow
delivery turn, a send queued behind it, the serve stopped with SIGTERM. The next serve ran the queued
send, but the cut-off turn's user message had no reply, so the model request carried the delivery
text and the queued text as ONE user turn ("Repaired 1 message-alternation violations") and the
model answered the delivery words.

The fork's boot sweep (``repair_orphaned_chat_turns``) now closes the cut-off turn in the
transcript with upstream's own hidden interrupt row; upstream's alternation repair is untouched.
"""

from __future__ import annotations

from agent_runtime.chat_session_scope import SessionDbAccess, open_chat_session_db, resolve_chat_session_scope
from agent_runtime.mission_chat_turns import mission_chat_turn_record, transition_mission_chat_turn
from agent_runtime.persona_chat_continuity import repair_orphaned_chat_turns
from agent_runtime.persona_chat_session import _persona_chat_native_history, _persona_chat_native_tip

ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"
CUT_OFF = "[BACKGROUND DISPATCH COMPLETE — dispatch-abc123] WORKER-TASK: build the thing"
QUEUED = "What is two plus two?"


def _db():
    return open_chat_session_db(resolve_chat_session_scope(session_id=ROOT), access=SessionDbAccess.WRITE)


def _cut_off_turn(*, tail: list[dict] | None = None) -> None:
    """A lead chat whose turn was running when the serve stopped: its user row, no reply."""

    db = _db()
    try:
        db.ensure_session(ROOT, source="persona_chat")
        db.append_message(ROOT, "user", "hello")
        db.append_message(ROOT, "assistant", "hi")
        db.append_message(ROOT, "user", CUT_OFF, platform_message_id="cm-cut")
        for row in tail or []:
            db.append_message(ROOT, **row)
    finally:
        db.close()
    for state in ("pending", "executing"):
        transition_mission_chat_turn(session_id=ROOT, client_message_id="cm-cut", turn_id="cm-cut", state=state,
                                     metadata={"root_chat_session_id": ROOT})


def _next_turn_history() -> list[dict]:
    """The queued send's turn: its user row lands, then the history the model is fed is read."""

    db = _db()
    try:
        tip = _persona_chat_native_tip(db, ROOT)
        db.append_message(tip, "user", QUEUED)
        return _persona_chat_native_history(db, tip)
    finally:
        db.close()


def test_a_queued_message_run_after_a_restart_reaches_the_model_as_its_own_turn():
    """KILLING MUTATION (run 2026-11-20): ``repair_orphaned_chat_turns`` without the
    ``close_cut_off_transcript(root)`` call -> the history ends in ONE user row holding both texts, red."""

    _cut_off_turn()

    assert repair_orphaned_chat_turns() == [ROOT]

    history = _next_turn_history()
    assert history[-1]["role"] == "user" and history[-1]["content"] == QUEUED
    assert [row["role"] for row in history[-3:]] == ["user", "assistant", "user"]
    assert history[-3]["content"] == CUT_OFF
    # The journal still says the cut-off turn was interrupted, and a reload still draws its marker:
    # the hidden closing row is no reply and is not drawn.
    assert mission_chat_turn_record(session_id=ROOT, client_message_id="cm-cut")["state"] == "interrupted"
    from agent_runtime.persona_chat_history.history_rows import _safe_recent_messages

    db = _db()
    try:
        rows, _status, _unread = _safe_recent_messages(db, session_id=ROOT)
    finally:
        db.close()
    markers = [row for row in rows if row.get("kind") == "turn_interrupted"]
    assert [marker["client_message_id"] for marker in markers] == ["cm-cut"]
    assert not [row for row in rows if row.get("role") == "agent" and not row.get("text")]


def test_the_closing_row_is_upstreams_hidden_interrupt_row():
    """Hidden in the transcript a person reads; a neutral label, never prose, on the wire."""

    from agent.agent_runtime_helpers_placeholders import hidden_interrupt_placeholder_row

    _cut_off_turn()
    repair_orphaned_chat_turns()

    db = _db()
    try:
        last = db.get_messages(_persona_chat_native_tip(db, ROOT), limit=1, latest=True)[-1]
    finally:
        db.close()
    expected = hidden_interrupt_placeholder_row()
    assert (last["role"], last["content"], last["display_kind"], last["api_content"]) == (
        expected["role"], expected["content"], expected["display_kind"], expected["api_content"])


def test_a_transcript_that_already_ends_on_a_reply_gets_nothing_added():
    """A turn cut after its reply was stored (the journal not yet settled) needs no closing row."""

    _cut_off_turn(tail=[{"role": "assistant", "content": "the reply"}])
    repair_orphaned_chat_turns()

    db = _db()
    try:
        last = db.get_messages(_persona_chat_native_tip(db, ROOT), limit=1, latest=True)[-1]
    finally:
        db.close()
    assert (last["role"], last["content"]) == ("assistant", "the reply")


def test_a_turn_cut_while_its_tool_ran_is_closed_too():
    """Seen live 2026-11-20 (w1118a-hrun, Eternia account C, hermes worktree): the cut-off delivery turn
    had started a ``terminal`` call, so its transcript ended on an assistant row with an unanswered
    ``tool_calls``; upstream's repair pruned the call, dropped the row, and the queued message merged into
    the cut-off one again — the model ran the cut-off turn's ``sleep 170`` a second time.

    KILLING MUTATION (run 2026-11-20): ``_closing_rows`` returning ``[]`` for an assistant tail (the first
    cut) -> the queued message is merged, red.
    """

    from agent.agent_runtime_helpers import repair_message_sequence

    call = {"id": "call_1", "type": "function", "function": {"name": "terminal", "arguments": "{}"}}
    _cut_off_turn(tail=[{"role": "assistant", "content": "", "tool_calls": [call]}])

    assert repair_orphaned_chat_turns() == [ROOT]

    history = _next_turn_history()
    repair_message_sequence(None, history)  # the turn's own pre-call repair, as upstream runs it
    assert history[-1]["role"] == "user" and history[-1]["content"] == QUEUED
    assert any(row.get("role") == "tool" and row.get("tool_call_id") == "call_1" for row in history)
