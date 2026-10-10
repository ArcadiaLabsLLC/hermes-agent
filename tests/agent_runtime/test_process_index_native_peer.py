"""D1.09 S2 — the native conversation worker tree is named in the Launcher's process index.

``conversations.worker.start_worker`` hands ``NativePeer`` a launcher process
whose child is the worker interpreter; a hard serve exit can leave both
running. The peer records the launcher pid at construction and the worker pid
when the worker's identity is bound, and forgets both when it is disposed.

Killing mutation: drop the ``process_index.forget_child`` loop in
``NativePeer._dispose`` -> both entries outlive the close.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import psutil
import pytest

from agent_runtime import process_index
from agent_runtime.conversations.native_peer import NativePeer

#: A launcher that starts one grandchild (the "worker") and exits when its stdin closes.
_LAUNCHER = (
    "import subprocess, sys\n"
    "worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "sys.stdin.read()\n"
    "worker.kill(); worker.wait()\n"
)


def _entry(pid: int) -> dict | None:
    path = process_index.index_directory() / f"{pid}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@pytest.mark.timeout(60)
def test_the_launcher_and_its_worker_are_named_until_the_peer_is_closed(monkeypatch):
    monkeypatch.setattr("hermes_cli.process_identity.register_child", lambda pid, purpose: True)
    process = subprocess.Popen([sys.executable, "-c", _LAUNCHER],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        peer = NativePeer(process, receive=lambda frame: None, lost=lambda: None,
                          worker_purpose="native-conversation")
        assert (_entry(process.pid) or {}).get("purpose") == "hermes_child"

        deadline = time.monotonic() + 30
        children = []
        while not children and time.monotonic() < deadline:
            children = psutil.Process(process.pid).children(recursive=True)
            time.sleep(0.05)
        assert children, "the launcher never started its worker"
        worker = children[0]
        peer.bind_worker_identity({"worker_pid": worker.pid, "worker_created": worker.create_time()})
        assert (_entry(worker.pid) or {}).get("pid") == worker.pid

        peer.close()

        assert _entry(process.pid) is None, "the launcher's entry outlived the close"
        assert _entry(worker.pid) is None, "the worker's entry outlived the close"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
