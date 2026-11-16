"""FH-ONE-HOST-TOOL-RESOLVER: ``agent_runtime.host_tools`` — which git this host runs, and whether it runs.

The phone case is the one h12 left as a guess (w1115e-h12, RT-REKEY-BRAIN-AND-WORKTREES-FOLLOW): on the
phone wheel ``agent_runtime.git_cmd`` is a loud stand-in (``loop_tool_lifecycles``), and the re-key's old
``realm_rekey_git.git_runs`` asked that stand-in, so it raised ``LifecycleNotShipped`` instead of
answering — reproduced 2026-11-15 (w1115e-dz11) in a child with the door switched off, as below. The
resolver answers False there, and the re-key's git step has nothing to do.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime import host_tools

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_pm_cache():
    host_tools._pm_git.cache_clear()
    yield
    host_tools._pm_git.cache_clear()


def _fake_pm(monkeypatch, binary: str | None, calls: list[str]):
    import pm

    class _Installed:
        def __init__(self, path):
            self.binary = Path(path) if path else None

    def installed_package(name, **_kwargs):
        calls.append(name)
        return _Installed(binary) if binary else None

    monkeypatch.setattr(pm, "installed_package", installed_package)


def test_on_windows_pm_git_is_the_command_and_the_resolution_says_so(monkeypatch, tmp_path):
    calls: list[str] = []
    pm_git = str(tmp_path / "cmd" / "git.exe")
    _fake_pm(monkeypatch, pm_git, calls)
    monkeypatch.setattr(host_tools.sys, "platform", "win32")

    assert host_tools.git_command() == pm_git
    resolution = host_tools.git_resolution()
    assert (resolution.command, resolution.source, resolution.found) == (pm_git, "pm", True)
    assert calls == ["git"]  # cached per data root: the second ask did not read PM again


def test_off_windows_pm_is_never_read_and_the_bare_name_runs_on_the_callers_path(monkeypatch):
    calls: list[str] = []
    _fake_pm(monkeypatch, "/pm/git", calls)
    monkeypatch.setattr(host_tools.sys, "platform", "linux")

    assert host_tools.git_command() == "git"
    assert calls == []


def test_the_path_answer_and_a_missing_git_are_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setattr(host_tools.sys, "platform", "linux")
    fake = tmp_path / "git"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)

    found = host_tools.git_resolution(path=str(tmp_path))
    assert (found.command, found.source) == (str(fake), "PATH")
    missing = host_tools.git_resolution(path="")
    assert (missing.command, missing.source, missing.found) == ("git", "missing", False)


def test_git_runs_answers_false_for_a_git_that_cannot_start(monkeypatch, tmp_path):
    monkeypatch.setattr(host_tools, "git_command", lambda: str(tmp_path / "no-such-git"))
    assert host_tools.git_runs() is False


_PHONE_CHILD = r'''
import json, sys
from pathlib import Path
OFF = ("agent_runtime.git_cmd",)

class Absent:
    def find_spec(self, name, path=None, target=None):
        if name in OFF or name.startswith(tuple(m + "." for m in OFF)):
            raise ModuleNotFoundError(f"switched off: {name}", name=name)

sys.meta_path.insert(0, Absent())
from agent_runtime.loop_tool_lifecycles import ensure_lifecycle_placeholders
out = {"placed": sorted(m for m in ensure_lifecycle_placeholders() if m in OFF)}
from agent_runtime import host_tools, realm_rekey_git
out["git_runs"] = host_tools.git_runs()
out["source"] = host_tools.git_resolution().source

class Mapping:
    workspaces = {"ws_old": "ws_new"}
    agents = {}
    def forms(self):
        return {"ws_old": "ws_new"}

try:
    realm_rekey_git.step_git(Path(sys.argv[1]), Mapping())
    out["step_git"] = "skipped"
except Exception as exc:
    out["step_git"] = type(exc).__name__
print(json.dumps(out))
'''


def test_on_the_phone_wheel_git_does_not_run_and_the_rekey_git_step_skips(tmp_path):
    """Killing mutations (recorded in the commit): drop the ``shipped(GIT_DOOR)`` check in
    ``git_runs`` -> ``git_runs`` is True on this box's PATH git; restore the old door-asking
    ``realm_rekey_git.git_runs`` -> ``step_git`` raises ``LifecycleNotShipped``."""
    proc = subprocess.run(
        [sys.executable, "-c", _PHONE_CHILD, str(tmp_path)], cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=240, check=False,
        env={**os.environ, "HERMES_HOME": str(tmp_path / "home"), "PYTHONPATH": str(REPO_ROOT)})
    assert proc.returncode == 0, proc.stderr[-4000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out == {"placed": ["agent_runtime.git_cmd"], "git_runs": False, "source": "not_shipped",
                   "step_git": "skipped"}


def test_on_desktop_git_runs_through_the_resolved_command():
    """Positive control for the phone case: this box ships the door and has a git."""
    assert host_tools.git_runs() is True
    assert host_tools.git_resolution().found is True
