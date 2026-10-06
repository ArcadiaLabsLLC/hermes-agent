"""Who runs a build: the bound snapshot worker, or this interpreter.

The serve binds a worker once (:func:`bind`, beside its read-model prewarm) and
unbinds it at shutdown. Every led and shadow build goes through
:func:`execute_build`; nothing else in the build path knows a worker exists.
Unbound -- a CLI, a test, a doctor, a profile with the switch off -- it is
today's in-process build, byte for byte.

**Never a lost build.** A worker that died, hung past :data:`BUILD_TIMEOUT_SECONDS`
or sent no core costs one ``snapshot_worker op=lost … fallback=in_process`` receipt
and this request is built in process. A dead or hung worker is replaced on the
next build, at most :data:`RESPAWN_LIMIT` times per serve life; after that the
binding retires (``op=retired``) and the serve builds in process for the rest of
its life. A child whose BUILD raised is kept: the in-process retry raises the same
error where the caller can see it.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent_runtime.snapshot.build_log import EXECUTOR_IN_PROCESS, EXECUTOR_WORKER

from .peer import WorkerLoss, WorkerLost

__layer__ = "lanes"

logger = logging.getLogger(__name__)

#: How long a lead waits for the worker before it is treated as hung. A cold first
#: build measured 15.2-16.1 s and a warm one under a chat window up to 15.8 s.
BUILD_TIMEOUT_SECONDS = 120.0
#: Replacements of a lost worker per serve life; then in process for good.
RESPAWN_LIMIT = 3

#: ``snapshot_worker`` receipts: one family, ``op=`` first, ``pid`` last (BO-3).
WORKER_SPAWN_RECEIPT = "snapshot_worker op=spawn worker_pid=%d spawn_ms=%d respawns=%d pid=%d"
WORKER_LOST_RECEIPT = (
    "snapshot_worker op=lost reason=%s fallback=in_process worker_pid=%s respawns=%d pid=%d"
)
WORKER_RETIRED_RECEIPT = "snapshot_worker op=retired respawns=%d pid=%d"
WORKER_OFF_RECEIPT = "snapshot_worker op=off reason=switch pid=%d"
WORKER_CLOSE_RECEIPT = "snapshot_worker op=close worker_pid=%s builds=%d pid=%d"


@dataclass(frozen=True)
class BuildExecution:
    """A built core and who built it."""

    core: dict
    executor: str
    worker_pid: int | None = None


def _resolution_params() -> dict[str, Any]:
    from agent_runtime.resolution import resolve_runtime

    resolution = resolve_runtime()
    return {
        "store_root": str(resolution.store_root),
        "layer": resolution.layer,
        "hermes_home": resolution.hermes_home,
        "config_path": resolution.config_path,
        "trace": list(resolution.trace),
    }


def _forward(receipts: list) -> None:
    """Write the worker's receipts as this process's own lines (ruling R5)."""

    for row in receipts:
        if not isinstance(row, dict):
            continue
        try:
            level = int(row.get("level", logging.INFO))
            logging.getLogger(str(row.get("logger") or __name__)).log(level, "%s", str(row.get("message", "")))
        except Exception:  # pragma: no cover - an instrument never fails a build
            continue


def _discard(peer) -> None:
    """Kill a lost worker and reap it off the build's thread."""

    def _reap() -> None:
        try:
            peer.process.kill()
        except Exception:
            pass
        try:
            peer.close()
        except Exception:
            pass

    threading.Thread(target=_reap, name="snapshot-worker-reap", daemon=True).start()


class WorkerBinding:
    """One serve's worker: spawned lazily, replaced when lost, retired when it keeps dying."""

    def __init__(self, home: Path, *, start: Callable[[Path], Any] | None = None,
                 timeout: float = BUILD_TIMEOUT_SECONDS) -> None:
        if start is None:
            from .worker import start_worker as start
        self.home = Path(home)
        self._start = start
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._peer = None
        self.spawns = 0
        self.builds = 0
        self.retired = False

    @property
    def respawns(self) -> int:
        return max(0, self.spawns - 1)

    def _live_peer(self):
        with self._lock:
            if self.retired:
                return None
            if self._peer is not None and self._peer.alive:
                return self._peer
            if self._peer is not None:
                _discard(self._peer)
                self._peer = None
            if self.spawns > RESPAWN_LIMIT:
                self.retired = True
                logger.warning(WORKER_RETIRED_RECEIPT, self.respawns, os.getpid())
                return None
            started = time.monotonic()
            self.spawns += 1
            try:
                self._peer = self._start(self.home)
            except Exception:
                logger.warning(WORKER_LOST_RECEIPT, WorkerLoss.SPAWN_FAILED.value, "-",
                               self.respawns, os.getpid(), exc_info=True)
                return None
            logger.info(WORKER_SPAWN_RECEIPT, self._peer.pid,
                        int((time.monotonic() - started) * 1000), self.respawns, os.getpid())
            return self._peer

    def build(self) -> BuildExecution | None:
        """The worker's core, or ``None`` when this request must be built in process."""

        peer = self._live_peer()
        if peer is None:
            return None
        from agent_runtime.snapshot.sections import running_work_for_worker

        params = {"resolution": _resolution_params(), "serve_pid": os.getpid(),
                  "running_work": running_work_for_worker()}
        try:
            reply = peer.build(params, timeout=self.timeout)
        except WorkerLost as lost:
            self._lost(peer, lost.loss)
            return None
        _forward(reply["receipts"])
        self.builds += 1
        return BuildExecution(reply["core"], EXECUTOR_WORKER, peer.pid)

    def _lost(self, peer, loss: WorkerLoss) -> None:
        logger.warning(WORKER_LOST_RECEIPT, loss.value, peer.pid, self.respawns, os.getpid())
        if loss is WorkerLoss.BUILD_ERROR:
            return
        with self._lock:
            if self._peer is peer:
                self._peer = None
        _discard(peer)

    @property
    def worker_pid(self) -> int | None:
        with self._lock:
            return None if self._peer is None else self._peer.pid

    def close(self) -> None:
        with self._lock:
            peer, self._peer = self._peer, None
            self.retired = True
        if peer is not None:
            logger.info(WORKER_CLOSE_RECEIPT, peer.pid, self.builds, os.getpid())
            try:
                peer.close()
            except Exception:  # pragma: no cover - shutdown is best effort
                pass


_binding: WorkerBinding | None = None
_binding_lock = threading.Lock()


def bind(home: Path | None = None, *, start: Callable[[Path], Any] | None = None) -> bool:
    """Route this process's builds to a worker for ``home`` (default: the active home).

    ``False`` -- and every build stays in process -- when ``snapshot.subprocess_worker``
    is off. Idempotent: a second bind keeps the first worker.
    """

    global _binding
    from .worker import subprocess_worker_enabled

    if not subprocess_worker_enabled():
        logger.info(WORKER_OFF_RECEIPT, os.getpid())
        return False
    if home is None:
        from hermes_constants import get_hermes_home

        home = Path(get_hermes_home())
    with _binding_lock:
        if _binding is None or _binding.retired:
            _binding = WorkerBinding(home, start=start)
    return True


def unbind() -> None:
    """Close the worker; later builds run in process. Safe to call when nothing is bound."""

    global _binding
    with _binding_lock:
        binding, _binding = _binding, None
    if binding is not None:
        binding.close()


def bound_binding() -> WorkerBinding | None:
    return _binding


def execute_build() -> BuildExecution:
    """Build the default-store core: in the bound worker if there is one, else here."""

    binding = _binding
    if binding is not None:
        execution = binding.build()
        if execution is not None:
            return execution
    from agent_runtime.snapshot.build import _build_snapshot_uncoalesced

    return BuildExecution(_build_snapshot_uncoalesced(), EXECUTOR_IN_PROCESS, None)
