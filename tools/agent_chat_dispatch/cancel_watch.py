"""The supervisor's cancel watch: a durable cancel another process wrote becomes this process's own cancel.

D1.07 (owner ruling a, 2026-10-10). Cancel is owned by the process that supervises
the work and a non-owner never kills by pid, so a process that does NOT supervise
a dispatch (a second serve on this machine) leaves ``cancel_requested`` on the
row (``dispatch_store.request_dispatch_cancel``) and this watch, running in the
supervising process, turns it into ``local.request_cancel`` — the same
identity-guarded kill and the same settle the owner's own Stop uses.

ONE thread per process, started when a dispatch is supervised and gone when none
is: one indexed read every :data:`CANCEL_POLL_SECONDS` however many dispatches
run. A cross-install row is skipped — its supervisor (``remote.RemoteDispatch``)
reads the mark at its own boundaries, and the far install is asked directly.

Map: ``tools/agent_chat_dispatch/__init__.py``.
"""

from __future__ import annotations

import logging
import threading
import time

from agent_runtime.dispatch_store.supervision import supervised_dispatch_ids

logger = logging.getLogger(__name__)

__layer__ = "lanes"

__all__ = ["CANCEL_POLL_SECONDS", "ensure_cancel_watch", "poll_cancel_requests"]

#: How long a durable cancel waits, at most, for the supervisor to act on it.
CANCEL_POLL_SECONDS = 2.0

_lock = threading.Lock()
_thread: threading.Thread | None = None


def ensure_cancel_watch() -> None:
    """Start the watch unless it runs. Called AFTER a dispatch is marked supervised."""

    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(
            target=_watch, name="agent-chat-dispatch-cancel-watch", daemon=True
        )
        _thread.start()


def _watch() -> None:
    global _thread
    while True:
        time.sleep(CANCEL_POLL_SECONDS)
        with _lock:
            # Checked under the lock ``ensure_cancel_watch`` holds, and a dispatch
            # is marked supervised BEFORE it calls that: either this sees the new
            # id and keeps watching, or it exits first and the caller starts one.
            if not supervised_dispatch_ids():
                _thread = None
                return
        try:
            poll_cancel_requests()
        except Exception:  # noqa: BLE001 - a watch pass must never end the watch
            logger.debug("dispatch cancel watch pass failed", exc_info=True)


def poll_cancel_requests() -> list[str]:
    """One pass: each supervised local row with a durable cancel gets this process's cancel.

    Returns the dispatch ids acted on. A row already carrying this process's own
    mark is skipped, so a kill is asked for once, not once per pass.
    """

    from agent_runtime import dispatch_store

    from .local import _peek_cancel_mark, request_cancel

    supervised = supervised_dispatch_ids()
    if not supervised:
        return []
    acted: list[str] = []
    for row in dispatch_store.cancel_requested_dispatches():
        dispatch_id = str(row.get("dispatch_id") or "")
        if (
            dispatch_id not in supervised
            or row.get("remote_install_id")
            or _peek_cancel_mark(dispatch_id) is not None
        ):
            continue
        request_cancel(dispatch_id, reason=str(row.get("cancel_requested") or "operator_cancel"))
        acted.append(dispatch_id)
    return acted
