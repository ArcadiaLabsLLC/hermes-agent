"""Fork-owned (upstream ships no conftest here): a verify run leaves nothing running.

``run_verify``'s start phase spawns its server through ``process_identity.spawn_owned``, which
starts the process-wide owner-death supervisor (an ``sh`` child and its waiter thread). Releasing
the server's group keeps that supervisor for a 30 s idle grace (``_SUPERVISOR_IDLE_EXIT_S``) on a
timer thread, so all three outlived each ``TestReadiness`` test (row
FH-SEAL-LEFTOVER-THREADS-AND-CHILDREN, seen by the seal 2026-11-16). With no grace the release
closes the supervisor's pipe at once: it exits and its waiter reaps it inside the test.
"""

from __future__ import annotations

import pytest

from hermes_cli import process_identity


@pytest.fixture(autouse=True)
def _owner_death_supervisor_exits_with_its_last_group(monkeypatch):
    monkeypatch.setattr(process_identity, "_SUPERVISOR_IDLE_EXIT_S", 0.0)
