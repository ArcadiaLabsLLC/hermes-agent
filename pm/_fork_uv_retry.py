"""Fork-owned: re-run a ``uv`` call that failed only on a Windows sharing violation.

Ledger row ``pm/environment.py`` (runtime R749, ``a7f6e167ef9``): ``PythonEnvironment.sync`` hands
its result here through one call line. Windows "file in use" while uv unpacks a wheel into a fresh
environment (``failed to remove directory ...pillow_heif-1.6.0.data ... os error 32``, twice on
2026-10-15): an on-access scanner holding the just-written tree is the leading suspect; the sync is
idempotent, so a short wait and a re-run finishes it. ``pm/_fork_extend_environment.py`` reuses it
for its in-place ``pip install``. Pinned by ``tests/pm/test_uv_sync_sharing_violation.py``.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

__all__ = ["retry_sync_on_sharing_violation"]

SHARING_VIOLATION_MARKERS = ("os error 32",)
SHARING_VIOLATION_RETRY_DELAYS = (2.0, 5.0)


def retry_sync_on_sharing_violation(run, command: list[str], source: Path, timeout: int,
                                    result: subprocess.CompletedProcess,
                                    *, sleep=None) -> subprocess.CompletedProcess:
    """Re-run a ``uv sync`` that failed only on a Windows sharing violation; else ``result``."""
    pause = time.sleep if sleep is None else sleep
    for delay in SHARING_VIOLATION_RETRY_DELAYS:
        output = " ".join((result.stderr or "", result.stdout or "")).lower()
        if not result.returncode or not any(marker in output for marker in SHARING_VIOLATION_MARKERS):
            return result
        pause(delay)
        result = run(command, cwd=source, timeout=timeout)
    return result
