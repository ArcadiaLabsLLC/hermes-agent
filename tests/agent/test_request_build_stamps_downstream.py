"""Fork tests for the h-turn1 A5 seam in upstream ``agent/turn_api_request.py::build_api_request``.

The marked ``_laps`` lines split the turn's ``preflight_done -> request_built`` span into
``agent_runtime.request_build_timing.REQUEST_BUILD_PARTS`` and hand the split to the run's
status callback as one ``timing_values`` payload, which the runner records into the turn's
``profile_timing``. Killing mutation: delete the ``_laps.finish("hook")`` line -> no payload,
``test_one_attempt_emits_every_part_once`` reds.
"""

from __future__ import annotations

import time

import pytest

from agent_runtime.conversation_observability import CONVERSATION_PREFLIGHT_DONE_STEP, _emit_phase_marker
from agent_runtime.request_build_timing import REQUEST_BUILD_PARTS, REQUEST_BUILD_STEP, timing_value_key


@pytest.fixture
def agent(tmp_path, monkeypatch):
    from run_agent import AIAgent

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    built = AIAgent(api_key="k", base_url="https://api.groq.com/openai/v1", provider="custom", model="m",
                    quiet_mode=True, skip_context_files=True, skip_memory=True)
    built._cached_system_prompt = "SYS"
    built._empty_content_retries = 0
    built.payloads = []
    built.status_callback = built.payloads.append
    return built


def _build(agent):
    from agent.turn_api_request import build_api_request

    messages = [{"role": "user", "content": "hi"}]
    return build_api_request(
        agent, api_messages=[{"role": "system", "content": "SYS"}, *messages], _moa_prepared_request=None,
        tools_for_api=agent.tools, system_message=None, messages=messages, original_user_message="hi",
        approx_tokens=1, total_chars=2, retry_count=0, api_call_count=1, api_request_id="r",
        api_start_time=time.time(), effective_task_id="t", turn_id="u",
    )


def _splits(agent):
    return [p["timing_values"] for p in agent.payloads if p.get("step") == REQUEST_BUILD_STEP]


def test_one_attempt_emits_every_part_once(agent):
    _emit_phase_marker(agent, CONVERSATION_PREFLIGHT_DONE_STEP)
    built = _build(agent)

    assert built.action == "fallthrough"
    [split] = _splits(agent)
    assert set(split) == {timing_value_key(part) for part in REQUEST_BUILD_PARTS}
    assert all(isinstance(v, int) and v >= 0 for v in split.values())


def test_a_retry_attempt_has_no_lead_in(agent):
    """``lead_in`` is announce + rate guard, which a retry of the same call does not re-run."""

    _emit_phase_marker(agent, CONVERSATION_PREFLIGHT_DONE_STEP)
    _build(agent)
    _build(agent)

    first, retry = _splits(agent)
    assert timing_value_key("lead_in") in first
    assert timing_value_key("lead_in") not in retry
    assert set(retry) == {timing_value_key(part) for part in REQUEST_BUILD_PARTS[1:]}


def test_the_runner_records_the_split_into_profile_timing(agent):
    from agent_runtime.profile_runner.status import StatusEmitter

    timing: dict = {}
    emitter = StatusEmitter(type("R", (), {"progress_callback": None})(), timing)
    agent.status_callback = emitter.emit
    _emit_phase_marker(agent, CONVERSATION_PREFLIGHT_DONE_STEP)
    _build(agent)

    assert {k for k in timing if k.startswith("profile_conversation_request_")} == {
        f"profile_{timing_value_key(part)}" for part in REQUEST_BUILD_PARTS
    }


def test_a_raising_status_callback_never_fails_the_build(agent):
    def boom(_payload):
        raise RuntimeError("sink down")

    agent.status_callback = boom
    assert _build(agent).action == "fallthrough"
