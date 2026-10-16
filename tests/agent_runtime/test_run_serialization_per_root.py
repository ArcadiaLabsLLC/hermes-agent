"""Run-serialization S5: one run per chat ROOT — another root progresses while one waits.

Plan: ``docs/agent-runtime-harness/planned/run-serialization-retirement-2026-10-15.md`` S5.

Driven through the real runner (``ProfileAgentRunner.run``) with a fake agent, so the
whole scope stack is entered as a serve turn enters it. Root A's agent parks inside its
turn — the shape of a turn blocked on an operator approval — until root B's turn has
finished; root B is bound to a different profile, and each records the home and runtime
root it resolves while the other is bound.

Kill-mutation: in ``AgentRunExecution.scopes`` replace
``root_run_lock(request.root_chat_session_id or request.tool_execution_scope_id)`` with
``root_run_lock(None)`` (every run shares one key, the old process-wide behaviour). Root
B then cannot start until root A gives up waiting, and the overlap test reds.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner

_WAIT = 20.0


class _Agent:
    behaviour: dict[str, object] = {}

    def __init__(self, **kwargs):
        self.session_id = kwargs.get("session_id") or "session_fake"
        self.provider = kwargs.get("provider")
        self.model = kwargs.get("model")
        self.base_url = "https://example.invalid/v1"
        self.tools = []

    def run_conversation(self, user_message, system_message=None, task_id=None):
        from agent_runtime.run_context import runtime_root_signal
        from hermes_constants import get_hermes_home

        hook = _Agent.behaviour[user_message]
        hook["home"] = get_hermes_home()
        hook["root"] = runtime_root_signal()
        hook["env_home"] = os.environ.get("HERMES_HOME")
        hook["run"]()
        return {"final_response": "ok", "session_id": self.session_id, "provider": self.provider,
                "model": self.model, "base_url": self.base_url,
                "messages": [{"role": "assistant", "content": "ok"}], "api_calls": 1, "total_tokens": 3}


@pytest.fixture
def two_profiles(tmp_path, monkeypatch):
    homes = {name: tmp_path / "profiles" / name for name in ("alpha", "beta")}
    for home in homes.values():
        home.mkdir(parents=True)
    monkeypatch.setattr("agent_runtime.profile_runner.status.profile_exists", lambda name: name in homes)
    monkeypatch.setattr("agent_runtime.profile_runner.status.get_profile_dir", lambda name: homes[name])
    monkeypatch.setattr("agent_runtime.profile_runner.status.normalize_profile_name", lambda name: name)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "head"))
    _Agent.behaviour = {}
    return homes


def _run(profile: str, root: str, message: str, runtime_root: Path, errors: list) -> None:
    try:
        ProfileAgentRunner(agent_factory=_Agent).run(AgentRunRequest(
            profile=profile, user_message=message, runtime_root=runtime_root,
            root_chat_session_id=root, tool_execution_scope_id=root))
    except BaseException as exc:  # surfaced by the test
        errors.append(exc)


def test_another_root_finishes_while_one_root_waits(tmp_path, two_profiles):
    b_done = threading.Event()
    a_waiting = threading.Event()
    a_saw_b_finish: list[bool] = []

    def a_body():
        a_waiting.set()
        a_saw_b_finish.append(b_done.wait(_WAIT))  # the "approval wait"

    _Agent.behaviour = {"a": {"run": a_body}, "b": {"run": b_done.set}}
    errors: list = []
    a = threading.Thread(target=_run, args=("alpha", "root-a", "a", tmp_path / "rt-a", errors))
    a.start()
    assert a_waiting.wait(_WAIT)
    b = threading.Thread(target=_run, args=("beta", "root-b", "b", tmp_path / "rt-b", errors))
    b.start()
    b.join(_WAIT * 2)
    a.join(_WAIT * 2)
    assert not errors, errors
    assert a_saw_b_finish == [True], "root B could not run while root A was parked in its turn"
    for key, profile in (("a", "alpha"), ("b", "beta")):
        seen = _Agent.behaviour[key]
        assert seen["home"] == two_profiles[profile], seen
        assert seen["root"] == str(tmp_path / f"rt-{key}"), seen
        assert seen["env_home"] == str(tmp_path / "head"), seen  # never rewritten


def test_two_turns_of_one_root_still_serialize(tmp_path, two_profiles):
    """Positive control for the lock itself: the SAME root never overlaps."""

    second_started = threading.Event()
    first_waiting = threading.Event()
    first_saw_second: list[bool] = []

    def first_body():
        first_waiting.set()
        first_saw_second.append(second_started.wait(1.5))

    _Agent.behaviour = {"first": {"run": first_body}, "second": {"run": second_started.set}}
    errors: list = []
    first = threading.Thread(target=_run, args=("alpha", "root-x", "first", tmp_path / "rt", errors))
    first.start()
    assert first_waiting.wait(_WAIT)
    second = threading.Thread(target=_run, args=("beta", "root-x", "second", tmp_path / "rt", errors))
    second.start()
    first.join(_WAIT * 2)
    second.join(_WAIT * 2)
    assert not errors, errors
    assert first_saw_second == [False], "a second turn of the same root ran inside the first"
    assert second_started.is_set()
