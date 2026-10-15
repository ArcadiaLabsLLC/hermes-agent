"""Fork: a ``-I`` child interpreter inherits this process's bytecode cache prefix (runtime R259/R497).

Killing mutations: ``bytecode_cache_flags`` returns ``[]`` -> the runtime test
and both spawn-site tests red; a spawn site reverted to ``[python, "-I", ...]``
-> that site's test reds.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from hermes_cli import sqlite_runtime
from hermes_cli.child_interpreter import child_python_argv
from hermes_cli.local_runtime import devices

_PRINT_PREFIX = ["-c", "import sys; print(sys.pycache_prefix)"]


def test_an_isolated_child_ignores_the_environment_variable(tmp_path):
    # Positive control for the defect: -I drops PYTHONPYCACHEPREFIX.
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(tmp_path)}
    out = subprocess.run([sys.executable, "-I", *_PRINT_PREFIX], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "None"


def test_the_built_argv_carries_the_prefix_into_an_isolated_child(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path))
    out = subprocess.run([*child_python_argv(sys.executable, "-I"), *_PRINT_PREFIX],
                         capture_output=True, text=True, check=True)
    assert Path(out.stdout.strip()) == tmp_path


def test_no_prefix_adds_no_flags(monkeypatch):
    monkeypatch.setattr(sys, "pycache_prefix", None)
    assert child_python_argv("py", "-I") == ["py", "-I"]


def _capture(monkeypatch, module) -> list[list[str]]:
    seen: list[list[str]] = []

    def run(argv, **_kwargs):
        seen.append(list(argv))
        return SimpleNamespace(returncode=1, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    return seen


def test_the_device_probe_child_carries_the_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path))
    seen = _capture(monkeypatch, devices)
    devices.probe_devices(tmp_path, "vulkan")
    assert seen and seen[0][1:4] == ["-X", f"pycache_prefix={tmp_path}", "-I"]


def test_the_sqlite_probe_child_carries_the_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "pycache_prefix", str(tmp_path))
    seen = _capture(monkeypatch, sqlite_runtime)
    sqlite_runtime.probe_sqlite_runtime(sys.executable)
    assert seen and seen[0][1:4] == ["-X", f"pycache_prefix={tmp_path}", "-I"]
