"""Lane h5-boot: fork modules on every hermes boot path do not import what only a live turn uses.

Subprocess probes, because the property is what a FRESH interpreter imports; this test
session has the deferred modules in ``sys.modules`` many times over.

* ``httpx`` (~120 ms with its CLI extras: click, rich, pygments) was imported at module
  scope by ``agent_runtime/stream_gap_receipt.py`` to subclass ``httpx.SyncByteStream``.
  ``progress`` and ``persona_chat_history.trace_rows`` import that module only for
  ``REASONING_USAGE_STEP``, so ``hermes harness status`` and the serve's import-to-ready
  paid it. The subclass is now built on the first response
  (``_timed_byte_stream_class``). Killing mutation: restore the module-scope
  ``import httpx`` — ``test_receipt_readers_do_not_import_httpx`` goes red.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _imported(modules: list[str], probe: list[str], tmp_path: Path) -> dict[str, bool]:
    """Import ``modules`` in a fresh interpreter; report which ``probe`` names it loaded."""

    script = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        + "".join(f"import {name}\n" for name in modules)
        + f"print(json.dumps({{n: n in sys.modules for n in {probe!r}}}))\n"
    )
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HERMES_HOME": str(home), "HERMES_AGENT_RUNTIME_ROOT": str(home / "runtime")}
    env.pop("HERMES_HEAD_HOME", None)
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(PROJECT_ROOT), env=env,
                          capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_receipt_readers_do_not_import_httpx(tmp_path):
    seen = _imported(
        ["agent_runtime.stream_gap_receipt", "agent_runtime.progress", "agent_runtime.persona_chat_history"],
        ["httpx", "agent_runtime.stream_gap_receipt"],
        tmp_path,
    )
    assert seen == {"httpx": False, "agent_runtime.stream_gap_receipt": True}


def test_timed_byte_stream_is_still_an_httpx_sync_stream():
    import httpx

    from agent_runtime.stream_gap_receipt import _timed_byte_stream_class

    timed = _timed_byte_stream_class()
    assert issubclass(timed, httpx.SyncByteStream)
    assert _timed_byte_stream_class() is timed  # one class, so the isinstance re-wrap guard holds
