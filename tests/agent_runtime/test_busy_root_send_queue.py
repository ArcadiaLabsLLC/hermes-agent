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
