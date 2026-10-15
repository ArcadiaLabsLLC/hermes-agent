"""The registry-write fence (``tests/_downstream/registry_write_fence.py``) is live in a test process.

Synthetic audit events, so no assertion here can touch the registry whichever way it goes.
Mutation: drop ``registry_write_fence.install()`` from ``tests/_downstream/conftest_plugin.py``
-> the first test is red (DID NOT RAISE).
"""

from __future__ import annotations

import sys

import pytest

from tests._downstream import registry_write_fence


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
