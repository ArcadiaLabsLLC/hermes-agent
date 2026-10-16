"""A stdio MCP child learns the Hermes home of the process that spawned it."""

from pathlib import Path

from tools.mcp_tool_config import _build_safe_env


def test_stdio_child_env_carries_hermes_home_under_a_redirected_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    env = _build_safe_env(None)
    assert Path(env["HERMES_HOME"]) == tmp_path / "hermes"


def test_server_env_overrides_the_inherited_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    assert _build_safe_env({"HERMES_HOME": "explicit"})["HERMES_HOME"] == "explicit"
