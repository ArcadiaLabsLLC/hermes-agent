"""The profile runner binds a run's profile and workdir in CONTEXT, never in process state.

Moved out of ``test_profile_runner.py`` by run-serialization S4/S5 (lane h3-runser),
where these two tests were rewritten from "the env is written and restored" to "the env
is never written": plan ``docs/agent-runtime-harness/archive/run-serialization-retirement-2026-10-15.md``.
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner
from tests.agent_runtime.test_profile_runner import FakeAgent


def test_runner_binds_the_profile_in_context_and_leaves_the_process_env_alone(tmp_path, monkeypatch):
    profile_home = tmp_path / "profiles" / "pm"
    (profile_home / "home").mkdir(parents=True)
    runtime_root = tmp_path / "runtime"
    monkeypatch.setenv("HERMES_HOME", "before_home")
    monkeypatch.setenv("HOME", "before_user_home")
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", "before_runtime")
    monkeypatch.setattr("agent_runtime.profile_runner.status.profile_exists", lambda name: True)
    monkeypatch.setattr("agent_runtime.profile_runner.status.get_profile_dir", lambda name: profile_home)
    monkeypatch.setattr("agent_runtime.profile_runner.status.normalize_profile_name", lambda name: name)
    seen = {}

    class EnvAgent(FakeAgent):
        def run_conversation(self, user_message, system_message=None, task_id=None):
            from agent_runtime.run_context import runtime_root_signal
            from hermes_constants import get_hermes_home

            seen["hermes_home"] = get_hermes_home()
            seen["runtime_root"] = runtime_root_signal()
            seen["env_HERMES_HOME"] = os.environ.get("HERMES_HOME")
            seen["env_HOME"] = os.environ.get("HOME")
            seen["env_HERMES_AGENT_RUNTIME_ROOT"] = os.environ.get("HERMES_AGENT_RUNTIME_ROOT")
            return super().run_conversation(user_message, system_message=system_message, task_id=task_id)

    ProfileAgentRunner(agent_factory=EnvAgent).run(AgentRunRequest(profile="pm", runtime_root=runtime_root, user_message="hi"))

    # Run-serialization S5: the profile, home and root reach the run through its
    # context; the process env is never rewritten — except POSIX HOME, which has no
    # context hook (``workdir._posix_process_home``).
    assert seen["hermes_home"] == profile_home
    assert seen["runtime_root"] == str(runtime_root)
    assert seen["env_HERMES_HOME"] == "before_home"
    assert seen["env_HERMES_AGENT_RUNTIME_ROOT"] == "before_runtime"
    assert seen["env_HOME"] == ("before_user_home" if os.name == "nt" else str(profile_home / "home"))
    assert os.environ["HERMES_HOME"] == "before_home"
    assert os.environ["HOME"] == "before_user_home"
    assert os.environ["HERMES_AGENT_RUNTIME_ROOT"] == "before_runtime"


def test_runner_executes_agent_inside_requested_workdir_and_restores_caller(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("TERMINAL_CWD", "before_terminal_cwd")
    caller_cwd = Path.cwd()
    seen = {}

    class CwdAgent(FakeAgent):
        def run_conversation(self, user_message, system_message=None, task_id=None):
            from agent.runtime_cwd import resolve_agent_cwd
            from tools.terminal_tool_config import _tenv

            seen["process_cwd"] = Path.cwd()
            seen["env_TERMINAL_CWD"] = os.environ.get("TERMINAL_CWD")
            seen["TERMINAL_CWD"] = _tenv("TERMINAL_CWD")
            seen["agent_cwd"] = resolve_agent_cwd()
            return super().run_conversation(user_message, system_message=system_message, task_id=task_id)

    ProfileAgentRunner(agent_factory=CwdAgent).run(AgentRunRequest(profile=None, user_message="hi", workdir=repo))

    # Run-serialization S4: the run is grounded through its terminal scope; the process
    # cwd and the process env never move, during the run or after it.
    assert seen["TERMINAL_CWD"] == str(repo.resolve())
    assert seen["agent_cwd"].resolve() == repo.resolve()
    assert seen["process_cwd"] == caller_cwd
    assert seen["env_TERMINAL_CWD"] == "before_terminal_cwd"
    assert Path.cwd() == caller_cwd
    assert os.environ["TERMINAL_CWD"] == "before_terminal_cwd"
