"""The fork's ``_PendingTurn`` entries satisfy upstream's ``HostSupervisor.has_pending_turn``.

Upstream (v0.22.2) unpacks ``_pending_turns`` values as ``(sid, callback)`` tuples; the fork stores
the ``_PendingTurn`` dataclass. Without the dataclass's ``__iter__`` the probe raises TypeError, which
``methods_session_interrupt`` swallows as "pending" (fail closed) — every interrupt then waits on a
terminal frame that may never come.
"""

from __future__ import annotations

import threading

from tui_gateway.host_supervisor import HostSupervisor, _PendingTurn


def _supervisor(pending):
    supervisor = HostSupervisor.__new__(HostSupervisor)  # __init__ would spawn a child
    supervisor._lock = threading.RLock()
    supervisor._pending_turns = pending
    return supervisor


def test_has_pending_turn_reads_the_forks_pending_turn_entries():
    supervisor = _supervisor({"req-a": _PendingTurn("sid-a", None), "req-b": _PendingTurn("sid-b", None)})

    assert supervisor.has_pending_turn("sid-a") is True
    assert supervisor.has_pending_turn("sid-c") is False
    supervisor._pending_turns.pop("req-a")
    assert supervisor.has_pending_turn("sid-a") is False


def test_pending_turn_unpacks_as_sid_and_callback():
    def complete(frame):
        return None

    sid, callback = _PendingTurn("sid-a", complete)
    assert (sid, callback) == ("sid-a", complete)
