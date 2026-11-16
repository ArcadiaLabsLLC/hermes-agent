"""An agent's terminal runs the ``hermes`` of the code serving it (RT-AGENT-TERMINAL-HERMES-RUNS-ANOTHER-INSTALL,
RT-TERMINAL-PAYLOAD-HERMES-LOSES-TO-THE-LOGIN-PROFILE). Seam: ``agent_runtime/terminal_pinned_hermes.py``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import tools.environments.local as local
from agent_runtime.terminal_pinned_hermes import front_move_line, pinned_launcher_dir
from tests._downstream.real_bash import real_bash_or_skip

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the login prelude is POSIX bash")


def _launcher(directory: Path, says: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "hermes"
    target.write_text(f"#!/bin/sh\necho {says}\n")
    target.chmod(0o755)
    return target


@pytest.fixture(autouse=True)
def pin_on(monkeypatch):
    monkeypatch.setattr("agent_runtime.terminal_pinned_hermes.PIN_OWN_LAUNCHERS", True)


@pytest.fixture
def fresh_bin_cache(monkeypatch):
    monkeypatch.setattr(local, "_HERMES_BIN_DIR", local._SENTINEL)
    monkeypatch.setattr(local, "_HERMES_BIN_DIR_IS_PAYLOAD", False)


def test_the_suite_runs_with_the_checkout_pin_off(request):
    assert "_terminal_pinned_hermes_off" in request.fixturenames


def test_a_payload_dir_still_wins(tmp_path):
    payload = tmp_path / "payload" / "bin"
    payload.mkdir(parents=True)
    _launcher(tmp_path / "root" / ".hermes" / "bin", "own")
    assert pinned_launcher_dir(payload, tmp_path / "root") == payload


def test_the_checkouts_own_launchers_are_pinned_when_there_is_no_payload(tmp_path):
    own = _launcher(tmp_path / ".hermes" / "bin", "own").parent
    assert pinned_launcher_dir(None, tmp_path) == own


def test_no_published_launcher_pins_nothing(tmp_path):
    (tmp_path / ".hermes" / "bin").mkdir(parents=True)
    assert pinned_launcher_dir(None, tmp_path) is None
    assert pinned_launcher_dir(None, tmp_path / "absent") is None


def test_an_unpinned_dir_adds_no_line():
    assert front_move_line("/opt/x/bin", False) == ""
    assert front_move_line(None, True) == ""
    assert front_move_line("relative/bin", True) == ""


def test_resolve_pins_the_serving_checkouts_launchers(tmp_path, monkeypatch, fresh_bin_cache):
    own = _launcher(tmp_path / "root" / ".hermes" / "bin", "own").parent
    _launcher(tmp_path / "machine", "machine")
    monkeypatch.setattr("agent_runtime.terminal_pinned_hermes.CODE_ROOT_OVERRIDE", tmp_path / "root")
    monkeypatch.setenv("PATH", f"{tmp_path / 'machine'}{os.pathsep}{os.environ.get('PATH', '')}")
    assert local._resolve_hermes_bin_dir() == str(own)
    assert local._HERMES_BIN_DIR_IS_PAYLOAD is True


@posix_only
def test_the_login_profile_does_not_put_another_install_first(tmp_path, monkeypatch, fresh_bin_cache):
    own = _launcher(tmp_path / "root" / ".hermes" / "bin", "own").parent
    machine = _launcher(tmp_path / "machine", "machine").parent
    monkeypatch.setattr(local, "_HERMES_BIN_DIR", str(own))
    monkeypatch.setattr(local, "_HERMES_BIN_DIR_IS_PAYLOAD", True)
    spawn_path = f"{own}:/usr/bin:/bin"
    command = local._append_dropped_path_entries("hermes", spawn_path)
    # What `bash -lic` does: the login profile runs first and prepends the machine install's dir.
    profile = f"PATH={machine}:\"$PATH\"; export PATH\n"
    out = subprocess.run([real_bash_or_skip(), "-c", profile + command], env={"PATH": spawn_path},
                         capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "own", out.stderr
