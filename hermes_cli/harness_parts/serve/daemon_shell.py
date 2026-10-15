"""The desktop serve's daemon shell: the pid registry, its sidecars, the git build stamp, the token.

The concerns a serve owns BECAUSE it is its own OS process (see
:mod:`hermes_cli.harness_parts.serve.shell`). Each method is the call the boot
used to make inline, unchanged — this module moved the call sites behind one
seam; it does not own the stores (``agent_runtime.serve_registry``,
``agent_runtime.serve_auth``, ``agent_runtime.build_stamp`` do).

The phone profile's manifest lists this module as switched off, so its import
closure never reaches the registry (``psutil``) or the git probe.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

__layer__ = "lanes"

__all__ = ["DaemonShell"]


class DaemonShell:
    kind = "daemon"

    def refuse_levers(self, *, socket_lane: bool, service: bool, record_end_reason: bool,
                      parent_pid: int | None) -> None:
        return None  # a daemon honours every process lever

    def build_block(self) -> dict[str, Any]:
        from agent_runtime.build_stamp import build_stamp

        return build_stamp().frame_payload()

    def version_build(self) -> dict[str, Any]:
        from agent_runtime.build_stamp import build_stamp

        return build_stamp().payload()

    def auth_block(self, store_root: Path) -> dict[str, Any]:
        from agent_runtime.serve_auth import ensure_token

        return ensure_token(store_root).payload()

    def register_instance(self, store_root: Path, **row: Any) -> dict[str, Any]:
        from agent_runtime.serve_registry import register_serve_instance

        return register_serve_instance(store_root, **row).payload()

    def unregister_instance(self, store_root: Path) -> tuple[bool, Path | None]:
        from agent_runtime.serve_registry import serve_instance_path, unregister_serve_instance

        row_path = serve_instance_path(store_root, os.getpid())
        return bool(unregister_serve_instance(store_root)), row_path

    def open_stderr_log(self, store_root: Path, *, boot_id: str, build: dict[str, Any]) -> Any:
        from agent_runtime.serve_registry import open_serve_stderr_log

        return open_serve_stderr_log(store_root, boot_id=boot_id, build=build)

    def prune_stale_instances(self, store_root: Path, *, emit: Callable[[dict[str, Any]], None],
                              boot_id: str) -> dict[str, Any]:
        from agent_runtime.serve_registry import prune_stale_serve_instances

        return prune_stale_serve_instances(store_root, emit=emit, boot_id=boot_id)

    def prune_ended(self, store_root: Path) -> None:
        from agent_runtime.serve_registry import prune_serve_ended

        prune_serve_ended(store_root)
