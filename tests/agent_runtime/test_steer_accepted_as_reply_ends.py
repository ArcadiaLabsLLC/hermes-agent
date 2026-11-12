"""A steer accepted in the instant a reply finishes is delivered instead of dropped.

RT-STEER-ACCEPTED-AS-REPLY-ENDS. The steer watcher keeps accepting until the runner's cleanup
stops it, after upstream's finalizer has already drained the steer buffer for the last time. A
steer accepted in that gap is in neither the transcript nor ``pending_steer``, and the settle of
a turn that RETURNED used to drop its own ledger records unread. It now re-delivers a record of
its own turn too, when the steer's id is in neither place.

The first test is the proof that change stands on: a steer the turn DID absorb is found in a
real ``SessionDB`` under its own id, so an absorbed steer is never sent twice.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from agent.steering import PendingSteer
from agent_runtime import chat_root_send_queue, paths
from agent_runtime.mission_chat_steer import (
    start_active_mission_chat_turn,
    submit_mission_chat_steer,
    take_accepted_steers,
)
from hermes_cli.harness_parts.persona import chat_history_writes
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT, _args, _install_chat_lane

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def test_an_absorbed_steer_is_found_in_a_real_session_db_under_its_own_id(tmp_path, isolate_agent_runtime_root):
    """Real inbox, real steer buffer, real drain, real flush, real ``SessionDB`` read."""

    from agent.agent_runtime_helpers import apply_pending_steer_to_tool_results
    from agent.interrupt_control import InterruptControlMixin
    from agent.session_persistence import SessionPersistenceMixin
    from hermes_cli.harness_parts.persona.chat_events import _ChatProtocolV2Emitter
    from hermes_cli.harness_parts.persona.chat_history_writes import _persona_chat_existing_turn
    from hermes_state import SessionDB

    class NativeAgent(InterruptControlMixin, SessionPersistenceMixin):
        def __init__(self):
            self._pending_steer = None
            self._pending_steer_lock = threading.Lock()
            self._turn_user_intervened = False

    with SessionDB(tmp_path / "state.db") as db:
        db.create_session("chat", "test")
        agent = NativeAgent()
        agent.session_id = "chat"
        agent._session_db = db
        agent._session_db_created = True
        agent._last_flushed_db_idx = 0
        agent._persona_chat_root_session_id = "chat"
        agent._persona_chat_client_message_id = "prompt"
        agent._persona_chat_turn_id = "prompt"
        emitter = _ChatProtocolV2Emitter(turn_id="prompt", client_message_id="prompt", emit_frames=False)
        handle = start_active_mission_chat_turn(runtime_root=tmp_path, session_id="chat", agent=agent,
                                               client_message_id="prompt", input_position=emitter.input_position)
        try:
            assert submit_mission_chat_steer(runtime_root=tmp_path, session_id="chat", message="Check tests",
                                             client_message_id="cm-steer-absorbed")["ok"]
        finally:
            handle.close()
        messages = [{"role": "user", "content": "Start"}, {"role": "tool", "content": "done"}]
        apply_pending_steer_to_tool_results(agent, messages, 1)
        messages.append({"role": "assistant", "content": "Finished"})
        assert agent._flush_messages_to_session_db(messages)

        found = _persona_chat_existing_turn(session_db=db, session_id="chat", client_message_id="cm-steer-absorbed")
        assert found.get("operator"), "an absorbed steer row lost its platform_message_id: it would be sent twice"
        assert "Check tests" in str(found["operator"].get("content"))
        never = _persona_chat_existing_turn(session_db=db, session_id="chat", client_message_id="cm-steer-never")
        assert not never.get("operator")


class _Agent:
    def steer(self, text) -> bool:
        return True


def _steer(turn_id: str, steer_id: str, text: str) -> None:
    """One steer through the real door, accepted by a live watcher bound to ``turn_id``."""

    handle = start_active_mission_chat_turn(
        runtime_root=paths.store_root(), session_id=ROOT, agent=_Agent(), client_message_id=turn_id)
    try:
        ack = submit_mission_chat_steer(
            runtime_root=paths.store_root(), session_id=ROOT, message=text, client_message_id=steer_id)
    finally:
        handle.close()
    assert ack["ok"] is True and ack["execution_state"] == "accepted"


def _a_turn_returns_after_accepting(monkeypatch, steers: list[tuple[str, str]], *, pending=None):
    """Run ``cm-fine`` to a normal reply; it accepts ``steers`` and hands back ``pending``."""

    handler = _install_chat_lane(monkeypatch)

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            for steer in steers:
                _steer(kwargs["client_message_id"], *steer)
            raw = {} if pending is None else {"pending_steer": pending}
            return SimpleNamespace(final_response="reply", input_tokens=1, output_tokens=2, total_tokens=3, raw=raw)

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    assert handler._cmd_mission_chat_message(_args("cm-fine")) == 0
    assert take_accepted_steers(runtime_root=paths.store_root(), session_id=ROOT) == []


def test_a_steer_accepted_as_the_reply_ends_becomes_the_next_turn(monkeypatch, isolate_agent_runtime_root):
    """Accepted, but in neither the transcript nor ``pending_steer``: the gap the watcher leaves."""

    _a_turn_returns_after_accepting(monkeypatch, [("cm-steer-gap", "also check the logs")])

    entry = chat_root_send_queue.find(ROOT, "steer-next-cm-steer-gap")
    assert entry is not None, "a steer accepted as the reply finished was dropped"
    assert entry.args["message"] == "also check the logs"
    assert entry.args["session_id"] == ROOT and entry.args["new_session"] is False


def test_a_steer_the_turn_handed_back_is_queued_once(monkeypatch, isolate_agent_runtime_root):
    """The twin: ``pending_steer`` carries it, so ``queue_leftover_steer``'s entry is the only one."""

    pending = PendingSteer.from_text("also check the logs", platform_id="cm-steer-late")
    _a_turn_returns_after_accepting(monkeypatch, [("cm-steer-late", "also check the logs")], pending=pending)

    assert [entry.client_message_id for entry in chat_root_send_queue.entries(ROOT)] == ["steer-next-cm-steer-late"]


def test_a_steer_handed_back_as_plain_text_is_queued_once(monkeypatch, isolate_agent_runtime_root):
    """A hand-back that kept no ids (upstream's plain join) is matched by its text."""

    _a_turn_returns_after_accepting(
        monkeypatch, [("cm-steer-late", "also check the logs")], pending="first thing\nalso check the logs")

    assert [entry.client_message_id for entry in chat_root_send_queue.entries(ROOT)] == ["steer-next-cm-fine"]


def test_a_steer_the_returned_turn_absorbed_is_not_sent_again(monkeypatch, isolate_agent_runtime_root):
    """The twin: its row is in the transcript (the first test proves a real one is found)."""

    monkeypatch.setattr(
        chat_history_writes, "_persona_chat_existing_turn",
        lambda **kwargs: {"operator": {"role": "user"}} if kwargs["client_message_id"] == "cm-steer-absorbed" else {},
    )
    _a_turn_returns_after_accepting(monkeypatch, [("cm-steer-absorbed", "also check the logs")])

    assert not chat_root_send_queue.has_entries(ROOT)
