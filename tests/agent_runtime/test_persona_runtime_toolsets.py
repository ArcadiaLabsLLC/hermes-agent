"""The bundled edition's disables ride the chat turn's REQUEST, so a shared config.yaml cannot reopen them.

RT-NAMESPACE-SHARED-CONFIG-SHELL-FAMILY B2 (plan bundled-shell-family-opt-in-2026-10-21.md). Upstream
unions config's ``agent.disabled_toolsets`` into the request's list, so the request is the seam:
whatever the namespace's ``config.yaml`` says (``agent.disabled_toolsets: []``, the Developer Edition's
edit), the bundled turn's request carries the profile's shell family.

Killing mutation: read ``config.yaml``'s list instead of the profile's -> the "config says []" test reds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_runtime import bundled_toolsets as bt
from agent_runtime.chat_lane_bundle import invalidate_chat_lane_bundles
from agent_runtime.profile_runner import AgentRunResult
from tests.agent_runtime.persona_samples import sample_personas

SHELL = {"terminal", "code_execution", "browser", "browser-use"}


class _CapturingRunner:
    request = None

    def run(self, request):
        self.request = request
        return AgentRunResult(final_response="ok", session_id="session_mission_chat",
                              provider=request.provider, model=request.model, base_url=None, messages=[])


@pytest.fixture
def turn(tmp_path: Path, monkeypatch):
    from agent_runtime.persona_runtime import GPTPersonaRuntime

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("agent:\n  disabled_toolsets: []\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    monkeypatch.setattr(bt, "profile_name", lambda: bt.DESKTOP_PROFILE)
    monkeypatch.setattr(bt, "persona_home", lambda _persona: home)
    neko = {persona.id: persona for persona in sample_personas()}["neko_supervisor"]

    def run(bundled: bool):
        monkeypatch.setattr("hermes_cli.steward.is_bundled_payload", lambda _root: bundled)
        invalidate_chat_lane_bundles()
        runner = _CapturingRunner()
        GPTPersonaRuntime(default_provider="openai-codex", default_model="gpt-6-sol",
                          agent_runner=runner).mission_chat_reply(
            neko, "hello", permission_session_id="session_mission_chat")
        return runner.request

    run.home = home
    return run


def test_the_bundled_turn_carries_the_shell_family_whatever_the_config_says(turn):
    request = turn(True)
    assert SHELL <= set(request.disabled_toolsets or ())


def test_a_granted_toolset_is_absent_from_the_bundled_request(turn, monkeypatch):
    monkeypatch.setattr("hermes_cli.steward.is_bundled_payload", lambda _root: True)
    bt.write_approval(turn.home, "terminal", mode="grant", reason="test")
    disabled = set(turn(True).disabled_toolsets or ())
    assert "terminal" not in disabled and (SHELL - {"terminal"}) <= disabled


def test_the_developer_turn_carries_no_request_disables(turn):
    assert turn(False).disabled_toolsets is None
