"""Fork: ``PythonEnvironment.sync`` re-runs a ``uv sync`` that failed only on a Windows sharing
violation (runtime R749: ``failed to remove directory ...pillow_heif-1.6.0.data ... os error 32``).

Killing mutation: drop the ``_retry_sync_on_sharing_violation`` line from ``sync`` ->
``test_a_sharing_violation_is_retried_until_the_sync_succeeds`` raises InstallError.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import pm.environment as environment_mod
from pm.environment import PythonEnvironment

LOCKED = ("error: Failed to install: pillow_heif-1.6.0-cp314-cp314-win_amd64.whl\n"
          "  Caused by: failed to remove directory `env\Lib\site-packages\pillow_heif-1.6.0.data`: "
          "The process cannot access the file because it is being used by another process. (os error 32)")


def _environment(tmp_path, monkeypatch, outcomes: list[tuple[int, str]]) -> tuple[PythonEnvironment, list]:
    calls: list = []

    def run(self, args, *, cwd, timeout):
        calls.append(list(args))
        code, stderr = outcomes[min(len(calls), len(outcomes)) - 1]
        return subprocess.CompletedProcess(args, code, "", stderr)

    monkeypatch.setattr(PythonEnvironment, "_run", run)
    monkeypatch.setattr(environment_mod, "_SHARING_VIOLATION_RETRY_DELAYS", (0.0, 0.0))
    env = PythonEnvironment(uv=Path("uv"), python=Path(sys.executable), destination=tmp_path / "env",
                            cache=tmp_path / "cache", env={})
    return env, calls


def test_a_sharing_violation_is_retried_until_the_sync_succeeds(tmp_path, monkeypatch):
    environment, calls = _environment(tmp_path, monkeypatch, [(2, LOCKED), (0, "")])
    environment.sync(tmp_path, extras=["anthropic"])
    assert len(calls) == 2 and calls[0] == calls[1]


def test_a_persistent_sharing_violation_still_fails_after_the_retries(tmp_path, monkeypatch):
    environment, calls = _environment(tmp_path, monkeypatch, [(2, LOCKED)])
    with pytest.raises(environment_mod.InstallError, match="os error 32"):
        environment.sync(tmp_path)
    assert len(calls) == 3


def test_any_other_failure_is_not_retried(tmp_path, monkeypatch):
    # Positive control: the retry keys on the sharing violation only.
    environment, calls = _environment(tmp_path, monkeypatch, [(2, "error: No solution found")])
    with pytest.raises(environment_mod.InstallError):
        environment.sync(tmp_path)
    assert len(calls) == 1
