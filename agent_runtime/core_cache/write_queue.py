"""The cache write-back, off the build's response path.

Row RT-FU-EVERY-AGENT-LIST-BUILD-WAITS-FOR-ITS-CACHE-COPY-TO-REACH-THE-DISK (seen
2026-11-22 on the owner's box): every led build's waiters were released only after
``write_back`` returned — 213-293 ms, 2,272 ms once — while the copy's only reader
is the NEXT process's boot consult. Now the build thread keeps the part whose
timing is load-bearing (the build stamp, the pre-build key and the IC-2 restat,
taken right after the build exactly as before, so a concurrent write cannot be
adopted into the key) and hands the rest — serialize, sidecar, stage, land, reap —
to ONE writer thread, in order — every write still lands, so the convergence
streak counts each build exactly as before.
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections import deque
from collections.abc import Callable

from agent_runtime.core_cache.models import CoreFingerprint
from agent_runtime.core_cache.vocabulary import logger

__layer__ = "stores"

__all__ = ["drain_write_backs", "write_back_off_path"]

#: Guards the queue and the worker handle; notified whenever the queue empties.
_IDLE = threading.Condition(threading.Lock())
_QUEUE: deque[Callable[[], object]] = deque()
#: The writer thread while it has landings to make; it exits when the queue is empty,
#: so an idle serve (and a test that built once) holds no thread for it.
_WORKER: threading.Thread | None = None


def _drain_queue() -> None:
    global _WORKER
    while True:
        with _IDLE:
            if not _QUEUE:
                _WORKER = None
                _IDLE.notify_all()
                return
            landing = _QUEUE.popleft()
        try:
            landing()
        except Exception:  # health: allow BLE001 -- best effort by contract, like write_back
            logger.warning("snapshot_core_cache_write ok=false reason=io", exc_info=True)


def write_back_off_path(core: dict, *, fingerprint: CoreFingerprint | None) -> bool:
    """Key the write now (stamp, pre-build key, IC-2 restat), land it on the writer thread.

    ``False`` when the key could not be formed (the same refusals ``write_back``
    receipts); ``True`` once the landing is queued — its own ``ok=`` line follows.
    """

    from agent_runtime.core_cache.persist import land_write_back, prepare_write_back

    global _WORKER
    prepared = prepare_write_back(core, fingerprint=fingerprint)
    if prepared is None:
        return False
    # The profile scope rides the hop: the landing resolves the store's home
    # exactly as the build that keyed it did.
    context = contextvars.copy_context()
    with _IDLE:
        _QUEUE.append(lambda: context.run(land_write_back, prepared))
        if _WORKER is None:
            _WORKER = threading.Thread(target=_drain_queue, name="harness-core-cache-write")
            _WORKER.start()
    return True


def drain_write_backs(timeout_s: float = 30.0) -> bool:
    """Wait for every queued landing; ``True`` when none is left to make."""

    deadline = time.monotonic() + timeout_s
    with _IDLE:
        while _WORKER is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _IDLE.wait(remaining)
    return True
