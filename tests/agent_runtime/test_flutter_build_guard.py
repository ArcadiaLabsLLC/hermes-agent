"""The agent ``flutter build`` guard, through the eternia-harness ``pre_tool_call`` hook.

Runtime-queue row (2026-10-01): with the RW4 guidance installed an agent still ran
``flutter build windows --debug`` in the operator's primary Launcher checkout while
that Launcher ran from its Debug output. Every refusal below has its positive
control: the same command, one variable changed, and the call proceeds.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime.flutter_build_guard import flutter_builds
from agent_runtime.machine_roots import machine_roots_cache_clear, write_machine_roots

BUILD = "flutter build windows --debug --target lib/main_marionette.dart"


def _plugin_pre_tool_call():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_build_guard_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registered: dict[str, object] = {}

    class _Ctx:
        def __getattr__(self, name):
            return lambda *a, **k: None

        def register_hook(self, name, callback):
            registered[name] = callback

    module.register(_Ctx())
    return registered["pre_tool_call"]


def _checkout(path: Path, *, worktree: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if worktree:
        (path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    else:
        (path / ".git").mkdir(exist_ok=True)
    (path / "pubspec.yaml").write_text("name: eternia_launcher\n", encoding="utf-8")
    return path


@pytest.fixture
def hook():
    return _plugin_pre_tool_call()


@pytest.fixture
def primary(tmp_path, monkeypatch):
    """The operator's primary checkout, registered as the ``eternia_launcher`` machine root."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    machine_roots_cache_clear()
    root = _checkout(tmp_path / "Launcher Primary")
    write_machine_roots({"eternia_launcher": str(root)}, dry_run=False)
    yield root
    machine_roots_cache_clear()


def _call(hook, command, workdir):
    return hook(tool_name="terminal", args={"command": command, "workdir": str(workdir)}, task_id="t-guard")


def test_a_build_in_the_primary_checkout_is_refused_naming_the_qa_door(hook, primary, tmp_path):
    refused = _call(hook, BUILD, primary)
    assert refused["action"] == "block"
    assert "primary Launcher checkout" in refused["message"]
    assert "mcp_launcher_qa_launch_or_attach" in refused["message"]
    assert "worktree" in refused["message"]
    assert "stagec_parity_build.dart" in refused["message"]

    # Reached through a cd from elsewhere, a sub-package, and the call-operator spelling.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert _call(hook, f'cd "{primary}" && flutter.bat -v build windows', elsewhere)["action"] == "block"
    package = primary / "packages" / "pkg_a"
    package.mkdir(parents=True)
    assert _call(hook, BUILD, package)["action"] == "block"
    assert _call(hook, f'& "C:\\sdk\\flutter\\bin\\flutter.bat" build windows --profile', primary)["action"] == "block"

    # Positive control: the same build in a lane worktree proceeds.
    lane = _checkout(tmp_path / "worktrees" / "lane", worktree=True)
    assert _call(hook, BUILD, lane) is None


def test_a_worktree_nested_inside_the_primary_checkout_is_not_the_primary(hook, primary):
    nested = _checkout(primary / ".claude" / "worktrees" / "lane", worktree=True)
    assert _call(hook, BUILD, nested) is None
    # Positive control: one level up, inside the primary itself, it is refused.
    assert _call(hook, BUILD, primary / ".claude")["action"] == "block"


def test_a_non_build_command_in_the_primary_checkout_passes(hook, primary):
    for command in ("flutter test test/unit", "flutter pub get", "git status",
                    'git commit -m "flutter build fix"', "dart run tool/stagec_parity_build.dart"):
        assert _call(hook, command, primary) is None, command
    # Same tool, other tool name: the guard reads terminal calls only.
    assert hook(tool_name="read_file", args={"command": BUILD, "workdir": str(primary)}, task_id="t") is None
    # Positive control: the build itself, same directory.
    assert _call(hook, BUILD, primary)["action"] == "block"


def _held_binary(directory: Path) -> subprocess.Popen:
    """Run a copied system executable out of ``directory`` until killed."""
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        source = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ping.exe"
        argv_tail = ["-n", "120", "127.0.0.1"]
    else:
        source = Path(shutil.which("sleep") or "/bin/sleep")
        argv_tail = ["120"]
    exe = directory / f"eternia_launcher{'.exe' if os.name == 'nt' else ''}"
    shutil.copy2(source, exe)
    return subprocess.Popen([str(exe), *argv_tail], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS output layout is a bundle; covered on win/linux")
def test_a_build_whose_output_binary_is_running_is_refused(hook, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no_roots_home"))  # no primary bound: this test alone
    machine_roots_cache_clear()
    lane = _checkout(tmp_path / "worktrees" / "qa-lane", worktree=True)
    target = "windows" if os.name == "nt" else "linux"
    debug_dir = (lane / "build" / "windows" / "x64" / "runner" / "Debug") if os.name == "nt" else (
        lane / "build" / "linux" / "x64" / "debug" / "bundle")
    command = f"flutter build {target} --debug"
    process = _held_binary(debug_dir)
    try:
        refused = _call(hook, command, lane)
        assert refused is not None and refused["action"] == "block"
        assert str(process.pid) in refused["message"]
        assert "mcp_launcher_qa_launch_or_attach" in refused["message"]
        # The release build writes runner/Release: a Debug-held Launcher does not block it.
        assert _call(hook, f"flutter build {target} --release", lane) is None
    finally:
        process.kill()
        process.wait(timeout=10)
    # Positive control: same command, same directory, the process gone.
    assert _call(hook, command, lane) is None


def test_the_parser_reads_cd_and_launch_prefixes(tmp_path):
    builds = flutter_builds(f'cd /d "{tmp_path}" ; fvm flutter --suppress-analytics build linux --profile', "X:/base")
    assert [(b.project_dir, b.target, b.mode) for b in builds] == [(tmp_path, "linux", "profile")]
    assert flutter_builds("cmd /c flutter build macos", tmp_path)[0].mode == "release"
    assert flutter_builds("flutter run -d windows", tmp_path) == []
