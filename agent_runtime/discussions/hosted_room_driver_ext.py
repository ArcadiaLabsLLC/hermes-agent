"""Group Chat independent-member observation for the hosted-room runtime — fork-owned.

``request_reconciliation`` and ``_observe_independent_members`` moved here unchanged from the
upstream ``tui_gateway/hosted_room_driver.py`` (footprint audit 2026-10-15, lane G) as
:class:`HostedRoomIndependentMembersMixin`; ``HostedRoomRuntime`` takes them through the one
``@with_independent_members`` decorator line (a decorator, not a base class, so the upstream
``class`` line stays byte-identical and the seam costs no deleted line).
The ``independent`` branches in ``_scan_room`` / ``_execute_attempt``, ``stop_unresolved``,
``inspection.active`` and the receipt's ``error`` field stay upstream-side (doors J1/J3 of
``docs/agent-runtime-harness/planned/upstream-doors-2026-10-06.md``, issue #125258).

The methods run on a ``HostedRoomRuntime`` and read its own state and helpers through ``self``.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict
from typing import TYPE_CHECKING

from gateway import hosted_room_driver as state

if TYPE_CHECKING:
    from tui_gateway.hosted_room_driver import HostedRoomBinding

__layer__ = "lanes"


class HostedRoomIndependentMembersMixin:
    """Host reconciliation and independent-member receipts on ``HostedRoomRuntime``."""

    def request_reconciliation(self, identity: state.TaskIdentity) -> None:
        """A host has fresh evidence for this exact task (for example a human answer).

        Invalidate only its negative recovery observation, not its durable lease
        or generation. The existing worker still decides whether it can settle.
        """
        for key in tuple(self._inspected_indeterminate_attempts):
            if key[:2] == (identity.room_id, identity.task_id):
                self._inspected_indeterminate_attempts.discard(key)
        self.wakeup()

    def _observe_independent_members(self, binding: HostedRoomBinding, lease: state.DriverLease) -> None:
        """Observe the same task receipts without parking a room on one member."""
        for task in self._tasks(binding, "running"):
            if not task["payload"].get("independent", False):
                continue
            lease = self._renew_lease_if_needed(lease)
            if self.clock() >= float(task["started_at"]) + self.turn_timeout_seconds:
                self._expire_attempt_deadline(binding, task, lease)
                continue
            inspection = self._inspect_recovery_session(binding, task)
            if inspection.terminal is not None:
                attempt = state.TaskAttempt(identity=task["identity"], lease=lease,
                    execution_generation=task["execution_generation"],
                    cancel_generation=task["cancel_generation"])
                with suppress(state.StaleTaskError):
                    self._publish(binding, state.settle_task(self.db_path, attempt,
                        **asdict(inspection.terminal), clock=self.clock))


_METHODS = ("request_reconciliation", "_observe_independent_members")


def with_independent_members(cls: type) -> type:
    """Class decorator: give ``cls`` the mixin's methods; refuse to shadow one it already has.

    A same-named method arriving from upstream is a merge conflict to resolve, never a silent
    override, so the decorator raises instead of choosing.
    """
    for name in _METHODS:
        if name in cls.__dict__:
            raise TypeError(f"{cls.__name__} already defines {name}; resolve the upstream overlap")
        setattr(cls, name, HostedRoomIndependentMembersMixin.__dict__[name])
    return cls
