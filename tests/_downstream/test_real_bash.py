"""``tests/_downstream/real_bash.py``: the Windows rule, with the host injected so it runs anywhere.

Killing mutations (2026-11-08): drop ``"system32"`` from ``_NOT_A_SCRIPT_BASH`` ->
``test_windows_skips_the_wsl_launcher_for_git_bash`` red; return ``found`` before the
``platform`` check is read (always trust PATH) -> the same test red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._downstream.real_bash import real_bash_or_skip, resolve_real_bash

_PF = r"C:\Program Files"


def _which(answer):
    return lambda name: answer if name == "bash" else None


def _only(*present: str):
    wanted = {Path(p) for p in present}
    return lambda candidate: Path(candidate) in wanted


def test_off_windows_the_path_bash_is_real():
    assert resolve_real_bash(platform="linux", which=_which("/usr/bin/bash")) == "/usr/bin/bash"
    assert resolve_real_bash(platform="linux", which=_which(None)) is None


@pytest.mark.parametrize("launcher", [
    r"C:\Windows\System32\bash.exe",
    r"C:\Program Files\WindowsApps\Microsoft.WSL_2\bash.exe",
    None,
])
def test_windows_skips_the_wsl_launcher_for_git_bash(launcher):
    git_bash = str(Path(_PF, "Git", "bin", "bash.exe"))
    got = resolve_real_bash(platform="win32", which=_which(launcher), program_files=_PF, exists=_only(git_bash))
    assert got == git_bash


def test_windows_falls_back_to_git_usr_bin_then_none():
    usr_bash = str(Path(_PF, "Git", "usr", "bin", "bash.exe"))
    launcher = _which(r"C:\Windows\System32\bash.exe")
    assert resolve_real_bash(platform="win32", which=launcher, program_files=_PF, exists=_only(usr_bash)) == usr_bash
    assert resolve_real_bash(platform="win32", which=launcher, program_files=_PF, exists=_only()) is None


def test_windows_keeps_a_real_path_bash():
    msys = r"C:\Program Files\Git\usr\bin\bash.exe"
    assert resolve_real_bash(platform="win32", which=_which(msys), program_files=_PF, exists=_only()) == msys


def test_no_bash_skips_the_caller(monkeypatch):
    monkeypatch.setattr("tests._downstream.real_bash.resolve_real_bash", lambda: None)
    with pytest.raises(pytest.skip.Exception):
        real_bash_or_skip()
