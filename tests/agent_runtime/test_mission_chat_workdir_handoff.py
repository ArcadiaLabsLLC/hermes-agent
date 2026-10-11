"""D1.12 S1 — the turn's workdir is resolved ONCE, in the turn context, and handed down.

Plan: ``docs/agent-runtime-harness/planned/design-sweep-d1-2026-10-10.md`` § D1.12 S1.
``mission_chat_workdir_for_persona``'s three inputs (the persona, the loaded
``AGENTS.md`` pointer, the primary slot's path) are first in hand in
``build_mission_chat_turn_context``; ``mission_chat_reply`` used to resolve it again.
These arms drive the real builder and the real reply over each ladder rung and count
the resolves: one, and the reply's receipt is the one a direct resolve gives.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import mission_chat_workdir as workdir_module
from agent_runtime import persona_runtime
from agent_runtime.mission_chat_workdir import (
    WORKDIR_SOURCE_PERSONA_CONFIG,
    WORKDIR_SOURCE_PRIMARY_SLOT,
    WORKDIR_SOURCE_WORKSPACE_AGENTS,
)
from agent_runtime.persona_slots import SlotContext
from agent_runtime.profile_runner import AgentRunResult
from tests.agent_runtime.test_mission_chat_turn_context import _build, _resolvers
from tests.agent_runtime.test_mission_chat_workdir import _persona


class _CapturingRunner:
    def __init__(self):
        self.request = None

    def run(self, request):
        self.request = request
        return AgentRunResult(final_response="ok", session_id="s", provider="openai-codex", model="gpt-5.5",
                              base_url=None, messages=[])


@pytest.fixture
def resolves(monkeypatch):
    """Every call to the ONE resolver, wherever it is reached from."""

    calls = []
    real = workdir_module.mission_chat_workdir_for_persona

    def counting(persona, **kwargs):
        calls.append(kwargs)
        return real(persona, **kwargs)

    monkeypatch.setattr(workdir_module, "mission_chat_workdir_for_persona", counting)
    monkeypatch.setattr(persona_runtime, "mission_chat_workdir_for_persona", counting)
    return calls


def _rung(tmp_path, monkeypatch, rung):
    """``(build overrides, the directory the rung grounds the turn in, its source)``."""

    repo = tmp_path / rung
    repo.mkdir()
    if rung == "config":
        monkeypatch.setattr("agent_runtime.config.mission_chat_workdir", lambda _persona_id: str(repo))
        return {}, repo, WORKDIR_SOURCE_PERSONA_CONFIG
    if rung == "agents_file":
        (repo / "AGENTS.md").write_text("# rules", encoding="utf-8")
        from agent_runtime.mission_chat_turn_context import _default_load_workspace_agents

        return ({"agents_file": str(repo / "AGENTS.md"),
                 "resolvers": _resolvers(load_workspace_agents=_default_load_workspace_agents)},
                repo, WORKDIR_SOURCE_WORKSPACE_AGENTS)
    slot = SlotContext(primary_slot="launcher", primary_source="explicit", primary_path=str(repo),
                       bound=(("launcher", str(repo)),), workspace_id="ws")
    return {"resolvers": _resolvers(load_slot_context=lambda _instance: slot)}, repo, WORKDIR_SOURCE_PRIMARY_SLOT


@pytest.mark.parametrize("rung", ["config", "agents_file", "primary_slot"])
def test_the_turn_resolves_its_workdir_once_and_the_reply_runs_there(rung, tmp_path, monkeypatch, resolves):
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    overrides, grounded_in, source = _rung(tmp_path, monkeypatch, rung)
    persona = _persona("neko_supervisor")
    context = _build(persona=persona, **overrides)
    assert len(resolves) == 1, "the turn context resolves the workdir exactly once"
    runner = _CapturingRunner()

    result = persona_runtime.GPTPersonaRuntime(
        default_provider="openai-codex", default_model="gpt-5.5", agent_runner=runner
    ).mission_chat_reply(
        persona, "hi", permission_session_id="session_mission_chat", workdir=context.workdir,
        workspace_agents_path=context.workspace_agents_path, primary_slot_path=context.primary_slot_path,
    )

    assert len(resolves) == 1, "the reply re-resolved a workdir it was handed"
    receipt = result.raw["mission_chat_workdir"]
    assert receipt == workdir_module.mission_chat_workdir_for_persona(
        persona, workspace_agents_path=context.workspace_agents_path, primary_slot_path=context.primary_slot_path
    ).receipt()
    assert receipt["source"] == source
    assert Path(runner.request.workdir) == grounded_in.resolve()


def test_a_caller_that_hands_no_workdir_still_gets_the_ladder(tmp_path, monkeypatch, resolves):
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runner = _CapturingRunner()

    persona_runtime.GPTPersonaRuntime(
        default_provider="openai-codex", default_model="gpt-5.5", agent_runner=runner
    ).mission_chat_reply(_persona("neko_supervisor"), "hi", permission_session_id="s",
                         workspace_agents_path=str(workspace / "AGENTS.md"))

    assert len(resolves) == 1
    assert Path(runner.request.workdir) == workspace.resolve()


def test_the_handler_hands_the_turn_contexts_workdir_to_the_reply(monkeypatch, capsys, tmp_path):
    """The live handler path: the reply receives the turn context's resolve, never None."""

    from hermes_cli.harness_parts.persona import chat_turn_message
    from tests.hermes_cli.test_mission_chat_budget_payload import _args, _seed

    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr("agent_runtime.config.mission_chat_workdir", lambda _persona_id: str(repo))
    received = {}

    class _Provider:
        def __init__(self, *args, **kwargs):
            pass

        def mission_chat_reply(self, *args, **kwargs):
            received.update(kwargs)
            return AgentRunResult(final_response="ok", session_id="s", provider="openai-codex", model="gpt-test",
                                  base_url=None, messages=[], raw={})

    _seed(monkeypatch, _Provider)
    code = chat_turn_message._cmd_mission_chat_message(_args("handoff_turn"))
    assert code == 0, json.loads(capsys.readouterr().out)
    handed = received["workdir"]
    assert handed is not None and handed.source == WORKDIR_SOURCE_PERSONA_CONFIG
    assert Path(handed.path) == repo.resolve()
