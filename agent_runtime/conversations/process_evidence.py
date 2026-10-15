"""PID plus creation time: uncertain receipts do not mistake PID reuse for work.

A subprocess worker's identity is its OS pid and creation time. An in-process
worker (:mod:`.in_process_peer`, the phone profile) has no process of its own,
so it records this process's pid and a per-worker generation instead, and the
evidence for it is the worker itself, looked up in :data:`_IN_PROCESS`.
"""
from __future__ import annotations

import os
import threading
import time
import weakref
from dataclasses import dataclass
from enum import Enum

__layer__ = "lanes"

#: identity -> the live in-process worker holding it (dropped when it is collected).
_IN_PROCESS: "weakref.WeakValueDictionary[tuple[int, float], object]" = weakref.WeakValueDictionary()
_GENERATION_LOCK = threading.Lock()
_last_generation = 0.0


def in_process_identity(worker: object) -> tuple[int, float]:
    """A fresh ``(pid, generation)`` for an in-process worker, registered as its evidence."""
    global _last_generation
    with _GENERATION_LOCK:
        _last_generation = max(time.time(), _last_generation + 1e-3)
        identity = (os.getpid(), _last_generation)
        _IN_PROCESS[identity] = worker
    return identity


def execution_possible(pid: int, created: float) -> bool:
    if pid <= 0 or created <= 0:
        return True
    worker = _IN_PROCESS.get((pid, created)) if pid == os.getpid() else None
    if worker is not None:
        return bool(worker.execution_possible)
    # A generation no longer registered never equals this process's creation time, so
    # the process table below answers False for a collected in-process worker too.
    try:
        import psutil
    except ModuleNotFoundError:
        # No process table (the phone profile ships no psutil): every worker there is
        # in-process, so a foreign pid is a previous app process, and it is gone.
        return False
    try:
        process = psutil.Process(pid)
        return process.create_time() == created and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return True


WORKER_READY_METHOD = "runtime.worker.ready"


class TreeStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ROOT_GONE = "root_gone"
    ROOT_REUSED = "root_reused"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProcessTreeEvidence:
    root: tuple[int, float]
    identities: tuple[tuple[int, float], ...]
    rss_bytes: int | None
    status: TreeStatus


def observe_process_tree(root: tuple[int, float]) -> ProcessTreeEvidence:
    """Observe the owned root and descendants; unavailable RSS is never zero.

    Creation-time checks fence PID reuse before and after each memory read.
    The spawn root remains the containment authority; child identity does not
    replace it. A partial enumeration cannot claim an aggregate RSS.
    """
    import psutil

    def empty(status):
        return ProcessTreeEvidence(root, (), None, status)

    try:
        owner = psutil.Process(root[0])
        if owner.create_time() != root[1]:
            return empty(TreeStatus.ROOT_REUSED)
        processes = [owner, *owner.children(recursive=True)]
    except psutil.NoSuchProcess:
        return empty(TreeStatus.ROOT_GONE)
    except psutil.Error:
        return empty(TreeStatus.UNAVAILABLE)
    identities = []
    rss = 0
    complete = True
    seen = set()
    for process in processes:
        try:
            identity = (process.pid, process.create_time())
            if identity in seen:
                continue
            try:
                memory = process.memory_info().rss
            except psutil.Error:
                memory = 0
                complete = False
            if psutil.Process(process.pid).create_time() != identity[1]:
                complete = False
                continue
            seen.add(identity)
            identities.append(identity)
            rss += memory
        except psutil.Error:
            complete = False
    try:
        if psutil.Process(root[0]).create_time() != root[1]:
            return empty(TreeStatus.ROOT_REUSED)
    except psutil.NoSuchProcess:
        return empty(TreeStatus.ROOT_GONE)
    except psutil.Error:
        return empty(TreeStatus.UNAVAILABLE)
    return ProcessTreeEvidence(root, tuple(identities), rss if complete else None,
                               TreeStatus.COMPLETE if complete else TreeStatus.PARTIAL)


def worker_ready_frame() -> dict:
    """The executing interpreter reports its own existing PID/create-time identity."""
    import psutil

    return {"jsonrpc": "2.0", "method": WORKER_READY_METHOD,
            "params": {"worker_pid": os.getpid(), "worker_created": psutil.Process().create_time()}}
