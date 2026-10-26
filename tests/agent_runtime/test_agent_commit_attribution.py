"""``RT-AGENT-COMMIT-ATTRIBUTION`` — a persona turn's commits name the agent and the turn.

Each test names the mutation that kills it (recorded in the landing commit).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from agent_runtime.agent_commit_attribution import with_commit_trailers
from agent_runtime.live_turns import live_turn
from agent_runtime.persona_turn_binding import bind_persona_turn_agent

_IDS = {"persona_instance_id": "personainst_neko_1", "turn_id": "agent-chat-send-abc"}
_OPTION = " --trailer=Agent-Instance:personainst_neko_1 --trailer=Agent-Turn:agent-chat-send-abc"


# Mutation: drop the ``(?=$|[\s;&|)])`` look-ahead -> ``commit-tree`` is rewritten;
# drop the global-option arm -> ``git -C "<dir>" commit`` is not.
def test_the_trailers_land_right_after_each_commit_verb_and_nowhere_else():
    assert with_commit_trailers('git -C "X:/a b" commit -q -m "fix"', **_IDS) == (
        f'git -C "X:/a b" commit{_OPTION} -q -m "fix"')
    assert with_commit_trailers("git commit -m x && git push origin HEAD:main", **_IDS) == (
        f"git commit{_OPTION} -m x && git push origin HEAD:main")
    for unchanged in ("git commit-tree HEAD^{tree}", "git log --grep commit", "echo commit"):
        assert with_commit_trailers(unchanged, **_IDS) == unchanged
    already = "git commit -m x --trailer=Agent-Turn:other"
    assert with_commit_trailers(already, **_IDS) == already
    assert with_commit_trailers("git commit -m x", persona_instance_id="", turn_id="t") == "git commit -m x"


def test_git_records_both_trailers_on_a_real_commit(tmp_path):
    """Positive control: the rewritten command, run by git, yields the two trailers."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    command = with_commit_trailers(
        f'git -C "{tmp_path.as_posix()}" -c user.name=a -c user.email=a@b commit -q --allow-empty -m "x"', **_IDS)
    subprocess.run(command, shell=True, check=True)
    body = subprocess.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%B"],
                          capture_output=True, text=True, check=True).stdout
    assert "Agent-Instance: personainst_neko_1" in body and "Agent-Turn: agent-chat-send-abc" in body


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eh_plugin_attr_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Mutation: register attribution as a second ``tool_request`` middleware instead of chaining it
# (or drop the ``attribute_commits`` call) -> the background commit loses one of its rewrites.
def test_the_plugin_middleware_chains_notify_and_attribution_inside_a_persona_turn():
    callback = _plugin().default_background_notify
    agent = SimpleNamespace(_persona_chat_turn_id="agent-chat-send-abc")
    args = {"command": "git commit -m x", "background": True}

    assert callback(tool_name="terminal", args=args)["args"] == {**args, "notify": True}
    with bind_persona_turn_agent(agent), live_turn(
        turn_id="agent-chat-send-abc", session_id="s", persona_instance_id="personainst_neko_1", agent=agent,
    ):
        result = callback(tool_name="terminal", args=args)
    assert result["args"] == {"command": f"git commit{_OPTION} -m x", "background": True, "notify": True}
    assert result["reason"] == "background notify default; agent commit trailers"
