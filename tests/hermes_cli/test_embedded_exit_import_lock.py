"""An embedded runtime's exit must not import under a held import lock.

``SessionDB.close()`` (upstream ``hermes_state.py``) releases a registry-shared
instance through a LAZY ``from hermes_state_registry import release``. At
interpreter exit ``SessionDB.__del__`` runs that line while a daemon thread
(auto-title's provider call, the token writer) can be frozen holding the global
import lock, and a module not yet in ``sys.modules`` waits on it forever. The
embedded transport imports the registry up front, so that line is a
``sys.modules`` hit and never takes the lock.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_CHILD = r"""
import _imp, os, sys, threading
import hermes_cli.harness_parts.serve.in_memory  # the embedded transport the host app loads
held = threading.Event()
def hold():
    _imp.acquire_lock()  # a daemon thread frozen mid-import at exit
    held.set()
    threading.Event().wait()
threading.Thread(target=hold, daemon=True).start()
held.wait()
from hermes_state_registry import release  # SessionDB.close()'s lazy import
print("RELEASED", flush=True)
os._exit(0)
"""


def test_the_embedded_transport_loads_the_registry_close_imports_lazily():
    try:
        proc = subprocess.run([sys.executable, "-c", _CHILD], cwd=REPO_ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=20)
    except subprocess.TimeoutExpired as exc:  # the hang itself
        raise AssertionError("SessionDB.close()'s lazy import waited on a held import lock") from exc
    assert proc.returncode == 0 and "RELEASED" in proc.stdout, proc.stderr[-3000:]
