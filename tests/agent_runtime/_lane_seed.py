"""Seed a persisted lane row straight to disk, for READ-side tests.

Every lane writer was deleted at S53, so a test that needs a persisted lane to
read back cannot mint one through ``GoalRuntimeInstanceStore``. Seeding the row
directly exercises the surviving read path against real on-disk state instead
of dropping the coverage — the same move ``test_status`` makes for runs.
Moved here from the S53 removal gate when the removal gates were deleted
(owner, 2026-09-24).
"""

from __future__ import annotations

from hermes_time import now
from utils import atomic_json_write

from agent_runtime import paths
from agent_runtime.models import GoalRuntimeInstance
from agent_runtime.serde import to_jsonable


def seed_lane_row(
    instance_id: str,
    *,
    task_id: str,
    state: str = "running",
    lane_kind: str = "production",
    priority: int = 5,
    **fields,
) -> GoalRuntimeInstance:
    ts = now()
    instance = GoalRuntimeInstance(
        id=instance_id,
        task_id=task_id,
        lane=instance_id,
        state=state,
        created_at=ts,
        updated_at=ts,
        lane_kind=lane_kind,
        priority=priority,
        **fields,
    )
    path = paths.runtime_instance_path(instance.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json_write(path, to_jsonable(instance), indent=2, sort_keys=True)
    return instance
