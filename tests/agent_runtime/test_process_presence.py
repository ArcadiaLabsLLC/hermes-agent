"""A terminal background process appends its own START and END to the EventLog.

Row ``RT-EMIT-RUNNING-WORK-CHAT``, plan ``docs/agent-runtime-harness/archive/p10-turn-2026-10-19.md``
§2.4 tests 1-3. The listener rides the additive upstream seam
``ProcessRegistry.add_lifecycle_listener``; these drive a REAL registry spawning
a REAL child, so the chokepoints under test are the ones every spawn and exit
path crosses.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone, UTC

import pytest

from agent_runtime.decision_contract_registry import event_catalog
from agent_runtime.events import EventLog
from agent_runtime.models import Event
from agent_runtime.patch_coverage import batch_is_patch_coverable
from agent_runtime.running_work import process_presence
from agent_runtime.running_work.process_presence import (
    EVENT_PROCESS_ENDED,
    EVENT_PROCESS_STARTED,
)
from agent_runtime.running_work.vocabulary import KIND_TERMINAL
from agent_runtime.state_patches import PATCH_OP_UPSERT, STATE_PATCHED_EVENT_TYPE
from tools.process_registry import ProcessRegistry


def _rows(event_type: str) -> list[Event]:
    return [event for event in EventLog().tail(200) if event.type == event_type]


def _quick_command() -> str:
    return f'"{sys.executable}" -c "pass"'


def _spawn_and_finish(registry: ProcessRegistry):
    session = registry.spawn_local(_quick_command())
    assert session._completion_event.wait(60), "child never finished"
    deadline = time.monotonic() + 10
    while session.id in registry._running and time.monotonic() < deadline:
        time.sleep(0.05)
    return session


def _registry() -> ProcessRegistry:
    registry = ProcessRegistry()
    registry.add_lifecycle_listener(process_presence._on_lifecycle)
    return registry


def test_a_real_spawn_appends_started_then_exactly_one_ended():
    """Killing mutation: notify from ``_move_to_finished`` instead of
    ``_publish_finished``'s ``was_running`` arm → the second (raced) move
    appends a second ``ended`` row."""

    registry = _registry()
    session = _spawn_and_finish(registry)
    # The kill/reconcile race: a second finisher crosses the same chokepoint.
    assert registry._move_to_finished(session) is False

    started = [e for e in _rows(EVENT_PROCESS_STARTED) if e.payload["process_session_id"] == session.id]
    ended = [e for e in _rows(EVENT_PROCESS_ENDED) if e.payload["process_session_id"] == session.id]
    assert len(started) == 1
    assert len(ended) == 1
    assert ended[0].payload["exit_code"] == 0
    assert ended[0].payload["work_id"] == f"{KIND_TERMINAL}:{session.id}"
    assert started[0].payload["work_id"] == ended[0].payload["work_id"]
    assert started[0].payload["pid"] == session.pid
    assert started[0].payload["started_at"]
    assert started[0].persona_id is None
    # Ordered: the start row precedes the end row in the log.
    log = [e for e in EventLog().tail(200) if e.payload.get("process_session_id") == session.id]
    assert [e.type for e in log] == [EVENT_PROCESS_STARTED, EVENT_PROCESS_ENDED]


def test_a_listener_that_raises_never_breaks_the_spawn():
    """Killing mutation: drop the ``try`` in ``_notify_lifecycle`` → the spawn raises."""

    registry = ProcessRegistry()

    def explode(phase, session):
        raise RuntimeError(f"listener failed on {phase}")

    registry.add_lifecycle_listener(explode)
    registry.add_lifecycle_listener(process_presence._on_lifecycle)
    session = _spawn_and_finish(registry)
    assert session.exit_code == 0
    # The listener after the raising one still ran.
    assert any(e.payload["process_session_id"] == session.id for e in _rows(EVENT_PROCESS_ENDED))


def test_an_append_failure_is_swallowed(monkeypatch):
    monkeypatch.setattr(EventLog, "append", lambda self, evt: (_ for _ in ()).throw(OSError("disk full")))
    registry = _registry()
    session = _spawn_and_finish(registry)
    assert session.exit_code == 0


def test_install_is_idempotent(monkeypatch):
    monkeypatch.setattr(process_presence, "_installed", False)
    seen: list = []
    import tools.process_registry as registry_module

    monkeypatch.setattr(registry_module.process_registry, "_lifecycle_listeners", seen)
    assert process_presence.install_process_presence() is True
    assert process_presence.install_process_presence() is False
    assert seen == [process_presence._on_lifecycle]


def _process_event(event_type: str) -> Event:
    payload = {
        "process_session_id": "proc_abc",
        "work_id": f"{KIND_TERMINAL}:proc_abc",
        "pid": 1234,
        "command": "sleep 5",
        "owner_task_id": None,
        "started_at": "",
    }
    if event_type == EVENT_PROCESS_ENDED:
        payload.update(exit_code=0, completion_reason="exited")
    return Event(
        ts=datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC),
        type=event_type,
        task_id=None,
        run_id=None,
        persona_id=None,
        payload=payload,
    )


def test_both_types_are_declared_and_are_not_covered_domain_events():
    """Killing mutation: add either type to ``COVERED_DOMAIN_EVENT_TYPES`` → a
    process batch becomes patch-coverable and ships an empty patch frame."""

    catalog = event_catalog()
    assert EVENT_PROCESS_STARTED in catalog
    assert EVENT_PROCESS_ENDED in catalog
    assert "exit_code" in catalog[EVENT_PROCESS_ENDED]["summary_fields"]
    for event_type in (EVENT_PROCESS_STARTED, EVENT_PROCESS_ENDED):
        EventLog().append(_process_event(event_type))  # the contract accepts the payload

    batch = [_process_event(EVENT_PROCESS_STARTED), _process_event(EVENT_PROCESS_ENDED)]
    assert batch_is_patch_coverable(batch) is False
    # The positive twin: a covered state.patched IS coverable under the same call.
    patched = Event(
        ts=datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC),
        type=STATE_PATCHED_EVENT_TYPE,
        task_id=None,
        run_id=None,
        persona_id=None,
        payload={"entity": "persona_instance", "id": "personainst_a", "op": PATCH_OP_UPSERT, "changed": {"display_name": "A"}},
    )
    assert batch_is_patch_coverable([patched]) is True


@pytest.mark.parametrize("phase", ["bogus", ""])
def test_an_unknown_phase_appends_nothing(phase):
    class _Session:
        id = "proc_x"

    assert process_presence._on_lifecycle(phase, _Session()) is False
