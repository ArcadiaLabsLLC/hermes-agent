"""RT-QA-TURN-LIMIT-OVERRIDES: QA-only per-turn limit overrides, honoured only under a QA provider pool.

The policy (``agent_runtime.qa_turn_overrides``), its three effects (an early wall-budget checkpoint,
a tool-iteration limit, a silence before the first provider call), and the mission-chat admission
that refuses any of them outside a QA namespace under a QA pool before anything runs.
"""

from __future__ import annotations

import time
from threading import Event
from types import SimpleNamespace

import pytest

from agent_runtime import qa_turn_overrides as qa
from agent_runtime.mission_chat_outcome import ChatErrorKind, ExecutionState
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from agent_runtime.persona_runtime import _qa_request_fields
from agent_runtime.profile_runner.execute import _qa_silence
from agent_runtime.profile_runner.models import AgentRunRequest
from agent_runtime.turn_budget import TurnBudgetPhase, TurnWallBudget
from hermes_cli import _namespace_bootstrap as bootstrap
from hermes_cli.harness_parts.persona import chat_turn_commit as commit
from hermes_cli.harness_parts.persona.chat_serve_route import send_argv
from tests.agent_runtime.test_chat_lease_finalization_tail import ROOT, _args, _envelopes, _install_chat_lane

QA_POOL = {"HERMES_NAMESPACE": "stagec-lane-a", qa.QA_POOL_ENV: "stagec-pool"}


def test_the_spelled_constants_are_the_bootstraps():
    assert qa.QA_POOL_ENV == bootstrap.QA_POOL_ENV
    assert qa.QA_PREFIX == bootstrap.QA_PREFIX


@pytest.mark.parametrize("env", [
    {},                                                    # the owner's base home
    {"HERMES_NAMESPACE": "account-owner"},                 # an account namespace
    {"HERMES_NAMESPACE": "stagec-lane-a"},                 # QA, but no provider pool
    {"HERMES_NAMESPACE": "neko", qa.QA_POOL_ENV: "stagec-pool"},  # a pool env outside QA
])
def test_outside_a_qa_pool_is_refused(env):
    with pytest.raises(qa.QaTurnOverridesRefused) as caught:
        qa.qa_turn_overrides(max_iterations=1, env=env)
    assert caught.value.error_kind == qa.REFUSED


def test_no_override_is_none_anywhere():
    assert qa.qa_turn_overrides(env={}) is None
    assert qa.qa_turn_overrides(env=QA_POOL) is None


def test_a_qa_pool_admits_bounded_overrides():
    got = qa.qa_turn_overrides(checkpoint_after_seconds=2, max_iterations=1, silence_seconds=70, env=QA_POOL)
    assert got == qa.QaTurnOverrides(2.0, 1, 70.0)
    assert got.as_dict() == {"checkpoint_after_seconds": 2.0, "max_iterations": 1, "silence_seconds": 70.0}


@pytest.mark.parametrize("kwargs", [
    {"checkpoint_after_seconds": 0.5}, {"checkpoint_after_seconds": 601}, {"checkpoint_after_seconds": True},
    {"max_iterations": 0}, {"max_iterations": 91}, {"max_iterations": 1.5},
    {"silence_seconds": -1}, {"silence_seconds": 301}, {"silence_seconds": float("nan")},
])
def test_an_out_of_bounds_override_is_invalid(kwargs):
    with pytest.raises(qa.QaTurnOverridesRefused) as caught:
        qa.qa_turn_overrides(env=QA_POOL, **kwargs)
    assert caught.value.error_kind == qa.INVALID


def test_the_early_checkpoint_opens_where_asked_and_the_hard_wall_keeps_the_budget():
    now = 1_000.0
    early = TurnWallBudget(total_seconds=240.0, deadline_epoch=now + 240.0, checkpoint_after_seconds=2.0)
    assert early.seconds_until_checkpoint(now=now) == pytest.approx(2.0)
    assert early.phase(now=now + 1.0) is TurnBudgetPhase.NORMAL
    assert early.phase(now=now + 3.0) is TurnBudgetPhase.CHECKPOINT
    assert early.remaining_seconds(now=now) == pytest.approx(240.0)
    # A real turn: the reserve rule, unchanged.
    real = TurnWallBudget(total_seconds=240.0, deadline_epoch=now + 240.0)
    assert real.seconds_until_checkpoint(now=now) == pytest.approx(180.0)
    # An override past the budget's end changes nothing.
    late = TurnWallBudget(total_seconds=240.0, deadline_epoch=now + 240.0, checkpoint_after_seconds=500.0)
    assert late.seconds_until_checkpoint(now=now) == pytest.approx(180.0)


def test_the_overrides_reach_the_runner_request():
    fields = _qa_request_fields(qa.QaTurnOverrides(2.0, 1, 70.0))
    request = AgentRunRequest(profile="p", **fields)
    assert (request.max_iterations, request.qa_checkpoint_after_seconds, request.qa_silence_seconds) == (1, 2.0, 70.0)
    assert _qa_request_fields(None) == {}
    plain = AgentRunRequest(profile="p", **_qa_request_fields(qa.QaTurnOverrides(silence_seconds=1.0)))
    assert plain.max_iterations == 90


def test_the_silence_waits_and_the_hard_wall_cuts_it_short():
    request = SimpleNamespace(qa_silence_seconds=0.3)
    started = time.monotonic()
    _qa_silence(request, None)
    assert time.monotonic() - started >= 0.29
    expired = Event()
    expired.set()
    started = time.monotonic()
    _qa_silence(request, expired)
    assert time.monotonic() - started < 0.2
    _qa_silence(SimpleNamespace(qa_silence_seconds=None), None)


def test_the_serve_route_forwards_the_flags():
    args = SimpleNamespace(qa_checkpoint_after_seconds=2.0, qa_max_iterations=1, qa_silence_seconds=None)
    argv = send_argv(args)
    assert "--qa-checkpoint-after-seconds=2.0" in argv and "--qa-max-iterations=1" in argv
    assert not any(item.startswith("--qa-silence-seconds") for item in argv)


def _send(handler, capsys, **overrides):
    args = _args("cm-qa")
    for key, value in overrides.items():
        setattr(args, key, value)
    code = handler._cmd_mission_chat_message(args)
    frames = [f for f in _envelopes(capsys) if f.get("capability_id") == "mission.chat.message"]
    return code, frames[-1]


def _capture_replies(monkeypatch) -> list[dict]:
    seen: list[dict] = []

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(final_response="ok", input_tokens=1, output_tokens=1, total_tokens=2, raw={})

    monkeypatch.setattr(commit.run, "GPTPersonaRuntime", _Provider)
    return seen


@pytest.mark.usefixtures("persisted_persona_samples")
def test_a_send_outside_a_qa_pool_is_refused_before_the_write_ahead(monkeypatch, capsys, isolate_agent_runtime_root):
    monkeypatch.delenv("HERMES_NAMESPACE", raising=False)
    monkeypatch.delenv(qa.QA_POOL_ENV, raising=False)
    handler = _install_chat_lane(monkeypatch)
    seen = _capture_replies(monkeypatch)

    code, answer = _send(handler, capsys, qa_max_iterations=1)

    assert code == 2
    assert answer["execution_state"] == ExecutionState.REJECTED
    assert answer["error_kind"] == ChatErrorKind.QA_TURN_OVERRIDES_REFUSED
    assert seen == []
    assert mission_chat_turn_record(session_id=ROOT, client_message_id="cm-qa") is None


@pytest.mark.usefixtures("persisted_persona_samples")
def test_a_qa_pool_send_carries_its_overrides_to_the_reply(monkeypatch, capsys, isolate_agent_runtime_root):
    handler = _install_chat_lane(monkeypatch)
    seen = _capture_replies(monkeypatch)
    # A real QA namespace re-roots the store (namespace isolation); the admission is proved above on env.
    monkeypatch.setattr(qa, "qa_turn_overrides_admitted", lambda env=None: True)

    code, answer = _send(handler, capsys, qa_max_iterations=1, qa_checkpoint_after_seconds=2.0)

    assert code == 0, answer
    assert seen[-1]["qa_turn_overrides"] == qa.QaTurnOverrides(2.0, 1, None)


@pytest.mark.usefixtures("persisted_persona_samples")
def test_a_plain_send_carries_no_overrides(monkeypatch, capsys, isolate_agent_runtime_root):
    handler = _install_chat_lane(monkeypatch)
    seen = _capture_replies(monkeypatch)

    code, answer = _send(handler, capsys)

    assert code == 0, answer
    assert seen[-1]["qa_turn_overrides"] is None
