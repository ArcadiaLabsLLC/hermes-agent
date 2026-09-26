"""Live behaviour that the S-wave removal gates used to carry.

The per-wave removal gates (``test_s*_removal.py``, S7–S57) were deleted on
2026-09-24 by owner ruling ("delete, live-behaviour checks moved first"). Most of
what they asserted was ABSENCE — a module, symbol, field or contract is gone —
and that dies with them. What follows is the part that checks the RUNNING
system and would still catch a real regression, merged where several waves
asserted one behaviour:

* a deregistered event type still READS BACK off an existing log (S44/S49/S52/S53);
* an operator config that still sets retired blocks and scalars LOADS, keeps
  its live keys, and validates (S47/S56/S57);
* the validator still has a real arm, and a default config validates clean (S57);
* the persona roster is emitted whatever the retired flag says (S56);
* the operator summary still renders a surviving type (S52);
* the lane READ path still projects a persisted row, into ``status`` too (S53);
* a stale persona row carrying the removed worker field is not busy (S56).

Pins elsewhere that already covered one of these were not duplicated: the chat
HUD's steering edges (S19) live in ``test_runtime_hud.py``.
"""

from __future__ import annotations

import json

import pytest
from agent_runtime import yaml_io

from agent_runtime import migrations, paths, persona_profile_binding, runtime_instances, snapshot, status
from agent_runtime.config import AgentRuntimeConfig, load_agent_runtime_config
from agent_runtime.runtime_instances import GoalRuntimeInstanceStore
from tests.agent_runtime._lane_seed import seed_lane_row

#: One historical row per retired event family, each written before its
#: deregistration: role envelopes (S44), operator takeover (S49), repo-bundle
#: writes (S52), lane transitions (S53).
_HISTORICAL_ROWS = (
    ("role_envelope.opened", {"envelope_id": "envelope_abc", "role_id": "dev"}, "envelope_id"),
    ("operator.takeover.applied", {"worker_session_id": "worker_abc", "actor": "operator"}, "worker_session_id"),
    ("repo_bundle.verified", {"repo_bundle_id": "bundle_abc", "repo": "launcher", "state": "verified"}, "repo_bundle_id"),
    (
        "lane.transitioned",
        {"runtime_instance_id": "goalrt_abc", "task_id": "task_historical", "state": "running"},
        "runtime_instance_id",
    ),
)


@pytest.mark.parametrize(("event_type", "payload", "key"), _HISTORICAL_ROWS, ids=[r[0] for r in _HISTORICAL_ROWS])
def test_a_retired_event_type_still_reads_back_off_the_log(event_type, payload, key, isolate_agent_runtime_root):
    """Deregistration gates APPENDS, not reads: a live log written before a
    contract was retired must still deserialize."""

    from agent_runtime.events import EventLog

    line = {
        "ts": "2026-07-01T00:00:00+00:00",
        "type": event_type,
        "task_id": "task_historical",
        "run_id": None,
        "persona_id": "dev",
        "payload": payload,
    }
    paths.events_path().parent.mkdir(parents=True, exist_ok=True)
    paths.events_path().write_text(json.dumps(line) + "\n", encoding="utf-8")

    rows = list(EventLog().iter_from_offset(0))

    assert [evt.type for _offset, evt in rows] == [event_type]
    assert rows[0][1].payload[key] == payload[key]


#: Blocks and scalars the live operator roots still carry in their yaml after
#: S47 / S56 / S57 took them off ``RuntimeConfig``.
_RETIRED_BLOCKS = {
    "role_envelope": {"enabled": True, "max_no_progress_repeats": 2},
    "enterprise_worker_sessions": {"enabled": True, "mode": "enforce", "persona_instance_runtime": True},
    "repo_bundle_routing": {"enabled": True, "auto_create_from_mission_plan": True},
    "continuous_role_sessions": {"enabled": True, "max_proofs_per_envelope": 2},
    "normal_worker_flow": {"enabled": True, "auto_final_gate_after_delivery": True},
    "simplified_agent_contract": {"enabled": True, "allow_legacy_decision_aliases": True},
    "swarm": {"enabled": True, "max_active_lanes": 4},
    "daemon": {"enabled": True, "interval_seconds": 3, "heartbeat_seconds": 1},
}
_RETIRED_SCALARS = {
    "heartbeat_ttl_seconds": 1,
    "daemon_enabled": True,
    "root_node_mode": True,
    "preferred_goal_execution_mode": "in_process_controller",
    "liveness_enabled": False,
    "liveness_poll_seconds": 1,
    "mission_max_total_tokens": 1,
    "artifact_storage_low_watermark_mb": 1,
}


def test_an_operator_config_still_setting_retired_knobs_loads_ignores_them_and_keeps_its_live_keys(
    tmp_path, monkeypatch
):
    home = tmp_path / "profile"
    home.mkdir()
    stanza = {**_RETIRED_BLOCKS, **_RETIRED_SCALARS}
    stanza["supervision"] = {"child_events_enabled": True, "recursive_enabled": True}
    stanza["lock_acquire_timeout_seconds"] = 33
    (home / "config.yaml").write_text(yaml_io.dump({"agent_runtime": stanza}), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    cfg = load_agent_runtime_config()

    for name in (*_RETIRED_BLOCKS, *_RETIRED_SCALARS):
        assert not hasattr(cfg, name), name
    assert not hasattr(cfg.supervision, "recursive_enabled")
    # The live keys in the SAME yaml still load: an ignore, not a parse failure.
    assert cfg.supervision.child_events_enabled is True
    assert cfg.lock_acquire_timeout_seconds == 33
    assert migrations.validate_runtime_config(cfg)["ok"] is True
    assert migrations.effective_config_summary(cfg).get("role_envelope") is None


def test_the_validator_still_rejects_a_bad_live_value_and_passes_the_default():
    bad = migrations.validate_runtime_config(AgentRuntimeConfig(lock_acquire_timeout_seconds=0))
    assert bad["ok"] is False
    assert any(item["field"] == "lock_acquire_timeout_seconds" for item in bad["errors"])

    default = migrations.validate_runtime_config(AgentRuntimeConfig())
    assert default["ok"] is True and default["errors"] == []


def test_the_frame_still_publishes_the_live_config_scalar(isolate_agent_runtime_root):
    frame = snapshot.build_snapshot()
    assert "lock_acquire_timeout_seconds" in frame["runtime_config"]


@pytest.mark.parametrize(
    "config",
    [
        {"agent_runtime": {"supervision": {"child_events_enabled": True}}},
        {"agent_runtime": {"enterprise_worker_sessions": {"enabled": False, "persona_instance_runtime": False}}},
    ],
    ids=["retired-block-absent", "retired-block-disabled"],
)
def test_the_persona_roster_is_emitted_whatever_the_retired_flag_says(
    config, tmp_path, monkeypatch, isolate_agent_runtime_root
):
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(yaml_io.dump(config), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))

    frame = snapshot.build_snapshot()
    data = status.build_status()

    assert "persona_instances" in frame
    assert frame["persona_instance_runtime"]["enabled"] is True
    assert data["persona_instance_runtime"] == {"enabled": True}
    assert isinstance(data["persona_instances"], list)


def test_the_operator_summary_still_renders_a_surviving_type():
    from hermes_time import now

    from agent_runtime.events import Event, operator_event_summary

    closed = Event(
        ts=now(),
        type="run.closed",
        task_id=None,
        run_id=None,
        persona_id="dev",
        payload={"state": "completed", "decision_type": "hand_off"},
    )
    assert operator_event_summary(closed) == "Closed dev run as completed after hand_off."


def test_the_lane_read_path_projects_a_persisted_row(isolate_agent_runtime_root):
    seeded = seed_lane_row(
        "goalrt_liveread",
        task_id="task_live",
        state="running",
        priority=2,
        current_stage_id="stage_1",
        current_owner="dev",
    )
    store = GoalRuntimeInstanceStore()

    assert [row.id for row in store.list_all()] == [seeded.id]
    summary = runtime_instances.runtime_instance_summary(store.get(seeded.id))
    assert summary["lane_id"] == seeded.id
    assert summary["lane_kind"] == "production"
    assert summary["priority"] == 2
    assert summary["current_stage_id"] == "stage_1"
    assert summary["current_owner"] == "dev"

    data = status.build_status()
    assert [row["lane_id"] for row in data["runtime_instances"]["lanes"]] == [seeded.id]


def test_a_stale_persona_row_carrying_the_removed_worker_field_is_not_busy():
    row = {"state": "idle", "active_worker_session_id": "worker_deadbeef"}
    assert persona_profile_binding.instance_busy_reason(row) is None
