"""RT-EXPLICIT-PROFILE-ARGS-SEAM: a gateway child launched for the DEFAULT profile names it.

Upstream ``_profile_arg`` answers "" for the default home, so an unsupervised child launched from
it read the sticky ``active_profile`` in ``main._apply_profile_override`` and booted that profile
instead (seen on Windows 2026-11-15 for the elevated install handoff). Each launch path below
builds its argv through ``gateway_downstream.explicit_profile_arg`` and is then booted with a
sticky ``active_profile`` set, which must leave the child on the default home.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.hermes_cli.test_apply_profile_override import _run_apply_profile_override
from tests.hermes_cli.test_apply_profile_override_downstream import _pin_hermes_root


@pytest.fixture
def default_home(tmp_path, monkeypatch) -> Path:
    """This process runs the default profile (HERMES_HOME is the root); the saved one is ``sticky``."""
    root = tmp_path / ".hermes"
    (root / "profiles" / "sticky").mkdir(parents=True)
    (root / "profiles" / "sticky" / "config.yaml").write_text("{}\n", encoding="utf-8")
    (root / "active_profile").write_text("sticky", encoding="utf-8")
    _pin_hermes_root(monkeypatch, root)
    monkeypatch.setenv("HERMES_HOME", str(root))
    return root


def _boots_on(tmp_path, monkeypatch, cli: list[str]) -> Path:
    """The home the child's bootstrap selects for ``hermes <cli>`` with ``sticky`` saved."""
    home = _run_apply_profile_override(tmp_path, monkeypatch, hermes_home=str(tmp_path / ".hermes"),
                                       active_profile="sticky", argv=["hermes", *cli])
    return Path(home).resolve()


def _tail_from(argv: list[str], first: str) -> list[str]:
    return argv[argv.index(first):]


def test_the_helper_names_the_default_root_a_named_home_and_nothing_for_another_root(default_home, tmp_path):
    from hermes_cli.gateway_downstream import explicit_profile_arg

    assert explicit_profile_arg() == "--profile default"
    assert explicit_profile_arg(home=default_home / "profiles" / "sticky") == "--profile sticky"
    assert explicit_profile_arg(home=tmp_path / "elsewhere") == ""
    assert explicit_profile_arg(profile="default") == "--profile default"


def test_the_elevated_windows_handoff_keeps_the_default_profile(default_home, tmp_path, monkeypatch):
    # The ShellExecuteW call is Windows-only; its argv is built here (_launch_elevated_gateway_command:
    # ``-m hermes_cli.main *_current_profile_cli_args() gateway <command>``). Real read owed on Windows.
    from hermes_cli import gateway_windows

    args = gateway_windows._current_profile_cli_args()

    assert args == ["--profile", "default"]
    assert _boots_on(tmp_path, monkeypatch, [*args, "gateway", "install", "--elevated-handoff"]) == default_home.resolve()


def test_the_post_update_relaunch_of_a_manual_default_gateway_keeps_it(default_home, tmp_path, monkeypatch):
    from hermes_cli import gateway

    argv = gateway._gateway_run_args_for_profile("default")

    assert _tail_from(argv, "--profile") == ["--profile", "default", "gateway", "run", "--replace"]
    assert _boots_on(tmp_path, monkeypatch, _tail_from(argv, "--profile")) == default_home.resolve()
    assert "--profile" in gateway._gateway_run_args_for_profile("work")  # a named profile is unchanged


def test_the_post_update_relaunch_of_a_stopped_default_serve_keeps_it(default_home, tmp_path, monkeypatch):
    from hermes_cli.update_cmd_windows import _serve_relaunch_commands

    (command,) = _serve_relaunch_commands([{"port": 8642, "profile": "default", "purpose": "serve"}])

    assert command[1:] == ["--profile", "default", "serve", "--port", "8642"]
    (named,) = _serve_relaunch_commands([{"port": 8643, "profile": "work", "purpose": "serve"}])
    assert named[1:] == ["--profile", "work", "serve", "--port", "8643"]


@pytest.mark.skipif(sys.platform == "win32", reason="launchd command builder; POSIX paths")
def test_the_launchd_detached_gateway_already_names_the_default_profile(default_home, tmp_path, monkeypatch):
    # Upstream bytes (no fork edit): pinned so the four launch paths are read together.
    from hermes_cli import gateway

    argv = gateway._gateway_run_command()

    assert _tail_from(argv, "--profile")[:4] == ["--profile", "default", "gateway", "run"]
    assert _boots_on(tmp_path, monkeypatch, _tail_from(argv, "--profile")) == default_home.resolve()
