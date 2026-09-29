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
