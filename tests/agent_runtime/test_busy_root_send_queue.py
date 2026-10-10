"""A send to a busy chat root is accepted and queued, never refused ``chat_busy``.

Owner ruling 2026-10-10 (``docs/agent-runtime-harness/planned/busy-root-queue-2026-10-10.md``):
the operator's message is persisted, answered "queued", run after the current turn
in arrival order, and its settle is recorded when it RUNS — so first-settle-wins
(``chat_turn_settles.record_settle``) stays correct. The lease, the handler and the
journal are the production ones (the ``test_chat_lease_finalization_tail`` rig);
only the provider is stubbed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue, chat_turn_settles
from agent_runtime.chat_root_send_runner import RunnerPolicy, run_queued_sends_once
from agent_runtime.persona_chat_continuity import persona_chat_root_lease
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run
from tests.agent_runtime.test_chat_lease_finalization_tail import (
    ROOT,
    _args,
    _envelopes,
    _install_chat_lane,
)

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _count_provider_calls(monkeypatch) -> list[str]:
    calls: list[str] = []

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            calls.append(message)
            return SimpleNamespace(
                final_response="the queued reply", input_tokens=1, output_tokens=2,
                total_tokens=3, raw={},
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    return calls


def _door(handler, ran: list[str]):
    """The mission-chat door's contract: run in-process, take the payload off the sink."""

    def run_turn(args):
        payloads: list[dict] = []
        args.payload_sink = payloads.append
        ran.append(args.client_message_id)
        return handler._cmd_mission_chat_message(args), (payloads[-1] if payloads else None)

    return RunnerPolicy(run_turn=run_turn)


def _send(handler, cmid: str, capsys, *, message: str = "please answer") -> tuple[int, dict]:
    args = _args(cmid)
    args.message = message
    code = handler._cmd_mission_chat_message(args)
    frames = [f for f in _envelopes(capsys) if f.get("capability_id") == "mission.chat.message"]
    return code, frames[-1]


def test_a_busy_root_queues_the_send_then_runs_and_settles_it(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    handler = _install_chat_lane(monkeypatch)
    calls = _count_provider_calls(monkeypatch)
    ran: list[str] = []

    with persona_chat_root_lease(ROOT, owner_id="held-by-the-test", observer_kind="cli"):
        code, answer = _send(handler, "cm-busy-1", capsys)
        assert run_queued_sends_once(_door(handler, ran))["busy"] == 1, "ran under a held lease"

    assert code == 0, answer
    assert answer["queued"] is True and answer["ok"] is True
    assert "error_kind" not in answer, f"a queued send must not carry a refusal: {answer}"
    assert answer["execution_state"] == "accepted"
    assert answer["queue_position"] == 1
    assert answer["client_message_id"] == "cm-busy-1"
    assert answer["root_chat_session_id"] == ROOT
    # The "queued" answer is not the turn's settle: recording it would make it the
    # first settle and swallow the real one.
    # The serve worker's ``finally`` records a settle from this very answer.
    assert chat_turn_settles.record_settle(
        client_message_id="cm-busy-1", session_id=ROOT, request_id="serve-rid",
        exit_code=code, outcome=chat_turn_settles.outcome_from_payload(answer),
    ) is None
    assert calls == []

    tally = run_queued_sends_once(_door(handler, ran))

    assert tally["ran"] == 1, tally
    assert ran == ["cm-busy-1"] and len(calls) == 1
    assert chat_root_send_queue.find(ROOT, "cm-busy-1") is None, "the entry outlived its turn"
    settles = [s for s in chat_turn_settles.list_settles() if s.client_message_id == "cm-busy-1"]
    assert len(settles) == 1, settles
    assert settles[0].exit_code == 0 and settles[0].refusal_class is None
    assert settles[0].session_id == ROOT
    assert settles[0].request_id == "queued:cm-busy-1"
    assert settles[0].state == chat_turn_settles.STATE_PENDING


def test_a_queued_send_survives_a_restart_and_still_runs(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    handler = _install_chat_lane(monkeypatch)
    calls = _count_provider_calls(monkeypatch)

    with persona_chat_root_lease(ROOT, observer_kind="cli"):
        _send(handler, "cm-restart", capsys)
    # The serve that queued it died mid-run: the entry is on disk, marked running.
    chat_root_send_queue.mark(ROOT, "cm-restart", state=chat_root_send_queue.STATE_RUNNING)

    # A fresh runner (nothing in memory, only the store) picks it up.
    ran: list[str] = []
    assert run_queued_sends_once(_door(handler, ran))["ran"] == 1
    assert ran == ["cm-restart"] and len(calls) == 1
    assert not chat_root_send_queue.has_entries(ROOT)


def test_the_same_client_message_id_twice_while_queued_is_one_turn(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    handler = _install_chat_lane(monkeypatch)
    calls = _count_provider_calls(monkeypatch)

    with persona_chat_root_lease(ROOT, observer_kind="cli"):
        _, first = _send(handler, "cm-twice", capsys)
        _, second = _send(handler, "cm-twice", capsys)
    # Lease free now, but the id is still waiting: the gate answers from its entry.
    code, third = _send(handler, "cm-twice", capsys)

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True and third["idempotent_replay"] is True
    assert code == 0 and third["queued"] is True
    assert first["queued_at"] == second["queued_at"] == third["queued_at"]
    assert len(chat_root_send_queue._entries(ROOT)) == 1
    assert calls == [], "a re-presented queued id ran a turn of its own"

    ran: list[str] = []
    run_queued_sends_once(_door(handler, ran))
    run_queued_sends_once(_door(handler, ran))
    assert ran == ["cm-twice"] and len(calls) == 1


def test_queued_sends_run_in_arrival_order_even_when_the_lease_frees_between(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    handler = _install_chat_lane(monkeypatch)
    calls = _count_provider_calls(monkeypatch)

    with persona_chat_root_lease(ROOT, observer_kind="cli"):
        _, a = _send(handler, "cm-a", capsys, message="first")
        _, b = _send(handler, "cm-b", capsys, message="second")
    # The lease is free, but two sends are waiting: a third must not overtake them.
    code, c = _send(handler, "cm-c", capsys, message="third")

    assert (a["queue_position"], b["queue_position"], c["queue_position"]) == (1, 2, 3)
    assert code == 0 and c["queued"] is True and calls == []

    ran: list[str] = []
    for _ in range(3):
        run_queued_sends_once(_door(handler, ran))
    assert ran == ["cm-a", "cm-b", "cm-c"]
    assert calls == ["first", "second", "third"]


def test_a_relay_send_to_a_busy_root_keeps_its_chat_busy_refusal():
    """Agent relays and delivery forges name their sender's root; both retry from
    a queue of their own (``dispatch_store``) or need the reply in the calling
    turn, so ``chat_busy`` keeps its meaning there."""

    from hermes_cli.harness_parts.persona.chat_send_queue import _busy_root_queues

    assert _busy_root_queues(SimpleNamespace(requested_by_session=None)) is True
    assert _busy_root_queues(SimpleNamespace()) is True
    assert _busy_root_queues(SimpleNamespace(requested_by_session="persona_chat_sender")) is False


# --------------------------------------------------------------------------- #
# A queued turn streams like a sent one, and roots never wait on each other    #
# --------------------------------------------------------------------------- #


class _Frames:
    detached = False

    def __init__(self) -> None:
        self.frames: list[dict] = []

    def emit(self, frame: dict) -> None:
        self.frames.append(frame)


class _Socket:
    def __init__(self) -> None:
        self.frames: list[dict] = []

    def broadcast(self, frame: dict) -> int:
        self.frames.append(frame)
        return 1


def _serve_session():
    import threading

    from hermes_cli.harness_parts.serve.frames import _LineFrameProxy
    from hermes_cli.harness_parts.serve.settle_push import SettlePush

    class _Session(SettlePush):
        pass

    session = _Session()
    session.service = False
    session.frames = _Frames()
    session.lane_lock = threading.Lock()
    session.socket_server = _Socket()
    session.stdout_proxy = _LineFrameProxy(session.frames, "line")
    session.stderr_proxy = _LineFrameProxy(session.frames, "stderr")
    return session


def _frame_types(lines) -> list[str]:
    import json

    types = []
    for line in lines:
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("type"):
            types.append(value["type"])
    return types


def test_a_queued_turn_streams_the_same_frames_a_sent_turn_does_to_a_subscriber(
    monkeypatch, capsys, isolate_agent_runtime_root
):
    import dataclasses
    import sys

    from hermes_cli.harness_parts.serve.queued_turns import queued_turn_runner_policy

    handler = _install_chat_lane(monkeypatch)
    _count_provider_calls(monkeypatch)

    # The reference: the same turn sent directly, streamed.
    direct = _args("cm-direct")
    direct.stream = True
    assert handler._cmd_mission_chat_message(direct) == 0
    direct_types = _frame_types(capsys.readouterr().out.splitlines())
    assert "chat.final" in direct_types and len(direct_types) > 1, direct_types

    with persona_chat_root_lease(ROOT, observer_kind="cli"):
        _send(handler, "cm-stream", capsys)

    session = _serve_session()
    ran: list[str] = []
    policy = dataclasses.replace(
        queued_turn_runner_policy(session), run_turn=_door(handler, ran).run_turn
    )
    with pytest.MonkeyPatch.context() as patched:
        # The serve's stdout IS the line proxy; the turn's prints reach the sink through it.
        patched.setattr(sys, "stdout", session.stdout_proxy)
        assert run_queued_sends_once(policy)["ran"] == 1

    subscriber = session.socket_server.frames
    assert subscriber, "no frame of the queued turn reached a stream subscriber"
    assert {frame["id"] for frame in subscriber} == {"queued:cm-stream"}
    lines = [frame["line"] for frame in subscriber if frame.get("event") == "line"]
    assert _frame_types(lines) == direct_types, (
        "a queued turn must stream exactly the frames a directly sent turn does"
    )
    assert subscriber[-1] == {"id": "queued:cm-stream", "event": "exit", "code": 0}
    # The stdio writer (a launcher reading the pipe) got the same stream.
    assert session.frames.frames == subscriber


def test_a_blocked_turn_on_one_root_does_not_hold_a_queued_send_on_another(
    isolate_agent_runtime_root,
):
    import threading

    from agent_runtime.chat_root_send_runner import QueuedSendRunner

    root_a, root_b = "persona_chat_root_a", "persona_chat_root_b"
    chat_root_send_queue.enqueue(root_a, "cm-a1", {})
    chat_root_send_queue.enqueue(root_b, "cm-b1", {})
    chat_root_send_queue.enqueue(root_a, "cm-a2", {})
    a_started, release_a, b_done = threading.Event(), threading.Event(), threading.Event()
    ran: list[str] = []

    def run_turn(args):
        ran.append(args.client_message_id)
        if args.client_message_id == "cm-a1":
            a_started.set()
            assert release_a.wait(10)
        if args.client_message_id == "cm-b1":
            b_done.set()
        return 0, {"ok": True}

    runner = QueuedSendRunner(RunnerPolicy(root_is_idle=lambda root: True, run_turn=run_turn))
    try:
        runner.dispatch_once()
        assert a_started.wait(5)
        assert b_done.wait(5), "root B's queued send waited behind root A's running turn"
        # Root A is still running cm-a1: its next send must wait for it, in order.
        tally = runner.dispatch_once()
        assert tally["occupied"] == 1 and tally["dispatched"] == 0, tally
        assert "cm-a2" not in ran
        release_a.set()
        for _ in range(100):
            if root_a not in runner.busy_roots():
                break
            threading.Event().wait(0.05)
        runner.dispatch_once()
    finally:
        release_a.set()
        runner.shutdown(wait=True)
    assert [cmid for cmid in ran if cmid.startswith("cm-a")] == ["cm-a1", "cm-a2"]
    assert not chat_root_send_queue.has_entries(root_a)
    assert not chat_root_send_queue.has_entries(root_b)
