"""Spawn the resident snapshot worker, the way the conversations worker is spawned."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .peer import SnapshotPeer

__layer__ = "lanes"

#: The ``HERMES_SPAWN`` purpose and the process-registry row's name.
SPAWN_PURPOSE = "snapshot-worker"


def start_worker(home: Path) -> SnapshotPeer:
    """Start one worker for the served profile ``home``; its first build pays the imports."""

    from tools.environments.local import served_profile_child_env
    from hermes_cli.local_runtime.processes import spawn_server
    from hermes_cli.process_identity import spawn_env, register_child

    environment = served_profile_child_env(target_home=home, inherit_credentials=True)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment.update(spawn_env(SPAWN_PURPOSE))
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    process, containment = spawn_server(
        [sys.executable, "-u", "-m", "agent_runtime.snapshot_worker.entry"],
        cwd=Path(__file__).resolve().parents[2], env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        **options,
    )
    try:
        peer = SnapshotPeer(process, receive=lambda _frame: None, lost=lambda: None,
                            containment=containment)
    except Exception:
        if containment is not None:
            containment.close()
        process.kill()
        process.wait(timeout=10)
        raise
    register_child(process.pid, SPAWN_PURPOSE)
    return peer


def subprocess_worker_enabled() -> bool:
    """``snapshot.subprocess_worker`` -- default: whatever ``conversations.subprocess_worker`` is.

    One rule (ruling R8): a profile that may start no conversation subprocess starts no
    snapshot subprocess either, and builds in process exactly as before.
    """

    from hermes_cli.config import config_switch

    from agent_runtime.conversations.worker import subprocess_worker_enabled as conversations_on

    return config_switch("snapshot", "subprocess_worker", default=conversations_on())
