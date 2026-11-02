"""RT-MC-TURN-READS-UNATTENDED: a Mission Control chat turn a person asked for reads as attended.

The chat lane's agent runs with ``platform="tool"`` and no session source, so upstream's
``is_attended`` answered False for every console turn and the free tier's
``free_tier_cooldown_ends_turn`` never fired there. The lane now binds the turn's attendance from
``requested_by`` (``agent_runtime.turn_attendance``) and ``is_attended`` reads it through one seam.

KILLING MUTATION: drop the ``attended_override()`` seam from ``agent.session_source.is_attended``
-> ``test_a_console_turn_is_attended_and_ends_a_long_free_tier_cooldown`` red.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.session_source import is_attended
from agent_runtime.persona_runtime import PERSONA_CHAT_SCRATCH_SOURCE
from agent_runtime.turn_attendance import attended_for_requester, attended_override, attended_turn
from tests.hermes_cli.test_mission_chat_turn_phases import isolate_agent_runtime_root  # noqa: F401  (fixture)


@pytest.mark.parametrize("requested_by", ["launcher", "operator", "cli", "dev_0a1b2c3d4e5f6071"])
def test_a_person_origin_is_attended(requested_by):
    assert attended_for_requester(requested_by) is True


@pytest.mark.parametrize("requested_by", [
    "agent:persona_chat_x", "harness-delivery:d1:1", "lens-episode:e1:m1", "work:r1", "schedule:r1",
    "messaging:telegram:42", "discussion:run1", "coordinator:boss", "", "  ", None,
])
def test_a_machine_origin_or_none_is_unattended(requested_by):
    assert attended_for_requester(requested_by) is False


def _chat_agent(platform: str = PERSONA_CHAT_SCRATCH_SOURCE):
    return SimpleNamespace(platform=platform)


def test_a_console_turn_is_attended_and_ends_a_long_free_tier_cooldown(monkeypatch):
    from agent import retry_utils, turn_recovery
    from hermes_cli import anon_auth

    monkeypatch.delenv("HERMES_SESSION_SOURCE", raising=False)
    monkeypatch.setattr(anon_auth, "on_free_model", lambda agent, base_url: True)
    monkeypatch.setattr(retry_utils, "provider_retry_after_seconds", lambda error: 1069.0)
    agent = _chat_agent()
    # POSITIVE CONTROL: outside a bound turn the chat lane's agent is unattended, as before.
    assert attended_override() is None
    assert is_attended(agent) is False
    assert turn_recovery.free_tier_cooldown_ends_turn(agent, RuntimeError("429"), "x") is False
    with attended_turn(attended_for_requester("launcher")):
        assert is_attended(agent) is True
        assert turn_recovery.free_tier_cooldown_ends_turn(agent, RuntimeError("429"), "x") is True
    with attended_turn(attended_for_requester("agent:persona_chat_x")):
        assert is_attended(agent) is False
    assert attended_override() is None, "the binding ends with the turn"


def test_a_delegated_child_stays_unattended_inside_a_console_turn():
    with attended_turn(True):
        assert is_attended(_chat_agent("subagent")) is False
        assert is_attended(SimpleNamespace(platform=None)) is False


def test_the_chat_lane_hands_the_requester_down(monkeypatch, capsys, isolate_agent_runtime_root):
    """``mission-chat message`` passes ``attended`` from ``--requested-by`` to the runtime."""

    from hermes_cli.harness_parts.persona import chat_turn_message
    from tests.hermes_cli.test_mission_chat_budget_payload import _seed  # type: ignore
    from tests.hermes_cli.test_mission_chat_turn_phases import _args  # type: ignore

    seen: list = []

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, persona, message, *args, **kwargs):
            seen.append(kwargs.get("attended"))
            return SimpleNamespace(final_response="ok", input_tokens=1, output_tokens=1, total_tokens=2,
                                   latency_ms=1, profile_timing={}, raw={}, turn_outcome=None)

    _seed(monkeypatch, _Provider)
    for turn, requester in (("att_console", "launcher"), ("att_relay", "work:r1")):
        args = _args(turn, stream=False)
        args.requested_by = requester
        assert chat_turn_message._cmd_mission_chat_message(args) == 0
    assert seen == [True, False]
