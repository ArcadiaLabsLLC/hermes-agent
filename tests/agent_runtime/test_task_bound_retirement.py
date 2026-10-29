"""RT-TASK-BOUND-VOCABULARY S1: ``--goal`` is a correlation id, never a task binding.

Plan ``docs/agent-runtime-harness/planned/task-bound-mode-retirement-2026-10-27.md``.
A STEER-shaped row (``task_bound`` whose task IS its goal) decodes as an ordinary
instance; a MISSION-shaped row (a task that is not its goal) decodes unchanged and
the reconciler's phase 0 archives it. Write-side assertions read the RAW JSON,
because the decode would hide a stamp.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_id_for
from agent_runtime.persona_instance_identity import reconcile_persona_instances
from agent_runtime.persona_profile_binding import _instance_rows_for_persona
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

PERSONA = "dev"
STEERED = f"{persona_instance_id_for(PERSONA)}_agent_2"
MISSION = f"{persona_instance_id_for(PERSONA)}_agent_3"


def _seed(instance_id: str, *, task: str | None, goal: str | None, mode: str = "task_bound") -> None:
    row = PersonaInstance(
        id=instance_id, persona_id=PERSONA, role=PERSONA, display_name="Dev", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, mode=mode,
        current_task_id=task, goal_id=goal,
    )
    path = paths.persona_instance_path(instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(row), indent=2, sort_keys=True), encoding="utf-8")


def _raw(instance_id: str) -> dict:
    return json.loads(paths.persona_instance_path(instance_id).read_text(encoding="utf-8"))


def _both_reads(store: PersonaInstanceStore, instance_id: str) -> list[PersonaInstance]:
    return [store.get(instance_id), next(i for i in store.scan_all().instances if i.id == instance_id)]


def test_steer_with_a_goal_stamps_no_mode_and_no_task():
    """Kill-mutation: restore ``updates["mode"] = "task_bound"`` (and the task) in ``set_parents``."""
    _seed(STEERED, task=None, goal=None, mode="configured")
    _seed(MISSION, task=None, goal=None, mode="configured")
    PersonaInstanceStore().steer(STEERED, parent_instance_id=MISSION, goal_id="g1")
    stored = _raw(STEERED)
    assert stored["goal_id"] == "g1"
    assert stored["mode"] == "configured"
    assert stored.get("current_task_id") is None


def test_update_profile_with_a_goal_writes_no_task():
    """RT-TASK-BOUND-UPDATE-GOAL-STAMP. Kill-mutation: restore the ``current_task_id`` write in
    ``_apply_chat_fields`` → the task half reds."""
    _seed(STEERED, task=None, goal=None, mode="configured")
    PersonaInstanceStore().update_profile(STEERED, goal_id="g1")
    stored = _raw(STEERED)
    assert stored["goal_id"] == "g1"
    assert stored["mode"] == "configured"
    assert stored.get("current_task_id") is None


def test_a_steer_shaped_row_decodes_as_ordinary_through_get_and_scan_all():
    """Kill-mutation: normalise in ``get`` only (``scan_all`` decoding raw) → the scan half reds."""
    _seed(STEERED, task="g1", goal="g1")
    for instance in _both_reads(PersonaInstanceStore(), STEERED):
        assert instance.mode == "configured"
        assert instance.current_task_id is None
        assert instance.goal_id == "g1"


def test_a_mission_shaped_row_decodes_configured_and_keeps_its_task():
    """RT-TASK-BOUND-MISSION-LANES: no reader branches on ``task_bound``, so every stored
    one decodes ``configured``; the mission shape keeps its task for the archive record.
    Kill-mutation: restore the ``current_task_id == goal_id`` guard on the ``mode`` write
    → ``mode == "task_bound"``, red."""
    _seed(MISSION, task="task_9", goal=None)
    for instance in _both_reads(PersonaInstanceStore(), MISSION):
        assert instance.mode == "configured"
        assert instance.current_task_id == "task_9"


def test_a_steered_instance_is_not_refused_as_busy_by_the_profile_rebind():
    """The visible effect. Kill-mutation: restore the ``BUSY_TASK_BOUND`` arm → the MISSION half reds."""
    _seed(STEERED, task="g1", goal="g1")
    _seed(MISSION, task="task_9", goal=None)
    reasons = {row["persona_instance_id"]: row["busy_reason"] for row in _instance_rows_for_persona(PERSONA)}
    assert reasons[STEERED] is None
    assert reasons[MISSION] is None  # no busy reason reads ``current_task_id`` any more


def test_phase_0_normalises_steer_rows_archives_mission_rows_once():
    """Kill-mutation: archive every ``task_bound`` row → the normalised half reds."""
    _seed(STEERED, task="g1", goal="g1")
    _seed(MISSION, task="task_9", goal=None)
    events = EventLog()
    store = PersonaInstanceStore(event_log=events)

    preview = store.retire_task_bound_rows(apply=False)
    assert [i["persona_instance_id"] for i in preview["normalised"]] == [STEERED]
    assert [i["persona_instance_id"] for i in preview["archived"]] == [MISSION]
    assert _raw(STEERED)["mode"] == "task_bound" and paths.persona_instance_path(MISSION).exists()

    store.retire_task_bound_rows(apply=True)
    assert _raw(STEERED)["mode"] == "configured" and _raw(STEERED).get("current_task_id") is None
    assert not paths.persona_instance_path(MISSION).exists()
    archived = list(paths.persona_instances_archive_dir().glob(f"*_retire/{MISSION}.json"))
    assert len(archived) == 1
    actions = sorted(e.payload["action"] for e in events.tail(1000) if e.type == "persona_instance.reconciled")
    assert actions == ["task_bound_archived", "task_bound_normalised"]
    assert store.retire_task_bound_rows(apply=True) == {"normalised": [], "archived": []}


def test_the_reconciler_runs_phase_0_and_its_dry_run_writes_nothing():
    """Kill-mutation: drop the phase-0 call in ``reconcile_persona_instances`` → red."""
    _seed(STEERED, task="g1", goal="g1")
    dry = reconcile_persona_instances(apply=False)
    assert [i["persona_instance_id"] for i in dry["task_bound_normalised"]] == [STEERED]
    assert _raw(STEERED)["mode"] == "task_bound"
    assert reconcile_persona_instances(apply=True)["task_bound_normalised_count"] == 1
    assert reconcile_persona_instances(apply=True)["task_bound_normalised_count"] == 0


def _boot_ready_frame() -> dict:
    import io

    from hermes_cli.harness_parts.serve import serve_loop

    out = io.StringIO()
    assert serve_loop(iter([json.dumps({"op": "shutdown"}) + "\n"]), out, pool_size=1, dispatch=lambda argv: 0) == 0
    return next(f for f in map(json.loads, out.getvalue().splitlines()) if f.get("event") == "ready")


def test_serve_boot_runs_phase_0_once():
    """RT-TASK-BOUND-BOOT-SWEEP. Kill-mutation: drop the ``retire_task_bound_rows`` call from
    ``_boot_sweeps_and_ready_frame`` → the archive glob is empty, red."""
    _seed(STEERED, task="g1", goal="g1")
    _seed(MISSION, task="task_9", goal=None)

    assert _boot_ready_frame()["task_bound_retired"] == 2

    assert _raw(STEERED)["mode"] == "configured" and _raw(STEERED).get("current_task_id") is None
    assert len(list(paths.persona_instances_archive_dir().glob(f"*_retire/{MISSION}.json"))) == 1
    assert "task_bound_retired" not in _boot_ready_frame()


def test_a_phase_0_that_raises_does_not_fail_the_boot(monkeypatch):
    """Kill-mutation: remove the ``try/except`` around the boot sweep → the boot errors."""
    def boom(self, *, apply=True):
        raise OSError("store unreadable")

    monkeypatch.setattr(PersonaInstanceStore, "retire_task_bound_rows", boom)
    ready = _boot_ready_frame()
    assert ready["event"] == "ready" and "task_bound_retired" not in ready
