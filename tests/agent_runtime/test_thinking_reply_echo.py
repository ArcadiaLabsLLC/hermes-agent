"""A turn with no native reasoning publishes no Thinking row that is only the reply echoed.

Upstream ``agent/turn_response_intake.py::_relay_thinking`` relays the reply text as
``reasoning.available`` when the provider surfaced no reasoning; the profile runner's progress
adapter must not turn that echo into a ``reasoning_summary`` row (live events 18810-18826,
2026-10-06: reasoning_summary == reply on all 5 turns). Native reasoning still publishes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import agent.turn_response_intake as intake
from agent_runtime.profile_runner.progress import _progress_adapter


class _Stop(Exception):
    """Raised right after the thinking relay so the test reads only that step."""


def _drive(monkeypatch, *, content: str, native: str | None) -> list[dict]:
    events: list[dict] = []
    message = SimpleNamespace(content=content, finish_reason="stop", tool_calls=None)
    monkeypatch.setattr(intake, "normalize_response_for_agent", lambda agent, response: message)
    monkeypatch.setattr(intake, "splice_provider_projection", lambda *a, **k: None)
    monkeypatch.setattr(intake, "_fire_post_api_request_hook", lambda *a, **k: None)
    import hermes_cli.observability.shared_metrics_harness as metrics
    monkeypatch.setattr(metrics, "record_reply_content", lambda *a, **k: None)

    def stop(_text):
        raise _Stop

    monkeypatch.setattr(intake, "has_incomplete_scratchpad", stop)
    agent = SimpleNamespace(
        tool_progress_callback=_progress_adapter(events.append, "run.progress"),
        quiet_mode=True, _delegate_depth=0, _extract_reasoning=lambda _message: native,
    )
    with pytest.raises(_Stop):
        intake.normalize_model_response(
            agent, response=object(), messages=[], api_messages=[], conversation_history=[],
            api_call_count=1, api_duration=0.0, api_start_time=0.0, api_request_id=None,
            effective_task_id="t", turn_id="turn")
    return events


def test_a_turn_without_native_reasoning_publishes_no_reply_echo_row(monkeypatch):
    events = _drive(monkeypatch, content="Here is the answer you asked for.", native=None)

    assert [e for e in events if e.get("step") == "reasoning_summary"] == []


def test_native_reasoning_still_publishes_its_row(monkeypatch):
    events = _drive(monkeypatch, content="Here is the answer.", native="Weighing the two options first.")

    rows = [e for e in events if e.get("step") == "reasoning_summary"]
    assert len(rows) == 1
    assert rows[0]["reasoning_summary"] == "Weighing the two options first."


def test_the_echo_marker_is_scoped_to_the_relay():
    from agent_runtime.thinking_echo import begin_reply_echo, end_reply_echo, is_reply_echo

    assert not is_reply_echo()
    token = begin_reply_echo()
    assert is_reply_echo()
    end_reply_echo(token)
    assert not is_reply_echo()
