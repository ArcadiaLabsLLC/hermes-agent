"""One native engine per served profile, owned by the Hermes service."""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from .native_peer import NativePeer

__layer__ = "lanes"


def start_worker(home: Path, *, receive: Callable[[dict], None],
                 lost: Callable[[], None]) -> NativePeer:
    from tools.environments.local import served_profile_child_env
    from hermes_cli.local_runtime.processes import spawn_server
    from hermes_cli.process_identity import spawn_env, register_child

    environment = served_profile_child_env(target_home=home, inherit_credentials=True)
    environment["PYTHONUNBUFFERED"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment.update(spawn_env("native-conversation"))
    # This interpreter is the selected, already-running Hermes installation.
    # No PATH probe, second install selection, shell or terminal window.
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    process, containment = spawn_server(
        [sys.executable, "-u", "-m", "agent_runtime.conversations.worker_entry"],
        cwd=Path(__file__).resolve().parents[2], env=environment,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        **options,
    )
    try:
        peer = NativePeer(process, receive=receive, lost=lost, containment=containment)
    except Exception:
        if containment is not None:
            containment.close()
        process.kill()
        process.wait(timeout=10)
        raise
    register_child(process.pid, "native-conversation")
    try:
        peer.call("client.capabilities", {"server_requests": True})
    except Exception:
        peer.close()
        raise
    return peer
