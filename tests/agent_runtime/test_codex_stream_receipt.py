"""The provider stream receipt, written from upstream's stream observer hooks (plugin-fit PF-3)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import codex_observability as receipt
from agent_runtime.persona_turn_binding import bind_persona_turn_agent


@pytest.fixture(autouse=True)
def _clean():
    receipt.reset_for_tests()
    yield
    receipt.reset_for_tests()


class _Agent(SimpleNamespace):
    """Weak-referenceable, as ``AIAgent`` is."""


def _agent(events, session_id="s1"):
    return _Agent(session_id=session_id, provider="openai-codex", model="gpt-test",
                  api_mode="codex_responses", status_callback=events.append)


def _by_step(events):
    return {event["step"]: event for event in events}


def test_start_delta_end_write_first_delta_and_consume():
    events: list = []
    agent = _agent(events)
    with bind_persona_turn_agent(agent):
        receipt.remember_stream_agent()
    ids = {"session_id": "s1", "turn_id": "t1", "iteration": 1}
    receipt.on_stream_start(**ids)
    receipt.on_stream_delta(**ids, delta="hel", kind="text")
    receipt.on_stream_delta(**ids, delta="why", kind="reasoning")
    receipt.on_stream_delta(**ids, delta="lo", kind="text")
    receipt.on_stream_end(**ids, final_text="hello", finished=True, error=None)

    steps = _by_step(events)
    assert set(steps) == {"provider_stream_first_delta", "provider_stream_consume"}
    consume = steps["provider_stream_consume"]
    assert consume["timing_key"] == "provider_stream_consume_ms"
    assert consume["status"] == "completed"
    assert consume["timing_values"] == {"provider_stream_text_delta_count": 2}
    assert consume["api_mode"] == "codex_responses"


def test_a_stream_with_no_text_times_start_to_end_and_writes_no_first_delta():
    events: list = []
    agent = _agent(events)  # held: the registry is weak
    receipt.remember_stream_agent(agent)
    ids = {"session_id": "s1", "turn_id": "t1", "iteration": 1}
    receipt.on_stream_start(**ids)
    receipt.on_stream_end(**ids, finished=False, error="boom")

    steps = _by_step(events)
    assert list(steps) == ["provider_stream_consume"]
    assert steps["provider_stream_consume"]["status"] == "failed"
    assert steps["provider_stream_consume"]["timing_values"] == {"provider_stream_text_delta_count": 0}


def test_an_unnamed_session_gets_no_receipt():
    """Positive control beside it: the same events for the named session do write."""
    events: list = []
    agent = _agent(events, session_id="named")
    receipt.remember_stream_agent(agent)
    for session in ("other", "named"):
        ids = {"session_id": session, "turn_id": "t", "iteration": 1}
        receipt.on_stream_start(**ids)
        receipt.on_stream_delta(**ids, delta="x", kind="text")
        receipt.on_stream_end(**ids, finished=True)
    assert [e["step"] for e in events] == ["provider_stream_first_delta", "provider_stream_consume"]


def test_an_unbound_turn_names_no_agent():
    receipt.remember_stream_agent()
    receipt.on_stream_start(session_id="", turn_id="t", iteration=1)
    assert not receipt._STREAMS
