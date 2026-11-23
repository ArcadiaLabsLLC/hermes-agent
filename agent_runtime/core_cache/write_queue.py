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
from concurrent.futures import Future, ThreadPoolExecutor

from agent_runtime.core_cache.models import CoreFingerprint

__layer__ = "stores"

__all__ = ["drain_write_backs", "write_back_off_path"]

_LOCK = threading.Lock()
_EXECUTOR: ThreadPoolExecutor | None = None
_PENDING: list[Future] = []


def _executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="harness-core-cache-write")
    return _EXECUTOR


def write_back_off_path(core: dict, *, fingerprint: CoreFingerprint | None) -> bool:
    """Key the write now (stamp, pre-build key, IC-2 restat), land it on the writer thread.

    ``False`` when the key could not be formed (the same refusals ``write_back``
    receipts); ``True`` once the landing is queued — its own ``ok=`` line follows.
    """

    from agent_runtime.core_cache.persist import land_write_back, prepare_write_back

    prepared = prepare_write_back(core, fingerprint=fingerprint)
    if prepared is None:
        return False
    # The profile scope rides the hop: the landing resolves the store's home
    # exactly as the build that keyed it did.
    context = contextvars.copy_context()
    with _LOCK:
        future = _executor().submit(context.run, land_write_back, prepared)
        _PENDING[:] = [item for item in _PENDING if not item.done()] + [future]
    return True


def drain_write_backs(timeout_s: float = 30.0) -> bool:
    """Wait for every queued landing; ``True`` when none is left running."""

    with _LOCK:
        pending = list(_PENDING)
    for future in pending:
        try:
            future.result(timeout=timeout_s)
        except Exception:  # health: allow BLE001 -- a landing logs its own failure
            return False
    return True
