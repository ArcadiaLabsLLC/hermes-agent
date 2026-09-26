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


# ── end to end: the plugin's own registration, on the codex path ─────────────


def _plugin_hooks():
    """The hook callbacks ``plugins/eternia-harness`` registers, by hook name."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_stream_receipt", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks: dict = {}

    class _Ctx:
        def register_hook(self, name, callback):
            hooks.setdefault(name, []).append(callback)
            return SimpleNamespace(dispose=lambda: hooks[name].remove(callback))

        def __getattr__(self, _name):
            return lambda *a, **k: None

    import hermes_cli.harness_parts.mission_chat_door_binding as door
    original = door.bind_mission_chat_door
    door.bind_mission_chat_door = lambda: None
    try:
        module.register(_Ctx())
    finally:
        door.bind_mission_chat_door = original
    return module, hooks


def test_the_codex_stream_writes_the_receipt_through_the_plugin_hooks(tmp_path, monkeypatch):
    import sys
    import time
    import types

    sys.modules.setdefault("fire", types.SimpleNamespace(Fire=lambda *a, **k: None))
    sys.modules.setdefault("firecrawl", types.SimpleNamespace(Firecrawl=object))
    sys.modules.setdefault("fal_client", types.SimpleNamespace())
    from agent import chat_completion_helpers as h
    from agent.plugin_stream_hooks import shutdown_plugin_stream_hook_dispatcher
    from tests.agent.test_codex_ttfb_watchdog import _install_codex_event_stream, _make_codex_agent

    agent = _make_codex_agent(tmp_path, monkeypatch)
    # after the agent: its construction discovers the real plugin, whose load re-installs
    # the real register_hook; this load is the one the turn must arm
    plugin, hooks = _plugin_hooks()
    shutdown_plugin_stream_hook_dispatcher()
    monkeypatch.setattr("hermes_cli.plugins.iter_hook_callbacks", lambda name: tuple(hooks.get(name, ())))
    events: list = []
    agent.status_callback = events.append

    def stream():
        yield SimpleNamespace(type="response.created")
        yield SimpleNamespace(type="response.output_text.delta", delta="hel")
        yield SimpleNamespace(type="response.output_text.delta", delta="lo")
        yield SimpleNamespace(type="response.completed", response=SimpleNamespace(status="completed", id="r", usage=None))

    _install_codex_event_stream(agent, monkeypatch, stream, [])
    with bind_persona_turn_agent(agent), receipt.stream_observers_armed():
        # the plugin's llm_execution middleware, around the codex streaming call
        plugin.time_provider_dispatch(
            request=None, next_call=lambda: h.interruptible_streaming_api_call(agent, {"model": "gpt-5.5", "input": "hi"}),
            api_call_count=1, api_mode="codex_responses", provider="openai-codex", model="gpt-5.5")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and "provider_stream_consume" not in _by_step(events):
        time.sleep(0.02)
    shutdown_plugin_stream_hook_dispatcher()

    steps = _by_step(events)
    assert "provider_stream_consume" in steps, sorted(steps)
    assert steps["provider_stream_consume"]["timing_values"] == {"provider_stream_text_delta_count": 2}
    assert "provider_stream_first_delta" in steps
    assert "conversation_provider_dispatch" in steps  # the dispatch total, same middleware


# ── the observers exist only while a persona turn runs ───────────────────────
# Any registered on_stream_* callback makes upstream's ``_has_stream_consumers()`` True
# for EVERY agent in the process (streaming, spinner and post-response mute follow it).


_STREAM_HOOKS = ("on_stream_start", "on_stream_delta", "on_stream_end")


def _registered(hooks):
    return {name for name in _STREAM_HOOKS if hooks.get(name)}


def test_plugin_load_registers_no_stream_observer():
    _plugin, hooks = _plugin_hooks()

    assert _registered(hooks) == set()
    with receipt.stream_observers_armed():  # positive control: the same load CAN arm them
        assert _registered(hooks) == set(_STREAM_HOOKS)


def test_armed_turns_share_one_registration_and_the_last_one_out_disposes_it():
    _plugin, hooks = _plugin_hooks()

    with receipt.stream_observers_armed():
        with receipt.stream_observers_armed():
            assert [len(hooks[name]) for name in _STREAM_HOOKS] == [1, 1, 1]
        assert _registered(hooks) == set(_STREAM_HOOKS)
    assert _registered(hooks) == set()


def test_the_profile_runner_turn_runs_with_the_observers_armed():
    from agent_runtime.profile_runner.execute import _run_conversation_with_usage_ledger

    _plugin, hooks = _plugin_hooks()
    seen = []
    agent = _Agent(session_id="s1", run_conversation=lambda **_k: seen.append(_registered(hooks)) or {})

    _run_conversation_with_usage_ledger(agent, {})

    assert seen == [set(_STREAM_HOOKS)]
    assert _registered(hooks) == set()
