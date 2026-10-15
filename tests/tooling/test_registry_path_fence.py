"""Only the installer-owned Hermes root may put its ``bin`` on the user PATH (owner decision 2026-10-03).

``hermes_cli/_registry_write_fence.py``'s PATH fence is always on: ``hermes_bootstrap``
installs it in every process that is not already fully fenced. It refuses a user-``Path``
write that ADDS an entry under the process's Hermes root unless that root is the native
one or the persisted ``HERMES_HOME``'s.

No test here writes the registry: the policy is called directly with explicit roots, and
the child cases raise a SYNTHETIC ``winreg.SetValue`` audit event (``sys.audit``), which
reaches the hook and nothing else.

Mutation: make ``install`` return ``None`` when the full fence is not requested (fence off by
default again) -> ``test_a_bootstrapped_child_refuses_a_custom_root_bin`` is red.
Mutation: drop ``if root in owned: return None`` -> both positive controls are red.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli import _registry_write_fence as fence
from tests._downstream.registry_write_fence import CHILD_FENCE_ENV

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A native root, an operator-chosen persisted home, and a QA seeded home, all under tmp."""
    local = tmp_path / "LocalAppData"
    native = local / "hermes"
    operator = tmp_path / "Eternia" / ".hermes"
    qa = tmp_path / "Temp" / "qa-seeded" / "home"
    for path in (native, operator, qa):
        path.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("HERMES_DATA_DIR_SUFFIX", "")
    monkeypatch.setattr(fence, "_persisted_user_home", lambda: str(operator))
    return {"native": native, "operator": operator, "qa": qa}


def _adding(root: Path) -> tuple[str, str]:
    current = r"C:\Windows;C:\Tools"
    return f"{root / 'bin'};{current}", current


def _refusal(machine, root: Path, monkeypatch, new=None, current=None):
    monkeypatch.setenv("HERMES_HOME", str(root))
    new_value, current_value = _adding(root) if new is None else (new, current)
    return fence.path_write_refusal(new_value, current_value)


def test_the_native_root_registers(machine, monkeypatch):
    # Positive control: same write shape as the refused case, the root is the native one.
    assert _refusal(machine, machine["native"], monkeypatch) is None


def test_the_persisted_custom_home_registers(machine, monkeypatch):
    # Positive control: the operator's install keeps its custom home, recorded for the user.
    assert _refusal(machine, machine["operator"], monkeypatch) is None


@pytest.mark.parametrize("which", ["qa", "temp-profile"])
def test_a_seeded_or_temp_root_is_refused(machine, monkeypatch, which, caplog):
    # A profile home under a custom root resolves to that root: <root>/profiles/<name> -> <root>.
    home = machine["qa"] if which == "qa" else machine["qa"].parent / "profiles" / "worker"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    new_value, current = _adding(home if which == "qa" else machine["qa"].parent)
    reason = fence.path_write_refusal(new_value, current)
    assert reason is not None and "not installer-owned" in reason, reason

    with caplog.at_level(logging.WARNING, logger=fence.__name__):
        with pytest.raises(PermissionError, match="PATH fence"):
            fence._refuse_foreign_path_write("winreg.SetValue", (0, "Path", 2, new_value))
    assert "not installer-owned" in caplog.text


def test_what_a_custom_root_may_still_write(machine, monkeypatch):
    qa_bin = str(machine["qa"] / "bin")
    # Removing its own stale entry, re-writing an entry already there, an entry outside the root.
    assert _refusal(machine, machine["qa"], monkeypatch, new=r"C:\Tools", current=rf"{qa_bin};C:\Tools") is None
    assert _refusal(machine, machine["qa"], monkeypatch, new=rf"{qa_bin};C:\Tools", current=rf"C:\Tools;{qa_bin}") is None
    assert _refusal(machine, machine["qa"], monkeypatch, new=r"C:\Node;C:\Tools", current=r"C:\Tools") is None
    # Another value name is not the PATH.
    fence._refuse_foreign_path_write("winreg.SetValue", (0, "probe", 1, qa_bin))


_CHILD = (
    "import sys\n"
    "sys.path.insert(0, {root!r})\n"
    "import hermes_bootstrap\n"
    "try:\n"
    "    sys.audit('winreg.SetValue', 0, 'Path', 2, sys.argv[1] + ';C:\\\\Tools')\n"
    "except PermissionError as exc:\n"
    "    print('REFUSED', exc)\n"
    "else:\n"
    "    print('PASSED')\n"
)


def _child(env: dict, entry: Path) -> str:
    code = _CHILD.format(root=str(ROOT))
    done = subprocess.run([sys.executable, "-c", code, str(entry)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _child_env(tmp_path: Path, hermes_home: Path | None) -> dict:
    env = {name: value for name, value in os.environ.items() if name not in (CHILD_FENCE_ENV, "HERMES_HOME")}
    env["LOCALAPPDATA"] = str(tmp_path / "LocalAppData")
    env["HERMES_DATA_DIR_SUFFIX"] = ""
    if hermes_home is not None:
        env["HERMES_HOME"] = str(hermes_home)
    return env


@pytest.mark.platforms("windows")
def test_a_bootstrapped_child_refuses_a_custom_root_bin(tmp_path):
    home = tmp_path / "Temp" / "qa-seeded" / "home"
    home.mkdir(parents=True)
    out = _child(_child_env(tmp_path, home), home / "bin")
    assert out.startswith("REFUSED PATH fence"), out


@pytest.mark.platforms("windows")
def test_the_same_child_passes_the_native_root_bin(tmp_path):
    # Positive control: identical child bytes, the one variable is which root is registered.
    native = tmp_path / "LocalAppData" / "hermes"
    native.mkdir(parents=True)
    out = _child(_child_env(tmp_path, None), native / "bin")
    assert out == "PASSED", out
