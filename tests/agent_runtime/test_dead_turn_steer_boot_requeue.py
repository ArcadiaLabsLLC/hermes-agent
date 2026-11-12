"""A steer typed just before the runtime died is delivered when the runtime comes back.

RT-DEAD-TURN-STEER-WAITS-FOR-NEXT-TURN. An accepted steer is kept on disk
(``test_steer_survives_a_failed_turn``), and a dead turn's record used to be re-delivered only
by the root's NEXT settle — after the operator sent something else. The steer watcher now keeps
the turn's own send beside the ledger (``active.json`` ``send_args``), and the serve boot queues
each record of a root whose lease is free as that root's next turn.

The handler, lease, steer watcher, ledger and send queue are the production ones; the provider
is stubbed, and the executor's death is a turn whose settle never ran.
"""

from __future__ import annotations

import pytest

from agent_runtime import chat_root_send_queue, paths
from agent_runtime.mission_chat_steer import roots_owing_steers, submit_mission_chat_steer, take_accepted_steers
from agent_runtime.persona_chat_continuity import persona_chat_root_lease
from hermes_cli.harness_parts.persona import chat_history_writes
from hermes_cli.harness_parts.persona.chat_turn_commit import TurnCommit, run as commit_run
from hermes_cli.harness_parts.persona.chat_turn_commit.leftover_steer import requeue_dead_turn_steers
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT, _install_chat_lane
from tests.agent_runtime.test_persona_assignments_chat_history import _mission_chat_test_args

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _args(client_message_id: str):
    """A send streaming to a screen: the only kind of turn that registers the steer watcher."""

    return _mission_chat_test_args(client_message_id, stream=True)


class _Agent:
    def steer(self, text) -> bool:
        return True


def _a_turn_dies_holding_a_steer(monkeypatch, *, notification: bool = False):
    """Run ``cm-dead`` through the real handler; it accepts ``cm-steer-orphan`` and never settles."""

    handler = _install_chat_lane(monkeypatch)

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            kwargs["agent_ready_callback"](_Agent())  # never closed: the process died
            ack = submit_mission_chat_steer(
                runtime_root=paths.store_root(), session_id=ROOT, message="this was typed before the crash",
                client_message_id="cm-steer-orphan", notification=notification)
            assert ack["ok"] is True and ack["execution_state"] == "accepted", ack
            raise RuntimeError("the process was killed here")

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    # A dead executor runs no settle: nothing reads its ledger.
    monkeypatch.setattr(TurnCommit, "_queue_leftover_steer", lambda self, **kwargs: None)
    assert handler._cmd_mission_chat_message(_args("cm-dead")) != 0
    assert not chat_root_send_queue.has_entries(ROOT)
    return handler


def test_the_boot_queues_a_dead_turns_steer_as_the_roots_next_turn(monkeypatch, isolate_agent_runtime_root):
    _a_turn_dies_holding_a_steer(monkeypatch)

    assert requeue_dead_turn_steers() == ["steer-next-cm-steer-orphan"]

    entry = chat_root_send_queue.find(ROOT, "steer-next-cm-steer-orphan")
    assert entry is not None, "the dead turn's steer still waits for the operator's next send"
    assert entry.args["message"] == "this was typed before the crash"
    assert entry.args["session_id"] == ROOT and entry.args["new_session"] is False
    # The queued turn is the dead turn's own send with the steer's text: same agent, same door.
    original = chat_root_send_queue.persistable_args(_args("cm-dead"))
    for name in ("persona_id", "persona_instance_id"):
        assert entry.args[name] == original[name], name
    assert chat_root_send_queue.ORIGIN_ARG in entry.args
    assert take_accepted_steers(runtime_root=paths.store_root(), session_id=ROOT) == []
    assert requeue_dead_turn_steers() == [], "a second boot queued the same steer again"


def test_a_root_whose_turn_is_still_running_keeps_its_ledger(monkeypatch, isolate_agent_runtime_root):
    """The twin: a held lease is a live turn, which settles its own ledger."""

    _a_turn_dies_holding_a_steer(monkeypatch)

    with persona_chat_root_lease(ROOT):
        assert requeue_dead_turn_steers() == []

    assert not chat_root_send_queue.has_entries(ROOT)
    assert [item["session_id"] for item in roots_owing_steers(runtime_root=paths.store_root())] == [ROOT]


def test_the_boot_does_not_resend_what_the_transcript_holds_or_a_process_notice(
        monkeypatch, isolate_agent_runtime_root):
    _a_turn_dies_holding_a_steer(monkeypatch)
    monkeypatch.setattr(
        chat_history_writes, "_persona_chat_existing_turn",
        lambda **kwargs: {"operator": {"role": "user"}} if kwargs["client_message_id"] == "cm-steer-orphan" else {},
    )
    assert requeue_dead_turn_steers() == []
    assert not chat_root_send_queue.has_entries(ROOT)


def test_a_dead_turns_process_notice_is_not_sent_as_operator_input(monkeypatch, isolate_agent_runtime_root):
    _a_turn_dies_holding_a_steer(monkeypatch, notification=True)

    assert requeue_dead_turn_steers() == []
    assert not chat_root_send_queue.has_entries(ROOT)


def test_serve_boot_runs_the_dead_turn_steer_sweep(monkeypatch, isolate_agent_runtime_root):
    """The boot phase that repairs orphaned turns also queues their steers."""

    import inspect

    from hermes_cli.harness_parts.serve import boot_phases

    source = inspect.getsource(boot_phases)
    sweep = source.index("repair_orphaned_chat_turns()")
    mark = source.index('self.timeline.mark("orphaned_turn_sweep_ms")')
    assert "requeue_dead_turn_steers()" in source[sweep:mark]
