"""Fork-owned half of ``tests/tools/test_async_delegation.py``.

The fork's ``tools.process_registry.ProcessRegistry.restore_durable_completions``
is an EXPLICIT startup step, not an import side effect, so upstream's
``test_real_process_restart_restores_owned_completion_once`` (which drains the
queue straight after the import) cannot pass and is a strict xfail row in
``tests/_downstream/id_markers.py``. This is the same restart E2E with each
child doing what a real entry point does. Upstream's autouse ``_clean_state``
is imported by name.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.tools.test_async_delegation import _clean_state  # noqa: F401 — upstream autouse fixture


def test_real_process_restart_restores_owned_completion_once(tmp_path):
    """Real-import E2E: a fresh interpreter restores a prior process's result.

    The restore is an EXPLICIT startup step, not an import side effect.
    `96cfc09a34` moved `restore_durable_completions()` out of
    `ProcessRegistry.__init__` because the constructor runs when the module is
    imported, so any read-only importer opened (and created) `state.db` and ran
    `recover_abandoned_delegations()` before a verb executed. The entry points
    that own a completion drain — gateway, interactive CLI, TUI gateway,
    harness serve — call it themselves.

    This test kept draining the queue straight after the import, so from that
    day it asserted the old contract and was red everywhere; the tail probe was
    worse than red, because "the queue is empty after the ack" is trivially
    true in a process that never restored anything. Both child programs below
    now do what a real entry point does.
    """
    repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    env = {**os.environ, "HERMES_HOME": str(tmp_path), "PYTHONPATH": repo}
    producer = r'''
import time
from tools import async_delegation as ad
r = ad.dispatch_async_delegation(
    goal="restart", context=None, toolsets=None, role="leaf", model="m",
    session_key="owner-session", parent_session_id="durable-parent",
    runner=lambda: {"status": "completed", "summary": "after restart"},
)
deadline = time.time() + 5
while ad.active_count() and time.time() < deadline:
    time.sleep(.01)
print(r["delegation_id"])
'''
    first = subprocess.run(
        [sys.executable, "-c", producer], cwd=repo, env=env,
        text=True, capture_output=True, timeout=15, check=True,
    )
    delegation_id = first.stdout.strip().splitlines()[-1]

    consumer = r'''
import json
from tools.process_registry import process_registry
# What an entry point that owns a completion drain does at startup.
restored = process_registry.restore_durable_completions()
assert restored == 1, f"expected one restored completion, got {restored}"
evt = process_registry.completion_queue.get_nowait()
print(json.dumps(evt, sort_keys=True))
'''
    second = subprocess.run(
        [sys.executable, "-c", consumer], cwd=repo, env=env,
        text=True, capture_output=True, timeout=15, check=True,
    )
    evt = json.loads(second.stdout.strip().splitlines()[-1])
    assert evt["delegation_id"] == delegation_id
    assert evt["session_key"] == "owner-session"
    assert evt["parent_session_id"] == "durable-parent"
    assert evt["summary"] == "after restart"

    acker = f'''
from tools import async_delegation as ad
assert ad.mark_completion_delivered({delegation_id!r})
'''
    subprocess.run(
        [sys.executable, "-c", acker], cwd=repo, env=env,
        text=True, capture_output=True, timeout=15, check=True,
    )
    # ...and the acked completion is not handed out a second time. The restore
    # has to RUN here or this reads zero for the wrong reason.
    probe_src = (
        "from tools.process_registry import process_registry; "
        "print(process_registry.restore_durable_completions()); "
        "print(process_registry.completion_queue.qsize())"
    )
    probe = subprocess.run(
        [sys.executable, "-c", probe_src],
        cwd=repo, env=env, text=True, capture_output=True, timeout=15, check=True,
    )
    restored_again, remaining = probe.stdout.strip().splitlines()[-2:]
    assert restored_again == "0", "an acked completion was restored again"
    assert remaining == "0"
