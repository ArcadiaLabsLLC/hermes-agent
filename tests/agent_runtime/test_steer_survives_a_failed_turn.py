"""A message sent to steer a running reply is not lost when that reply fails.

RT-STEER-LOST-WHEN-TURN-FAILS. The steer watcher acknowledges a steer ACCEPTED once the
agent's ``steer()`` took it, and the agent holds it only in memory. A run that returns hands
the undrained part back (``pending_steer``, ``test_leftover_steer_next_turn``); a run that
raises, or that the hard wall ends, hands back nothing, and the operator's accepted message
was gone. The watcher now keeps an on-disk ledger of what it accepted and the turn's settle
re-delivers what never reached the transcript as the root's next turn.

The handler, lease, journal, steer watcher and send queue are the production ones; only the
provider is stubbed, and it steers itself mid-run through the real submit door.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

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


class _Agent:
    def steer(self, text) -> bool:
        return True


def _steer(turn_id: str, steer_id: str, text: str, *, notification: bool = False) -> None:
    """One steer through the real door, accepted by a live watcher bound to ``turn_id``."""

    handle = start_active_mission_chat_turn(
        runtime_root=paths.store_root(), session_id=ROOT, agent=_Agent(), client_message_id=turn_id)
    try:
        ack = submit_mission_chat_steer(
            runtime_root=paths.store_root(), session_id=ROOT, message=text,
            client_message_id=steer_id, notification=notification)
    finally:
        handle.close()
    assert ack["ok"] is True and ack["execution_state"] == "accepted"


def _provider(monkeypatch, *, steers: dict[str, list[tuple]], fails: set[str]) -> None:
    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            turn_id = kwargs["client_message_id"]
            for steer in steers.get(turn_id, []):
                _steer(turn_id, *steer)
            if turn_id in fails:
                raise RuntimeError("the provider connection died")
            return SimpleNamespace(final_response="reply", input_tokens=1, output_tokens=2, total_tokens=3, raw={})

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)


def test_a_steer_accepted_by_a_turn_that_fails_becomes_the_next_turn(monkeypatch, isolate_agent_runtime_root):
    handler = _install_chat_lane(monkeypatch)
    _provider(monkeypatch, steers={"cm-fails": [("cm-steer-1", "also check the logs")]}, fails={"cm-fails"})

    assert handler._cmd_mission_chat_message(_args("cm-fails")) != 0

    entry = chat_root_send_queue.find(ROOT, "steer-next-cm-steer-1")
    assert entry is not None, "the accepted steer was lost with the failed turn"
    assert entry.args["message"] == "also check the logs"
    assert entry.args["session_id"] == ROOT and entry.args["new_session"] is False
    assert take_accepted_steers(runtime_root=paths.store_root(), session_id=ROOT) == []


def test_a_steer_the_transcript_already_holds_is_not_sent_twice(monkeypatch, isolate_agent_runtime_root):
    handler = _install_chat_lane(monkeypatch)
    _provider(monkeypatch, steers={"cm-fails": [("cm-steer-1", "also check the logs")]}, fails={"cm-fails"})
    monkeypatch.setattr(
        chat_history_writes, "_persona_chat_existing_turn",
        lambda **kwargs: {"operator": {"role": "user"}} if kwargs["client_message_id"] == "cm-steer-1" else {},
    )

    assert handler._cmd_mission_chat_message(_args("cm-fails")) != 0
    assert chat_root_send_queue.find(ROOT, "steer-next-cm-steer-1") is None


def test_a_turn_that_returns_owes_its_own_steers_nothing_more(monkeypatch, isolate_agent_runtime_root):
    """The twin: the run returned, so its steers were drained or handed back; none is re-sent."""

    handler = _install_chat_lane(monkeypatch)
    _provider(monkeypatch, steers={"cm-fine": [("cm-steer-1", "also check the logs")]}, fails=set())

    assert handler._cmd_mission_chat_message(_args("cm-fine")) == 0
    assert not chat_root_send_queue.has_entries(ROOT)
    assert take_accepted_steers(runtime_root=paths.store_root(), session_id=ROOT) == []


def test_a_dead_turns_steer_is_delivered_after_the_next_turn(monkeypatch, isolate_agent_runtime_root):
    """An executor that died left its ledger behind; the root's next settle re-delivers it."""

    handler = _install_chat_lane(monkeypatch)
    _provider(monkeypatch, steers={}, fails=set())
    _steer("cm-dead", "cm-steer-orphan", "this was typed before the crash")
    _steer("cm-dead", "cm-notice", "process 12 exited", notification=True)

    assert handler._cmd_mission_chat_message(_args("cm-after")) == 0
    entry = chat_root_send_queue.find(ROOT, "steer-next-cm-steer-orphan")
    assert entry is not None and entry.args["message"] == "this was typed before the crash"
    assert chat_root_send_queue.find(ROOT, "steer-next-cm-notice") is None, "a process notice was sent as operator input"


def test_a_turn_that_is_not_streaming_to_a_screen_still_takes_a_steer(monkeypatch, isolate_agent_runtime_root):
    """RT-STEER-ONLY-STREAMING-TURNS: a forged or Work turn (``stream=False``) registers the steer
    watcher too, so a steer sent while it runs is ACCEPTED into it instead of refused ``no_active_turn``."""

    handler = _install_chat_lane(monkeypatch)
    acks: list[dict] = []

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            close = kwargs["agent_ready_callback"](_Agent())
            try:
                acks.append(submit_mission_chat_steer(
                    runtime_root=paths.store_root(), session_id=ROOT, message="look at the logs too",
                    client_message_id="cm-steer-quiet"))
            finally:
                if callable(close):
                    close()
            return SimpleNamespace(final_response="reply", input_tokens=1, output_tokens=2, total_tokens=3, raw={})

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    args = _args("cm-quiet")
    assert not getattr(args, "stream", False)

    assert handler._cmd_mission_chat_message(args) == 0
    assert acks and acks[0]["ok"] is True and acks[0]["execution_state"] == "accepted", acks
