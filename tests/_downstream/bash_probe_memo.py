"""A bash.exe that started once is not probed again in the same test process (suite speed, lane r-state).

``pm.shell.bash()`` (upstream) proves each Windows candidate with a ``bash -c "exit 0"``
spawn on EVERY call, and ``tools.environments.local._find_bash`` calls it for every
command, so every local-backend command costs two bash spawns. Measured 2026-10-18:
``tests/tools/test_known_file_write_baseline.py::test_own_patch_after_own_write_keeps_the_baseline``
ran 35 spawns, half of them the probe, ~0.35 s each; the v4a test ran 32 s against the
30 s per-test timeout.

The memo keeps only a candidate that STARTED, keyed by its path, for the life of the test
process. It steps aside whenever ``subprocess.run`` is not the one standing at setup (the
live-system guard's wrapper), so a test that fakes the probe's outcome still sees its fake, and a candidate that failed is probed
again every time. Production keeps upstream's per-call probe (a runtime-queue row in
``Upstream-owned`` names it).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

_STARTED: set[str] = set()


def _memoized(original, baseline_run):
    def bash_starts_memoized(candidate: str) -> bool:
        if subprocess.run is not baseline_run:  # the test replaced it: its fake decides
            return original(candidate)
        if candidate in _STARTED:
            return True
        started = original(candidate)
        if started:
            _STARTED.add(candidate)
        return started

    bash_starts_memoized.__wrapped__ = original
    return bash_starts_memoized


@pytest.fixture(autouse=True)
def _bash_probe_memo(monkeypatch, _live_system_guard):
    """After the live-system guard, whose ``subprocess.run`` wrapper is the baseline."""
    shell = sys.modules.get("pm.shell")
    if shell is None:
        if "tools.environments.local" not in sys.modules:
            return  # nothing in this process runs local-backend commands yet
        import pm.shell as shell  # local.py imports it on its first command
    original = getattr(shell, "_bash_starts", None)
    if original is None or getattr(original, "__wrapped__", None) is not None:
        return
    monkeypatch.setattr(shell, "_bash_starts", _memoized(original, subprocess.run))
