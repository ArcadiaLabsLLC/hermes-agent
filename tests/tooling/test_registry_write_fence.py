"""The registry-write fence (``tests/_downstream/registry_write_fence.py``) is live in a test process.

Synthetic audit events, so no assertion here can touch the registry whichever way it goes.
Mutation: drop ``registry_write_fence.install()`` from ``tests/_downstream/conftest_plugin.py``
-> the first test is red (DID NOT RAISE).
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests._downstream import registry_write_fence

pytestmark = pytest.mark.gate


def test_a_registry_write_is_refused_in_a_test_process(monkeypatch):
    monkeypatch.delenv("HERMES_E2E_WINDOWS_INSTALL", raising=False)
    before = len(registry_write_fence.REFUSED)
    with pytest.raises(PermissionError, match="test fence"):
        sys.audit("winreg.SetValue", 0, "Path", 1, "x")
    assert registry_write_fence.REFUSED[before:] == [
        (registry_write_fence.REFUSED[before][0], "winreg.SetValue")]


def test_a_registry_read_is_not_refused(monkeypatch):
    # Positive control: same door, a read event.
    monkeypatch.delenv("HERMES_E2E_WINDOWS_INSTALL", raising=False)
    sys.audit("winreg.QueryValue", 0, "Path", 1)


def test_the_machine_e2e_suite_owns_the_registry(monkeypatch):
    monkeypatch.setenv("HERMES_E2E_WINDOWS_INSTALL", "1")
    sys.audit("winreg.SetValue", 0, "Path", 1, "x")


# ── a child given a scratch environment (FH-PYTEST-HOME-BIN-LEAKS-INTO-USER-PATH) ──────────────
# Killing mutation (2026-11-08): make ``marked_env`` return *env* unchanged ->
# test_a_scratch_env_child_is_asked_to_fence[kw|positional] red (the child reads False).

_ASKS = ("import sys; sys.path.insert(0, sys.argv[1]); "
         "from hermes_cli._registry_write_fence import requested; print(requested())")


class _FencedPopen(subprocess.Popen):
    """A private subclass, so the wrap under test never touches this process's ``subprocess.Popen``."""


@pytest.mark.parametrize("spelling", ["kw", "positional"])
def test_a_scratch_env_child_is_asked_to_fence(monkeypatch, spelling):
    monkeypatch.delenv("HERMES_E2E_WINDOWS_INSTALL", raising=False)
    registry_write_fence.fence_scratch_child_envs(_FencedPopen)
    root = str(registry_write_fence.__file__).rsplit("tests", 1)[0]
    scratch = {"PATH": os.environ.get("PATH", ""), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    argv = [sys.executable, "-I", "-c", _ASKS, root]
    if spelling == "kw":
        child = _FencedPopen(argv, stdout=subprocess.PIPE, text=True, env=scratch)
    else:
        child = _FencedPopen(argv, -1, None, None, subprocess.PIPE, None, None, True, False, None, scratch, text=True)
    out, _ = child.communicate(timeout=60)
    assert out.strip() == "True"
    assert registry_write_fence.CHILD_FENCE_ENV not in scratch  # the caller's mapping is not mutated


def test_marked_env_leaves_inherit_and_the_e2e_opt_in_alone(monkeypatch):
    monkeypatch.delenv("HERMES_E2E_WINDOWS_INSTALL", raising=False)
    assert registry_write_fence.marked_env(None) is None
    assert registry_write_fence.marked_env({"A": "1"}) == {"A": "1", registry_write_fence.CHILD_FENCE_ENV: "1"}
    monkeypatch.setenv("HERMES_E2E_WINDOWS_INSTALL", "1")
    assert registry_write_fence.marked_env({"A": "1"}) == {"A": "1"}


def test_the_wrap_is_once():
    assert registry_write_fence.fence_scratch_child_envs(_FencedPopen) in (True, False)
    assert registry_write_fence.fence_scratch_child_envs(_FencedPopen) is False
