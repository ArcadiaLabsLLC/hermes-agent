"""The repo-slot environment overlay and its one upstream seam (plan ``build-running-work-2026-10-04.md`` §3.3, row H5c).

Owner call 8e: every command whose cwd is under an assigned, bound slot runs with that
slot's environment — the PATH head, the env keys, the slot's ``.env`` (values from the file,
never from the record), the venv. These arms go through the REAL spawn env builders in
``tools/environments/local.py`` (background: ``build_subprocess_env`` →
``_sanitize_subprocess_env``; foreground: ``_make_run_env``), so they prove the seam, not
only the overlay function.
"""

from __future__ import annotations

import json
import os

import pytest

from agent_runtime.machine_roots import machine_roots_cache_clear, write_machine_roots
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slot_env import set_slot_fill, slot_env_path
from agent_runtime.workspace_slot_overlay import SlotBinding, env_overlay, slot_env_scope
from agent_runtime.workspace_slots import declare
from tools.environments.local import _make_run_env, build_subprocess_env

ISSUED = "2026-10-04T12:00:00+00:00"


@pytest.fixture
def slot(tmp_path):
    machine_roots_cache_clear()
    workspace = WorkspaceStore().create(name="Env").id
    checkout = tmp_path / "launcher"
    (checkout / "lib").mkdir(parents=True)
    (checkout / ".env").write_text('ETERNIA_API_BASE=https://api.test\nKEYCLOAK_CLIENT_SECRET="from-dotenv"\n',
                                   encoding="utf-8")
    write_machine_roots({"launcher": str(checkout)}, dry_run=False)
    declare(workspace, [{
        "name": "launcher", "repo": {"clone_url": "https://x/launcher.git"},
        "toolchain": {"env_keys": [{"key": "FLUTTER_ROOT"}], "dotenv": {"path": ".env", "keys": [
            {"key": "ETERNIA_API_BASE"}, {"key": "KEYCLOAK_CLIENT_SECRET", "secret": True}]}},
    }], issued_at=ISSUED, machine="mach_test")
    prepend = str(tmp_path / "flutter" / "bin")
    set_slot_fill(workspace, "launcher", env={"FLUTTER_ROOT": str(tmp_path / "flutter")}, path_prepend=[prepend])
    return workspace, checkout, prepend


def _path(env: dict) -> list[str]:
    key = next(k for k in env if k.upper() == "PATH")
    return env[key].split(os.pathsep)


def test_a_command_under_a_bound_slot_runs_with_the_slot_environment(slot):
    workspace, checkout, prepend = slot
    bindings = [SlotBinding(workspace, "launcher", str(checkout))]
    with slot_env_scope(bindings, checkout / "lib"):
        background = build_subprocess_env({"PATH": os.pathsep.join(["/usr/bin"])})
        foreground = _make_run_env({})
    for env in (background, foreground):
        assert _path(env)[0] == prepend
        assert env["FLUTTER_ROOT"].endswith("flutter")
        assert env["ETERNIA_API_BASE"] == "https://api.test"
        assert env["KEYCLOAK_CLIENT_SECRET"] == "from-dotenv"


def test_outside_every_slot_and_outside_a_turn_nothing_is_overlaid(slot, tmp_path):
    workspace, checkout, prepend = slot
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    with slot_env_scope([SlotBinding(workspace, "launcher", str(checkout))], elsewhere):
        outside = build_subprocess_env({"PATH": "/usr/bin"})
    no_turn = build_subprocess_env({"PATH": "/usr/bin"})
    for env in (outside, no_turn):
        assert "FLUTTER_ROOT" not in env and "ETERNIA_API_BASE" not in env
        assert prepend not in _path(env)


def test_a_secret_reaches_the_overlay_only_from_the_dotenv(slot):
    workspace, checkout, _prepend = slot
    # Write the machine record by hand, past the secret_in_env door.
    record = json.loads(slot_env_path().read_text(encoding="utf-8"))
    record["workspaces"][workspace]["launcher"]["env"]["KEYCLOAK_CLIENT_SECRET"] = "from-the-record"
    slot_env_path().write_text(json.dumps(record), encoding="utf-8")
    overlay = env_overlay(checkout, [SlotBinding(workspace, "launcher", str(checkout))])
    assert overlay.env["KEYCLOAK_CLIENT_SECRET"] == "from-dotenv"
    (checkout / ".env").write_text("ETERNIA_API_BASE=https://api.test\n", encoding="utf-8")
    overlay = env_overlay(checkout, [SlotBinding(workspace, "launcher", str(checkout))])
    assert "KEYCLOAK_CLIENT_SECRET" not in overlay.env
    assert overlay.env_source == "slot:launcher"


def test_the_deepest_bound_slot_wins(slot, tmp_path):
    workspace, checkout, _prepend = slot
    nested = SlotBinding(workspace, "docs", str(checkout / "lib"))
    outer = SlotBinding(workspace, "launcher", str(checkout))
    assert env_overlay(checkout / "lib" / "src", [outer, nested]).slot == "docs"
    assert env_overlay(checkout, [outer, nested]).slot == "launcher"


def test_a_command_spawned_in_another_slot_runs_with_that_slot_not_the_turn_workdir(slot, tmp_path, monkeypatch):
    """The overlay keys on the command's spawn cwd (the terminal's tracked cwd after a ``cd``),
    not the turn's workdir: drive the real ``LocalEnvironment._run_bash`` with Popen captured."""
    import types

    import tools.environments.local as local

    workspace, checkout, prepend = slot
    primary = tmp_path / "primary"
    primary.mkdir()
    spawned: dict = {}

    def fake_popen(args, **kwargs):
        spawned.update(kwargs)
        return types.SimpleNamespace(pid=os.getpid())

    monkeypatch.setattr(local, "_find_bash", lambda: "bash")
    monkeypatch.setattr(local.subprocess, "Popen", fake_popen)
    terminal = local.LocalEnvironment.__new__(local.LocalEnvironment)
    terminal.env, terminal.cwd = {}, str(checkout / "lib")
    bindings = [SlotBinding(workspace, "launcher", str(checkout))]
    with slot_env_scope(bindings, primary):
        terminal._run_bash("true")
        after = build_subprocess_env({"PATH": "/usr/bin"})

    assert spawned["cwd"] == str(checkout / "lib")
    assert _path(spawned["env"])[0] == prepend
    assert spawned["env"]["ETERNIA_API_BASE"] == "https://api.test"
    assert "ETERNIA_API_BASE" not in after  # the spawn cwd does not outlive its spawn
