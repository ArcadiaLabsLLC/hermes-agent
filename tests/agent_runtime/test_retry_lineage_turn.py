"""``retry_of`` through the real chat turn (D2.04 S1 + S3).

A retry names the interrupted turn it re-runs; the turn admits it only when the
target is a reply-less terminal turn (``TERMINAL_TURN_MARKERS``) of the SAME
root, stamps it on its own write-ahead record, and the busy-root queue carries
it to a queued run unchanged. Plan
``docs/agent-runtime-harness/planned/design-sweep-d2-2026-10-10.md`` § D2.04.
"""

from __future__ import annotations

import pytest

from agent_runtime.mission_chat_outcome import ChatErrorKind, ExecutionState
from agent_runtime.mission_chat_turns import mission_chat_turn_record
from agent_runtime.mission_chat_turns.journal import persist_mission_chat_turn
from tests.agent_runtime.test_busy_root_send_queue import _count_provider_calls
from tests.agent_runtime.test_chat_lease_finalization_tail import (
    ROOT,
    _args,
    _envelopes,
    _install_chat_lane,
)

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _seed_target(cmid: str, state: str) -> None:
    persist_mission_chat_turn(
        session_id=ROOT, client_message_id=cmid, turn_id=cmid, elements=[], state=state,
    )


def _retry(handler, cmid: str, retry_of: str, capsys) -> tuple[int, dict]:
    args = _args(cmid)
    args.retry_of = retry_of
    code = handler._cmd_mission_chat_message(args)
    frames = [f for f in _envelopes(capsys) if f.get("capability_id") == "mission.chat.message"]
    return code, frames[-1]


@pytest.mark.parametrize("target_state", ["interrupted", "budget_exhausted"])
def test_a_retry_of_a_reply_less_terminal_turn_runs_and_records_its_origin(
    monkeypatch, capsys, isolate_agent_runtime_root, target_state
):
    handler = _install_chat_lane(monkeypatch)
    calls = _count_provider_calls(monkeypatch)
    _seed_target("cm-orig", target_state)

    code, answer = _retry(handler, "cm-retry", "cm-orig", capsys)

    assert code == 0, answer
    assert len(calls) == 1
    record = mission_chat_turn_record(session_id=ROOT, client_message_id="cm-retry")
    assert record["retry_of"] == "cm-orig"
    assert record["state"] == "projected"
    # The original is terminal and is never written again.
    original = mission_chat_turn_record(session_id=ROOT, client_message_id="cm-orig")
    assert original["state"] == target_state and "retried_as" not in original


@pytest.mark.parametrize(
    "seed_state,retry_of",
    [
        (None, "cm-missing"),            # no such turn in this root
        ("projected", "cm-orig"),        # a completed turn: that is regenerate, not retry
        ("outcome_unknown", "cm-orig"),  # ambiguous: turn-resolve owns it
        ("interrupted", "cm-retry"),     # a turn cannot retry itself
    ],
)
def test_a_retry_naming_anything_else_is_refused_before_the_write_ahead(
    monkeypatch, capsys, isolate_agent_runtime_root, seed_state, retry_of
):
    handler = _install_chat_lane(monkeypatch)
    calls = _count_provider_calls(monkeypatch)
    if seed_state is not None:
        _seed_target("cm-orig", seed_state)

    code, answer = _retry(handler, "cm-retry", retry_of, capsys)

    assert code == 2
    assert answer["execution_state"] == ExecutionState.REJECTED
    assert answer["error_kind"] == ChatErrorKind.CHAT_TURN_RETRY_TARGET_INVALID
    assert answer["retry_of"] == retry_of
    assert calls == []
    assert mission_chat_turn_record(session_id=ROOT, client_message_id="cm-retry") is None
