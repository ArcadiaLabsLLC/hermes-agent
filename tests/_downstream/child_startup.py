"""The session chain's hand-off to the hermes children a test spawns (fork-owned, test-only).

Row "every hermes child the e2e/native tests spawn repeats provider discovery and the git
version lookup" (fork-hygiene-queue, q-chain 2026-10-18). :func:`install` runs once per test
process, at import of ``conftest_plugin``, and puts two things in ``os.environ`` that every
spawned child inherits (the served-profile child env keeps both):

* ``PYTHONPATH`` gains ``tests/_downstream/child_site``, whose ``sitecustomize`` installs the
  child-side shortcut (see that module's docstring);
* ``HERMES_TEST_CHILD_STARTUP`` names the snapshot directory, this checkout's
  ``.pytest_cache/hermes-child-startup``: the version info and the parsed bundled manifests,
  recorded by the first child that resolves them, keyed by HEAD's commit and each manifest's
  ``(mtime_ns, size)``, re-used by every later child of every session on this checkout.

And it takes one thing out: ``PYTHONDONTWRITEBYTECODE`` (agent shells export it), so this process
and every child write the ``.pyc`` they compile. Both runners already drop it (``run_tests.sh``'s
``env -i``, ``run_tests_bundled.prepare_child_environ``); a ``python -m pytest <file>`` from such
a shell did not, and on a checkout without bytecode each ``hermes harness --help`` child then
compiled its whole import graph every time: 5.0-5.7 s against 2.0-2.1 s once written (lane
w2-speed-b, 2026-10-18, ``RT-TEST-VENV-PURE-YAML``).

Nothing here imports production code; a process that never spawns a child pays two env writes.
Pinned by ``tests/test_child_startup_downstream.py`` and the chain contract
``tests/tooling/test_session_chain_contract.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ENV = "HERMES_TEST_CHILD_STARTUP"
CHILD_SITE = Path(__file__).resolve().parent / "child_site"
SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / ".pytest_cache" / "hermes-child-startup"


def install(environ=os.environ, snapshot_dir: Path = SNAPSHOT_DIR) -> None:
    parts = [p for p in environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if str(CHILD_SITE) not in parts:
        environ["PYTHONPATH"] = os.pathsep.join([str(CHILD_SITE), *parts])
    environ.setdefault(ENV, str(snapshot_dir))
    environ.pop("PYTHONDONTWRITEBYTECODE", None)
    if environ is os.environ:
        sys.dont_write_bytecode = False
