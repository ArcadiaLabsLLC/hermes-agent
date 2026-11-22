"""A bare upstream-known key reaches no reader unmasked, lane by lane, through each lane's REAL path.

RT-FU-A-BARE-KEY-IN-A-STREAM-FRAME-OR-CHAT-LOG-LINE-IS-NOT-ASKED-OF-THE-ONE-SCRUBBER (review
w1118a.69: reproduce per lane first; only a lane that leaks asks the one scrubber). The keys
are FAKE: an upstream prefix shape (``hf_``, ``glpat-``) with filler, never a real credential.
"""

from __future__ import annotations

import json

from agent_runtime.chat_live_log import chat_live_log_path, reset_chat_live_log_state
from agent_runtime.continuity import return_summary_to_parent_session
from agent_runtime.events import EventLog
from agent_runtime.models import BoardCard
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_history import persona_chat_session_messages
from agent_runtime.progress import ChatProgressSink
from agent_runtime.snapshot.boards import board_card_row
from agent_runtime.stream.frames import delta_frame
from tests.agent_runtime.persona_samples import sample_personas
from tests.agent_runtime.persona_instance_mint import mint_hidden_copy

FAKE_HF = "hf_" + "QaF" + "FAKE" * 4 + "0000"
FAKE_GITLAB = "glpat-" + "FAKEfake" + "x" * 12
FAKES = (FAKE_HF, FAKE_GITLAB)
PROSE = f"deployed with {FAKE_HF} then pushed using {FAKE_GITLAB} ok"


def _leaks(value) -> list[str]:
    blob = value if isinstance(value, str) else json.dumps(value, default=str)
    return [key for key in FAKES if key in blob]


def _persona(persona_id: str):
    return next(persona for persona in sample_personas() if persona.id == persona_id)


def _child_returns(summary: str, session_id: str) -> None:
    store = PersonaInstanceStore()
    parent = mint_hidden_copy(store=store, persona=_persona("neko_supervisor"))
    child = mint_hidden_copy(store=store, persona=_persona("dev"))
    child = store.set_parents(child.id, [parent.id], goal_id="task_bare_key")
    return_summary_to_parent_session(child.id, parent_session_id=session_id, summary=summary)


def test_a_tool_result_s_bare_key_is_masked_in_its_stream_frame():
    # The stream's text comes from the progress sink, which asks the one scrubber at the
    # event's birth (``_safe_progress_payload``); the frame's own env-assignment pass is
    # the second line. Fed through the real sink and the real frame builder. No change was
    # needed on this lane (the review's order: a lane whose text always crossed upstream
    # closes with its test alone).
    # MUTATION: drop ``_redact_upstream`` from ``redaction.scrub_secret_values`` and this reddens.
    log = EventLog()
    sink = ChatProgressSink(session_id="bare_key_stream", persona_id="dev", turn_id="t1", event_log=log)
    sink.emit("run.tool.started", {"tool_name": "terminal", "summary": f"run {PROSE}"})
    sink.emit("run.tool.finished", {"tool_name": "terminal", "status": "passed",
                                    "summary": PROSE, "detail": PROSE, "output_tail": PROSE})
    sink.emit("run.progress", {"phase": "thinking", "summary": PROSE, "message": PROSE})
    events = log.for_session("bare_key_stream")
    assert {event.type for event in events} >= {"run.tool.started", "run.tool.finished"}
    for offset, event in enumerate(events, start=1):
        assert _leaks(delta_frame(event, offset=offset)) == []


def test_a_child_s_returned_bare_key_is_masked_in_the_live_chat_log():
    reset_chat_live_log_state()
    _child_returns(PROSE, "bare_key_live_log")
    path = chat_live_log_path("bare_key_live_log")
    assert path is not None and path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Continuity return from" in text
    assert _leaks(text) == []
    reset_chat_live_log_state()


def test_a_child_s_returned_bare_key_is_masked_in_the_chat_history():
    reset_chat_live_log_state()
    _child_returns(PROSE, "bare_key_history")
    from hermes_state import SessionDB

    page = persona_chat_session_messages(session_id="bare_key_history", session_db=SessionDB())
    assert page.get("messages"), page
    assert _leaks(page) == []
    reset_chat_live_log_state()


def test_a_board_card_s_bare_key_is_masked_in_the_snapshot():
    card = BoardCard(card_id="c1", board_id="b1", column_id="todo", order_key="a", title=f"rotate {FAKE_HF}",
                     description=PROSE)
    assert _leaks(board_card_row(card)) == []


def test_a_bare_key_in_a_chat_title_and_preview_is_masked():
    # The roster row's title (cut at 120) and preview (cut at 180) are cut AFTER the key is
    # hidden: a key straddling the cut would otherwise leave a head too short for any rule.
    from agent_runtime.persona_chat_history.history_rows import _history_row

    straddle = "x" * 170 + " " + FAKE_HF
    row = _history_row({"title": f"rotate {FAKE_GITLAB}", "preview": straddle},
                       persona_id="dev", instance_id="dev-1", session_id="bare_key_row")
    assert "«redacted:glpat-…»" in row["title"]
    assert "hf_QaF" not in json.dumps(row, default=str)
