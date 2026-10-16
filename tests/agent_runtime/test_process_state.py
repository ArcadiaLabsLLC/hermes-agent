"""``agent_runtime.process_state``: process-global state is declared beside its
global, and one call puts every declared piece back the way a fresh import left
it. Plan ``docs/agent-runtime-harness/planned/process-global-state-reset-2026-10-15.md`` S1/S2.

The owner arm asks the RUNTIME: it dirties each owner's real global, runs the one
reset, and reads the global back -- a registration that is spelled but never
bound, or a reset that misses its global, reds here.
"""

from __future__ import annotations

import importlib

import pytest

from agent_runtime import process_state


@pytest.fixture
def _private_registry(monkeypatch):
    monkeypatch.setattr(process_state, "_RESETS", {})


def test_every_declared_reset_runs_and_a_failure_does_not_stop_the_rest(_private_registry):
    ran: list[str] = []

    def boom() -> None:
        ran.append("b")
        raise OSError("closed twice")

    process_state.register_process_state("c", lambda: ran.append("c"))
    process_state.register_process_state("b", boom, holds=("_B",))
    process_state.register_process_state("a", lambda: ran.append("a"), holds=("_A", "_A2"))

    with pytest.raises(process_state.ProcessStateResetError, match="failed: b") as caught:
        process_state.reset_all_process_state()

    assert ran == ["a", "b", "c"]
    assert isinstance(caught.value.__cause__, OSError)
    assert process_state.declared_globals() == {"a:_A", "a:_A2", "b:_B"}


def test_re_registering_a_name_replaces_it(_private_registry):
    process_state.register_process_state("m", lambda: None, holds=("_OLD",))
    process_state.register_process_state("m", lambda: None, holds=("_NEW",))

    assert process_state.registered_process_state() == ("m",)
    assert process_state.declared_globals() == {"m:_NEW"}


def _dirty_and_read(module_name: str):
    """(dirty the owner's global, read whether it is clean) for each declared owner."""

    module = importlib.import_module(module_name)
    if module_name == "agent_runtime.builds.detect":
        return module.enable_detection, lambda: module.detection_enabled() is False
    if module_name == "agent_runtime.persona_chat_continuity.runtime_registry":
        return (
            lambda: module.initialize_persona_chat_runtime_registry(enabled=True),
            lambda: module.persona_chat_runtime_registry() is None,
        )
    if module_name == "agent_runtime.idle_turn_keeper":
        return lambda: module._REFRESHES.__setitem__("leak", lambda: None), lambda: not module._REFRESHES
    if module_name == "agent_runtime.chat_lane_bundle":
        return lambda: module._memo.__setitem__(("leak", "leak"), None), lambda: not module._memo
    memo = {
        "agent_runtime.prompt_observability.skills_resolver": "_skill_catalog_memo",
        "agent_runtime.snapshot.summaries": "_profile_template_memo",
    }[module_name]
    target = getattr(module, memo)
    return lambda: target.update(rows=["leak"], at=99.0), lambda: target["rows"] is None and target["at"] == 0.0


OWNERS = (
    "agent_runtime.builds.detect",
    "agent_runtime.chat_lane_bundle",
    "agent_runtime.idle_turn_keeper",
    "agent_runtime.persona_chat_continuity.runtime_registry",
    "agent_runtime.prompt_observability.skills_resolver",
    "agent_runtime.snapshot.summaries",
)


@pytest.mark.parametrize("module_name", OWNERS)
def test_each_owner_is_reset_by_the_one_call(module_name):
    dirty, is_clean = _dirty_and_read(module_name)
    dirty()
    assert not is_clean(), "the control did not dirty the global -- the reset below would prove nothing"

    process_state.reset_all_process_state()

    assert module_name in process_state.registered_process_state()
    assert is_clean()
