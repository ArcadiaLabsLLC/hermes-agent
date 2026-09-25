"""Test seams: helpers only tests call, moved out of production.

Each one was a production function with no production caller (the dead-code
queue's TEST SEAM class, ``Harness_Brain/20 — Active Initiatives/
dead-code-burn-down-queue.md``). It reaches into the module it serves and does
exactly what the production copy did; the tombstone registry keeps the
production name from growing back.
"""

from __future__ import annotations

__all__ = ["active_workspace_lifts", "chat_live_log_failures", "reset_unreadable_instance_rows"]


def reset_unreadable_instance_rows() -> None:
    """Forget the persona-instance re-mint history, as a fresh process would.

    Same shape and same reason as ``core_cache.reset_process_state``: a property
    of the PROCESS has to be resettable for a test to exercise a second
    process's behaviour without spawning one — and, here, so that one case's
    corrupt row cannot silence the next case's first legitimate repair when the
    two happen to resolve the same path.
    """

    from agent_runtime.persona_assignments import scan

    with scan._unreadable_instance_lock:
        scan._unreadable_instance_rows.clear()


def active_workspace_lifts(realm):
    """The lift markers that currently say "this id is NOT deleted"."""

    from agent_runtime.store.ledgers import workspace_lift_is_active

    return [lift for lift in (getattr(realm, "workspace_lifts", None) or []) if workspace_lift_is_active(lift)]


def chat_live_log_failures() -> int:
    """How many live-log mirror writes failed in this process (0 when healthy).

    The tally itself stays in production (``chat_live_log.files._failures``,
    bumped by ``_note_failure`` next to the once-per-process log line); only
    this reader moved — no production surface ever read it.
    """

    from agent_runtime.chat_live_log import files

    with files._state_lock:
        return files._failures
