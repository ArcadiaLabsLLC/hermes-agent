"""A steer the turn finished before absorbing becomes the chat root's next turn.

Owner ruling 2026-10-15 (runtime-queue "Audit delivery of a steer arriving after the
final tool drain"): upstream's finalizer returns undrained input as
``result["pending_steer"]`` and every upstream consumer delivers it as the next user
turn; the Mission Control lane acknowledged it ACCEPTED and dropped it. The handler,
lease, journal and send queue are the production ones; only the provider is stubbed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.steering import PendingSteer, join_pending_steer
from agent_runtime import chat_root_send_queue
from agent_runtime.chat_root_send_runner import RunnerPolicy, run_queued_sends_once
from hermes_cli.harness_parts.persona.chat_turn_commit import run as commit_run
from hermes_cli.harness_parts.persona.chat_turn_commit.leftover_steer import (
    leftover_steer_client_message_id,
)
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT, _args, _install_chat_lane

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _provider(monkeypatch, leftovers: dict[str, object]) -> list[str]:
    calls: list[str] = []

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            calls.append(message)
            raw = {}
            if kwargs.get("client_message_id") in leftovers:
                raw["pending_steer"] = leftovers[kwargs["client_message_id"]]
            return SimpleNamespace(
                final_response="reply", input_tokens=1, output_tokens=2, total_tokens=3, raw=raw,
            )

    monkeypatch.setattr(commit_run, "GPTPersonaRuntime", _Provider)
    return calls


def _door(handler, ran: list[str]):
    def run_turn(args):
        payloads: list[dict] = []
        args.payload_sink = payloads.append
        ran.append(args.client_message_id)
        return handler._cmd_mission_chat_message(args), (payloads[-1] if payloads else None)

    return RunnerPolicy(run_turn=run_turn)


def test_a_leftover_steer_runs_as_the_roots_next_turn(monkeypatch, isolate_agent_runtime_root):
    handler = _install_chat_lane(monkeypatch)
    late = PendingSteer.from_text("also check the logs", platform_id="cm-steer-late")
    calls = _provider(monkeypatch, {"cm-first": late})

    args = _args("cm-first")
    args.message = "do the thing"
    assert handler._cmd_mission_chat_message(args) == 0

    entry = chat_root_send_queue.find(ROOT, "steer-next-cm-steer-late")
    assert entry is not None, "the leftover steer was dropped"
    assert entry.args["message"] == "also check the logs"
    assert entry.args["new_session"] is False and entry.args["session_id"] == ROOT

    ran: list[str] = []
    assert run_queued_sends_once(_door(handler, ran))["ran"] == 1
    assert ran == ["steer-next-cm-steer-late"]
    assert calls == ["do the thing", "also check the logs"]
    assert chat_root_send_queue.find(ROOT, "steer-next-cm-steer-late") is None


def test_a_turn_with_nothing_left_over_queues_nothing(monkeypatch, isolate_agent_runtime_root):
    """Positive control's twin: the same turn, no ``pending_steer``, no queue entry."""

    handler = _install_chat_lane(monkeypatch)
    _provider(monkeypatch, {})

    assert handler._cmd_mission_chat_message(_args("cm-quiet")) == 0
    assert not chat_root_send_queue.has_entries(ROOT)


def test_the_next_turn_id_is_the_first_addressed_inputs_else_the_turns():
    joined = join_pending_steer(
        PendingSteer.from_text("one", platform_id="cm-a"),
        PendingSteer.from_text("two", platform_id="cm-b"),
    )
    assert leftover_steer_client_message_id(joined, "cm-turn") == "steer-next-cm-a"
    assert leftover_steer_client_message_id("plain text", "cm-turn") == "steer-next-cm-turn"
