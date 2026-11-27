"""Codex and fallback execution through the turn handler and Running Work's real stream."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.codex_runtime import run_codex_app_server_turn
from agent.turn_api_call import perform_api_call
from agent.turn_recovery import activate_codex_app_server_fallback
from agent.turn_response_intake import _fire_post_api_request_hook
from agent_runtime.chat_turn_presence import EVENT_TURN_MODEL_ROUTE_CHANGED
from agent_runtime.events import EventLog
from agent_runtime.patch_coverage import HISTORICAL_FOLD_ENTITIES, RUNNING_WORK_SECTION_CAPABILITY
from agent_runtime.persona_turn_binding import bind_persona_turn_agent
from agent_runtime.serde import to_jsonable
from agent_runtime.stream.build import _batch_frames_with_liveness
from agent_runtime.stream.frames import running_work_frame
from agent_runtime.usage_ledger import on_post_api_request
from hermes_cli import lifecycle, middleware
from hermes_cli.harness_parts.persona import chat_turn_message
from tests.agent.test_provider_fallback import _make_agent, _mock_client
from tests.agent.transports.test_codex_app_server_session import FakeClient, make_session
from tests.hermes_cli.test_mission_chat_budget_payload import (
    _args,
    _seed,
    isolate_agent_runtime_root,  # re-exported fixture
)


TURN_ID = "running_route_turn"
CODEX_ROUTE = {"provider": "openai-codex", "model": "gpt-5.6-luna"}
FALLBACK_ROUTE = {"provider": "openai", "model": "gpt-4o"}
REPLY_ROUTE = {"provider": "openai", "model": "gpt-4o-2024-11-20"}


def _turn_row(frame):
    return next(row for row in frame["running_work"]["rows"] if row["work_id"] == f"chat_turn:{TURN_ID}")


def _last_offset():
    return max((int(offset) for offset, _ in EventLog().iter_from_offset(0)), default=0)


def _next_route_frame(offset):
    batch = [(int(move), event) for move, event in EventLog().iter_from_offset(offset)]
    assert [event.type for _, event in batch] == [EVENT_TURN_MODEL_ROUTE_CHANGED]
    frame, = _batch_frames_with_liveness(
        batch, base_offset=offset, delta_patches=True, resync=False, heartbeat_interval_seconds=60,
        fold_entities=HISTORICAL_FOLD_ENTITIES | {RUNNING_WORK_SECTION_CAPABILITY},
    )
    assert frame["type"] == "running_work"
    assert frame["base_offset"] == offset
    assert frame["watermark"]["event_offset"] == batch[-1][0]
    return frame


def _generic_request(agent, request_id):
    return perform_api_call(
        agent, api_kwargs={"model": agent.model, "input": [{"role": "user", "content": "hello"}], "instructions": "answer"},
        _original_api_kwargs={}, _llm_middleware_trace=[],
        _moa_prepared_request=None, _retry=SimpleNamespace(), thinking_spinner=None, retry_count=0,
        api_call_count=1, api_request_id=request_id, effective_task_id=TURN_ID, turn_id=TURN_ID,
        interrupted=False,
    ).response


@pytest.mark.parametrize("fallback", [False, True], ids=["codex", "codex-fallback"])
def test_running_work_pushes_then_reloads_the_answering_route(
    monkeypatch, capsys, isolate_agent_runtime_root, fallback,
):
    agent = _make_agent(fallback_model=[FALLBACK_ROUTE.copy()])
    agent.provider = CODEX_ROUTE["provider"]
    agent.model = "gpt-5.6-luna-900k"  # Codex receives the base slug, never the picker alias.
    agent.api_mode = "codex_app_server"
    client = FakeClient()
    if not fallback:
        client.queue_notification(
            "item/completed", threadId="t", turnId="tu1",
            item={"type": "agentMessage", "id": "answer-1", "text": "answer"},
        )
    client.queue_notification(
        "turn/completed", threadId="t",
        turn={"id": "tu1", "status": "failed" if fallback else "completed",
              "error": {"message": "429 Too Many Requests"} if fallback else None},
    )
    codex_session = make_session(client, model=agent.model)
    monkeypatch.setattr("agent.codex_runtime._ensure_codex_session", lambda *_: None)
    agent._codex_session = codex_session
    monkeypatch.setattr(
        "agent.auxiliary_client.resolve_provider_client",
        lambda *a, **k: (_mock_client(base_url="https://api.openai.com/v1"), FALLBACK_ROUTE["model"]),
    )
    monkeypatch.setattr("agent.turn_api_call._should_stream", lambda _: False)
    monkeypatch.setattr(lifecycle, "has_hook", lambda name: name == "post_api_request")
    def invoke_hook(name, **kwargs):
        if name == "post_api_request":
            on_post_api_request(**kwargs)
        return []

    monkeypatch.setattr(lifecycle, "invoke_hook", invoke_hook)
    monkeypatch.setattr(agent, "_api_response_payload_for_hook", lambda *a, **k: {})
    monkeypatch.setattr(agent, "_usage_summary_for_api_request_hook", lambda _: None)

    frames = []
    offsets = {}
    take_notification = client.take_notification

    def take_first_notification(**kwargs):
        if not frames:
            frame = _next_route_frame(offsets["before_codex"])
            assert _turn_row(frame)["model_route"] == CODEX_ROUTE
            frames.append(frame)
        return take_notification(**kwargs)

    monkeypatch.setattr(client, "take_notification", take_first_notification)

    def fallback_response(_request):
        if len(frames) == 1:
            frame = _next_route_frame(offsets["before_fallback"])
            assert _turn_row(frame)["model_route"] == FALLBACK_ROUTE
            frames.append(frame)
        return SimpleNamespace(model=REPLY_ROUTE["model"])

    monkeypatch.setattr(agent, "_interruptible_api_call", fallback_response)

    class Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            kwargs["agent_ready_callback"](agent)
            before = running_work_frame(as_of_offset=_last_offset())
            assert "model_route" not in _turn_row(before)
            with bind_persona_turn_agent(agent):
                before_veto = _last_offset()
                with monkeypatch.context() as plugin:
                    plugin.setattr(middleware, "run_llm_execution_middleware", lambda *a, **k: None)
                    _generic_request(agent, "middleware-veto")
                assert _last_offset() == before_veto  # a plugin intercepts the request before the provider
                offsets["before_codex"] = before_veto
                native = run_codex_app_server_turn(
                    agent, user_message="test", original_user_message="test", messages=[],
                    effective_task_id=TURN_ID, turn_id=TURN_ID,
                )
                if fallback:
                    assert activate_codex_app_server_fallback(agent, native)
                    offsets["before_fallback"] = _last_offset()
                    _generic_request(agent, "fallback-1")
                    offset = _last_offset()
                    response = _generic_request(agent, "fallback-2")
                    assert _last_offset() == offset  # same route, no extra stream event
                    assistant = SimpleNamespace(content="answer", tool_calls=[])
                    _fire_post_api_request_hook(
                        agent, response, assistant, "stop", api_messages=[], api_call_count=1, api_duration=0,
                        api_start_time=0, api_request_id="fallback-2", effective_task_id=TURN_ID, turn_id=TURN_ID,
                    )
                    # A late result from the first attempt must not overwrite the answer.
                    _fire_post_api_request_hook(
                        agent, SimpleNamespace(model="stale-response"), assistant, "stop", api_messages=[],
                        api_call_count=1, api_duration=0, api_start_time=0, api_request_id="fallback-1",
                        effective_task_id=TURN_ID, turn_id=TURN_ID,
                    )
                    _fire_post_api_request_hook(
                        agent, SimpleNamespace(model="tool-only"), SimpleNamespace(content=None, tool_calls=[{}]),
                        "tool_calls", api_messages=[], api_call_count=2, api_duration=0, api_start_time=0,
                        api_request_id="fallback-2", effective_task_id=TURN_ID, turn_id=TURN_ID,
                    )
                else:
                    assert native["completed"] and native["final_response"] == "answer"
            return SimpleNamespace(final_response="answer", input_tokens=1, output_tokens=1, total_tokens=2,
                                   latency_ms=1, profile_timing={}, raw={})

    _seed(monkeypatch, Provider)
    assert chat_turn_message._cmd_mission_chat_message(_args(TURN_ID)) == 0, capsys.readouterr().out

    agent.model = "new-picker-choice"
    reloaded = running_work_frame(as_of_offset=_last_offset())
    finished = _turn_row(reloaded)
    assert finished["finished_at"]
    assert finished["model_route"] == (REPLY_ROUTE if fallback else CODEX_ROUTE)
    frames.append(reloaded)

    if fallback and (capture := os.getenv("HERMES_TEST_RUNNING_MODEL_FRAMES")):
        Path(capture).write_text(json.dumps(to_jsonable(frames)), encoding="utf-8")
