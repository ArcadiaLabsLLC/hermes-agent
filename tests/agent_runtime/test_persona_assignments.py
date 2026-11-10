"""Persona instances: singletons, placements, steering, open-chat binding and naming.

Split from one 5,169-line file so the per-file runner parallelises it
(FH-PREPUSH-TOUCHED-OVER-BUDGET-PERSONA-ASSIGNMENTS); shared helpers live in
``tests/agent_runtime/persona_assignments_helpers.py``.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.models import AgentPersona, AgentRun
from agent_runtime.persona_assignments import (
    PersonaInstanceStore,
    persona_chat_session_id_for,
    persona_instance_id_for,
    persona_instance_id_for_placement,
    persona_instance_summary,
)
from agent_runtime.persona_chat_history import persona_chat_history_summary
from agent_runtime.persona_instance_identity import reconcile_persona_instances
from agent_runtime.snapshot import build_snapshot
from agent_runtime.states import RunState, WorkerSessionState
from agent_runtime.status import build_status
from agent_runtime.store import RunStore
from hermes_cli.harness_parts.persona import (
    chat_open,
    instance_commands,
    lifecycle_commands,
)
from tests.agent_runtime.persona_assignments_helpers import (
    _assignment_config,
    _FailingTranscriptDB,
    _persona,
    _seed_run,
    _TranscriptDB,
)
from tests.agent_runtime.persona_instance_mint import mint_free_floating

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def test_persona_instance_store_ensures_a_singleton_per_persona(isolate_agent_runtime_root):
    # S56 renamed derive_from_workers(personas, workers) -> ensure_for_personas
    # (the worker half is gone). The surviving contract is one canonical instance
    # per configured persona.
    store = PersonaInstanceStore()

    instances = store.ensure_for_personas([_persona("dev"), _persona("qa")])

    by_id = {item.persona_id: item for item in instances}
    assert by_id["dev"].id == "personainst_dev"
    assert by_id["qa"].id == "personainst_qa"


def test_disabled_and_mothballed_definitions_never_materialize_runtime_instances(
    isolate_agent_runtime_root,
):
    store = PersonaInstanceStore()

    instances = store.ensure_for_personas(
        [
            _persona("dev"),
            _persona("custom_reviewer", role="reviewer"),
            _persona("retired_coordinator", role="disabled"),
            _persona("pm", role="disabled"),
        ]
    )

    assert {item.persona_id for item in instances} == {"dev", "custom_reviewer"}


def test_reconciled_disabled_pm_is_not_recreated_by_read_builds(
    isolate_agent_runtime_root,
):
    store = PersonaInstanceStore()
    pm = _persona("pm", role="disabled")
    store.ensure_for_persona(pm)

    report = reconcile_persona_instances(event_log=EventLog())
    assert report["pruned_count"] == 1
    assert store.list_all() == []

    # These are the central paths used by snapshot/status/persona-list/chat
    # initialization. Repeating them after reconciliation must remain a no-op.
    assert store.ensure_for_personas([pm]) == []
    build_snapshot()
    build_status()
    assert not [item for item in store.list_all() if item.persona_id == "pm"]

    again = reconcile_persona_instances(event_log=EventLog())
    assert again["pruned_count"] == 0


def test_persona_instance_ensure_clears_a_stale_execution_binding(isolate_agent_runtime_root):
    # S56: with the worker lane gone the reset pass is unconditional — an
    # instance still carrying a dead task/assignment binding settles back to idle.
    store = PersonaInstanceStore()
    stale = store.ensure_for_persona(_persona("dev"))
    stale.mode = "task_bound"
    stale.state = WorkerSessionState.RUNNING
    stale.current_task_id = "task_stale"
    stale.current_assignment_id = "assign_stale"
    stale.goal_id = "task_stale"
    store.update(stale)

    instances = store.ensure_for_personas([_persona("dev")])

    instance = instances[0]
    assert instance.id == "personainst_dev"
    assert instance.state == WorkerSessionState.IDLE
    assert instance.current_assignment_id is None
    assert instance.current_task_id is None
    assert instance.active_run_id is None
    assert instance.session_id is None


def test_free_floating_instance_mint_reuses_canonical_idle_placement(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    first = mint_free_floating("profile_reviewer", store=store)
    second = mint_free_floating("profile_reviewer", store=store)

    assert first.id == second.id == persona_instance_id_for("profile_reviewer")
    assert first.persona_id == "profile_reviewer"
    assert first.role == "profile"
    assert first.profile_id == "reviewer"
    assert first.mode == "free_floating"
    assert first.state == WorkerSessionState.IDLE
    assert first.current_task_id is None
    # S56 removed PersonaInstance.active_worker_session_id outright.
    assert not hasattr(first, "active_worker_session_id")

    instances = store.ensure_for_personas([_persona("dev")])
    by_id = {item.id: item for item in instances}

    assert by_id[first.id].persona_id == "profile_reviewer"
    assert by_id[first.id].mode == "free_floating"
    assert by_id[first.id].state == WorkerSessionState.IDLE


def test_create_operator_chat_from_same_template_gets_distinct_sessions(isolate_agent_runtime_root):
    store = PersonaInstanceStore()

    first = store.create_operator_chat(
        persona_id="profile_reviewer",
        display_name="Reviewer One",
    )
    second = store.create_operator_chat(
        persona_id="profile_reviewer",
        display_name="Reviewer Two",
    )

    assert first.id == second.id == persona_instance_id_for("profile_reviewer")
    assert first.session_id.startswith(f"persona_chat_{first.id}_")
    assert second.session_id.startswith(f"persona_chat_{second.id}_")
    assert first.session_id != second.session_id
    assert first.mode == "chat"
    assert second.mode == "chat"
    assert first.persona_id == "profile_reviewer"
    assert first.profile_id == "reviewer"
    assert second.profile_id == "reviewer"
    assert first.display_name == "Reviewer One"
    assert second.display_name == "Reviewer Two"


def test_operator_chat_history_binds_by_unique_session(isolate_agent_runtime_root):
    from hermes_state import SessionDB

    store = PersonaInstanceStore()
    first = store.create_operator_chat(
        persona_id="profile_reviewer",
        display_name="Reviewer One",
    )
    second = store.create_operator_chat(
        persona_id="profile_reviewer",
        display_name="Reviewer Two",
    )
    db = SessionDB()
    for session_id, text in (
        (first.session_id, "first only"),
        (second.session_id, "second only"),
    ):
        db.create_session(
            session_id=session_id,
            source="agent_runtime_persona_chat",
            model=None,
            system_prompt="test persona chat",
        )
        db.append_message(session_id=session_id, role="assistant", content=text)

    rows = persona_chat_history_summary(
        persona_instances=store.list_all(),
        session_db=db,
    )

    messages_by_session = {
        row["session_id"]: [message["text"] for message in row["messages"]]
        for row in rows
        if row["messages"]
    }
    assert messages_by_session[first.session_id] == ["first only"]
    assert messages_by_session[second.session_id] == ["second only"]
    assert {row["persona_instance_id"] for row in rows if row["messages"]} == {first.id}


def test_additional_placement_does_not_reuse_another_instance_session(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    profile = store.create_operator_chat(
        persona_id="profile_alice",
        display_name="Alice Agent",
    )

    placed = store.add_instance(
        persona_id="profile_alice",
        placement_id="operator_2c1f1de674e74942_agent_2",
        display_name="Alice Agent",
        session_id=profile.session_id,
    )

    assert placed.id == persona_instance_id_for_placement("operator_2c1f1de674e74942_agent_2")
    assert placed.session_id != profile.session_id
    assert placed.session_id.startswith(f"persona_chat_{placed.id}_")


def test_additional_placement_stamps_scope_pointers(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    placed = store.add_instance(
        persona_id="qa",
        placement_id="agent_a1b2c3d4_agent_2",
        display_name="QA Agent (2)",
        workspace_id="ws_testv4",
        realm_id="realm_test",
    )
    assert placed.workspace_id == "ws_testv4"
    assert placed.realm_id == "realm_test"

    # The pointers survive the store round-trip and ship in the snapshot row.
    reloaded = store.get(placed.id)
    assert reloaded.workspace_id == "ws_testv4"
    assert reloaded.realm_id == "realm_test"
    summary = persona_instance_summary(reloaded)
    assert summary["workspace_id"] == "ws_testv4"
    assert summary["realm_id"] == "realm_test"

    # A plain re-open that carries no scope must NOT clear the pointers —
    # ordinary chat opens don't know scope and never erase provenance.
    reopened = store.open_chat(
        persona_id="qa",
        persona_instance_id=placed.id,
        session_id=placed.session_id,
    )
    assert reopened.workspace_id == "ws_testv4"
    assert reopened.realm_id == "realm_test"


def test_scope_pointers_default_none_for_unscoped_lanes(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    chat = store.create_operator_chat(
        persona_id="profile_alice",
        display_name="Alice Agent",
    )
    assert chat.workspace_id is None
    assert chat.realm_id is None
    summary = persona_instance_summary(chat)
    assert summary["workspace_id"] is None
    assert summary["realm_id"] is None


# S70 removed the assignment MINT side (`create` / `create_or_resume` /
# `PersonaAssignmentSpec` and the evidence/archive-scope/signal-hash
# derivations) with the free-floating queue lane; the tombstone registry (wave
# s70) owns their absence. The store's READ/CLOSE side survives for residual
# on-disk rows, so tests of surviving behaviour seed representative historical
# rows directly — the same pattern `_seed_run` uses for the historical run
# store.


def test_status_and_snapshot_expose_persona_instances_unconditionally(monkeypatch, isolate_agent_runtime_root):
    cfg = _assignment_config()
    monkeypatch.setattr("agent_runtime.status.load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr("agent_runtime.snapshot.envelope.load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr("agent_runtime.snapshot.sections.load_agent_runtime_config", lambda: cfg)
    # S56: the worker session that used to make ``dev`` an active-lane agent is
    # gone; a chat instance carrying a live goal/assignment is the surviving way
    # in (``ensure_for_personas`` settles every non-chat instance back to idle).
    instance_store = PersonaInstanceStore()
    live = instance_store.create_operator_chat(persona_id="dev", display_name="dev worker")
    live.goal_id = "task_1"
    live.current_assignment_id = "assign_1"
    instance_store.update(live)

    # S56: build_status / build_snapshot no longer take worker_session_store=,
    # and the persona-instance roster ships unconditionally.
    status = build_status()
    snapshot = build_snapshot()

    # The wire block survives — its ``enabled`` half is S56's statement that the
    # roster is no longer gated. AX2 (2026-08-31) took the second half:
    # ``assignment_store_enabled`` was the writerless assignment lane's own flag
    # and was constant ``true`` from the day it was written.
    assert status["persona_instance_runtime"] == {"enabled": True}
    # S56 retired these build_status rows with the worker/bundle/envelope lanes.
    for retired in (
        "worker_sessions",
        "active_worker_sessions",
        "repo_bundles",
        "repo_bundle_closeout",
        "bundle_queue",
        "repo_locks",
        "lanes",
        "production_envelope",
        "swarm",
        "swarm_budget",
    ):
        assert retired not in status, retired
    # RT-WRITERLESS-GOAL-STATUS-KEYS: the writer-less goal-lane projections went too.
    assert "runtime_instances" not in status
    assert "foreground_runtime" not in status
    assert {item["persona_id"] for item in status["persona_instances"]} >= {"dev", "qa", "neko_supervisor", "backend_dev"}
    status_lane_agents = {item["persona_id"]: item for item in status["agents"]}
    assert "personainst_dev" in status_lane_agents
    assert status_lane_agents["personainst_dev"]["source_persona_id"] == "dev"
    # Residue-slim R2: the fat tool payloads (tool_resolution) + the retired
    # agent_hud_state leave the row; the head keeps a typed visibility_ref pointer
    # + the always-visible scalars, fetched in full via `harness persona-instance
    # detail`.
    assert "agent_hud_state" not in status_lane_agents["personainst_dev"]
    assert "tool_resolution" not in status_lane_agents["personainst_dev"]
    assert isinstance(status_lane_agents["personainst_dev"]["visibility_ref"], dict)
    assert status_lane_agents["personainst_dev"]["visibility_ref"]["evicted"] is True
    assert isinstance(status_lane_agents["personainst_dev"]["mutation_boundary"], dict)
    assert snapshot["persona_instance_runtime"]["enabled"] is True
    assert {item["persona_id"] for item in list(snapshot["persona_instances"].values())} >= {"dev", "qa", "neko_supervisor", "backend_dev"}
    snapshot_lane_agents = {item["persona_id"]: item for item in snapshot["agents"]}
    # S56 INVERSION: this used to pin "personainst_dev not in the snapshot agent
    # catalog", but that only held because build_snapshot seeded ``workers = []``
    # so the instance derived IDLE while build_status (handed the real worker
    # store) saw it active. Both projections now share one unconditional roster,
    # so an ACTIVE instance appears in both agent lanes; idle ones still don't
    # (see test_snapshot_exposes_operator_created_idle_persona_instance).
    assert "personainst_dev" in snapshot_lane_agents
    assert snapshot_lane_agents["personainst_dev"]["source_persona_id"] == "dev"


def test_snapshot_exposes_operator_created_idle_persona_instance(monkeypatch, isolate_agent_runtime_root):
    cfg = _assignment_config()
    monkeypatch.setattr("agent_runtime.snapshot.envelope.load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr("agent_runtime.snapshot.sections.load_agent_runtime_config", lambda: cfg)
    created = mint_free_floating("profile_reviewer")

    snapshot = build_snapshot()
    by_id = {item["persona_instance_id"]: item for item in list(snapshot["persona_instances"].values())}

    assert created.id in by_id
    assert by_id[created.id]["agent_profile_id"] == created.id
    assert by_id[created.id]["persona_id"] == "profile_reviewer"
    assert by_id[created.id]["source_persona_id"] == "profile_reviewer"
    assert by_id[created.id]["source_profile_id"] == "reviewer"
    assert created.id == "personainst_profile_reviewer"
    assert by_id[created.id]["state"] == "idle"
    assert by_id[created.id]["lifecycle_mode"] == "free_floating"
    assert by_id[created.id]["mode"] == "free_floating"
    # S56 dropped active_worker_session_id from the model and every wire row.
    assert "active_worker_session_id" not in by_id[created.id]


def test_persona_instance_create_without_display_name_refuses_and_mints_nothing(monkeypatch, capsys, isolate_agent_runtime_root):
    """S70: the display-name-less branch used to queue a free-floating
    assignment nothing would ever consume (the tick loop that drained the queue
    was removed by the 2026-07-30 chat-only purge, and the advertised
    ``run-once`` follow-up verb never existed). The branch is now a typed
    refusal pointing at the chat lane — and it must mint NO assignment row and
    NO instance row on the way out."""
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)

    code = lifecycle_commands._cmd_persona_instance_create(
        Namespace(
            persona_id="dev",
            title="Launcher Dev sandbox",
            message="Check the persona without a product task.",
            requested_by="test",
            client_message_id=None,
            display_name=None,
            session_id=None,
            add_instance=False,
            placement_id=None,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "free-floating assignment lane is retired" in payload["error"]
    assert "mission-chat message" in payload["next_expected"]
    assert not list(paths.persona_assignments_dir().glob("*.json"))
    assert PersonaInstanceStore().list_all() == []
    assert RunStore().list_all() == []


def test_persona_instance_message_verb_is_gone_from_the_parser():
    """S70 removed `persona instance message` (and create's --auto-run /
    --stream / --max-actions / --max-seconds). argparse must REJECT them
    cleanly — a removed lane must never degrade to a silent ignore.

    The `--auto-run` vector carries `--auto-run` and nothing else removed: it
    used to ride beside `--message`, which S-DUP5 has since deleted too, and a
    vector with two rejected flags proves neither one is rejected."""
    import argparse

    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    with pytest.raises(SystemExit):
        root.parse_args(
            ["harness", "persona", "instance", "message", "personainst_dev", "--message", "hi"]
        )
    with pytest.raises(SystemExit):
        root.parse_args(
            [
                "harness", "persona", "instance", "create",
                "--persona", "dev", "--title", "t",
                "--auto-run",
            ]
        )
    # The surviving create shape still parses (display-name mint lane).
    args = root.parse_args(
        [
            "harness", "persona", "instance", "create",
            "--persona", "dev", "--title", "t",
            "--display-name", "Dev Agent", "--json",
        ]
    )
    assert args.display_name == "Dev Agent"


def test_coordinator_create_beyond_spawn_scope_returns_confirm_without_creating(monkeypatch, capsys, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)

    code = lifecycle_commands._cmd_persona_instance_create(
        Namespace(
            persona_id="dev",
            title="Spawn Dev",
            message="Start a child.",
            requested_by="coordinator:neko_supervisor",
            coordinator_id="neko_supervisor",
            coordinator_max_spawns=0,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=None,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=None,
            client_message_id=None,
            display_name="Spawned Dev",
            session_id=None,
            add_instance=True,
            placement_id="scene_child_1_agent_2",
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "needs_operator_confirm"
    assert payload["reason"] == "spawn_scope_exhausted"
    assert PersonaInstanceStore().list_all() == []


def test_persona_instance_steer_cli_attaches_parent_and_goal(monkeypatch, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)

    store = PersonaInstanceStore()
    store.ensure_for_persona(_persona("neko_supervisor"))
    store.ensure_for_persona(_persona("dev"))

    code = instance_commands._cmd_persona_instance_steer(
        Namespace(
            persona_instance_id="personainst_dev",
            parent_instance_id="personainst_neko_supervisor",
            goal_id="task_77",
            detach=False,
            requested_by="operator",
            coordinator_id="neko_supervisor",
            coordinator_max_spawns=None,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=None,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=None,
            json=True,
        )
    )

    assert code == 0
    instance = PersonaInstanceStore().get("personainst_dev")
    assert instance.spawned_by == "personainst_neko_supervisor"
    assert instance.goal_id == "task_77"
    assert instance.current_task_id is None  # a goal stamps no task (RT-TASK-BOUND-VOCABULARY)
    assert instance.mode != "task_bound"


def test_persona_instance_steer_cli_detaches_to_standalone(monkeypatch, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)

    store = PersonaInstanceStore()
    store.ensure_for_persona(_persona("neko_supervisor"))
    store.ensure_for_persona(_persona("dev"))
    store.steer("personainst_dev", parent_instance_id="personainst_neko_supervisor", goal_id="task_77")

    code = instance_commands._cmd_persona_instance_steer(
        Namespace(
            persona_instance_id="personainst_dev",
            parent_instance_id=None,
            goal_id=None,
            detach=True,
            requested_by="operator",
            coordinator_id="neko_supervisor",
            coordinator_max_spawns=None,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=None,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=None,
            json=True,
        )
    )

    assert code == 0
    instance = PersonaInstanceStore().get("personainst_dev")
    assert instance.spawned_by is None
    assert instance.goal_id is None
    assert instance.current_task_id is None
    assert instance.mode == "configured"


def test_persona_instance_steer_cli_rejects_self_steer(monkeypatch, capsys, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    PersonaInstanceStore().ensure_for_persona(_persona("dev"))

    code = instance_commands._cmd_persona_instance_steer(
        Namespace(
            persona_instance_id="personainst_dev",
            parent_instance_id="personainst_dev",
            goal_id="task_77",
            detach=False,
            requested_by="operator",
            coordinator_id="neko_supervisor",
            coordinator_max_spawns=None,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=None,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=None,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "cannot steer itself" in payload["error"]


def test_persona_instance_steer_cli_rejects_missing_parent(monkeypatch, capsys, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(instance_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    PersonaInstanceStore().ensure_for_persona(_persona("dev"))

    code = instance_commands._cmd_persona_instance_steer(
        Namespace(
            persona_instance_id="personainst_dev",
            parent_instance_id="personainst_missing",
            goal_id="task_77",
            detach=False,
            requested_by="operator",
            coordinator_id="neko_supervisor",
            coordinator_max_spawns=None,
            coordinator_spawns_used=0,
            coordinator_may_kill_own=None,
            coordinator_no_kill_own=None,
            coordinator_may_kill_others=None,
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "parent persona instance not found" in payload["error"]


def test_persona_instance_steer_store_reroutes_without_minting_instances(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    store.ensure_for_persona(_persona("neko_supervisor"))
    store.ensure_for_persona(_persona("pm"))
    store.ensure_for_persona(_persona("dev"))
    before = {item.id for item in store.list_all()}

    store.steer("personainst_dev", parent_instance_id="personainst_neko_supervisor", goal_id="task_77")
    rewired = store.steer("personainst_dev", parent_instance_id="personainst_pm", goal_id="task_77")

    assert rewired.spawned_by == "personainst_pm"
    # Re-routing must mutate the existing instance, never spawn a new one.
    assert {item.id for item in store.list_all()} == before


def test_persona_instance_steer_store_rejects_cycles(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    store.ensure_for_persona(_persona("neko_supervisor"))
    store.ensure_for_persona(_persona("dev"))
    store.ensure_for_persona(_persona("qa"))
    store.steer("personainst_dev", parent_instance_id="personainst_neko_supervisor", goal_id="task_77")
    store.steer("personainst_qa", parent_instance_id="personainst_dev", goal_id="task_77")

    with pytest.raises(ValueError, match="cycle"):
        store.steer("personainst_dev", parent_instance_id="personainst_qa", goal_id="task_77")

    assert store.get("personainst_dev").spawned_by == "personainst_neko_supervisor"


def test_persona_instance_open_chat_binds_old_chat_without_ticking(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    from argparse import Namespace

    cfg = _assignment_config()
    session_db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: session_db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: session_db)
    previous = PersonaInstanceStore().create_operator_chat(
        persona_id="dev",
        display_name="dev worker",
        session_id="chat_current_123",
    )

    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id="dev",
            session_id="chat_old_123",
            json=True,
        )
    )

    assert code == 0
    instance = PersonaInstanceStore().get("personainst_dev")
    assert instance.mode == "chat"
    assert instance.session_id == "chat_old_123"
    assert instance.current_task_id is None
    assert instance.active_run_id is None
    assert not list(paths.persona_assignments_dir().glob("*.json"))
    assert RunStore().list_all() == []
    assert session_db.get_session(instance.session_id) is not None
    assert session_db.get_session_title(instance.session_id) == f"{instance.display_name} chat"
    payload = json.loads(capsys.readouterr().out)
    assert payload["previous_session_id"] == previous.session_id
    assert payload["binding_receipt"] == {
        "schema_version": 1,
        "persona_instance_id": instance.id,
        "session_id": "chat_old_123",
        "previous_session_id": previous.session_id,
        "changed": True,
        "instance_updated_at": instance.updated_at.isoformat(),
    }

    assert chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id="dev",
            session_id="chat_old_123",
            json=True,
        )
    ) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["binding_receipt"]["changed"] is False
    assert replay["binding_receipt"]["previous_session_id"] == "chat_old_123"


def test_persona_instance_open_chat_new_session_mints_exact_instance_and_replays(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    from argparse import Namespace

    cfg = _assignment_config()
    session_db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: session_db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: session_db)
    existing = PersonaInstanceStore().create_operator_chat(
        persona_id="dev",
        display_name="Launcher Dev Agent",
    )
    original_session = existing.session_id
    args = Namespace(
        persona_id="dev",
        persona_instance_id=existing.id,
        session_id=None,
        new_session=True,
        idempotency_key="new-chat-dev-1",
        add_instance=False,
        json=True,
    )

    assert chat_open._cmd_persona_instance_open_chat(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["ok"] is True
    assert first["persona_instance_id"] == existing.id
    assert first["session_id"] != original_session
    assert first["mission_chat_root_id"] == first["session_id"]
    assert first["idempotent_replay"] is False
    assert first["mint_receipt_state"] == "bound"
    assert PersonaInstanceStore().get(existing.id).session_id == first["session_id"]
    assert session_db.get_session(first["session_id"]) is not None

    assert chat_open._cmd_persona_instance_open_chat(args) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["session_id"] == first["session_id"]
    assert replay["idempotent_replay"] is True
    assert replay["selected"] is True

    distinct_args = Namespace(
        **{
            **vars(args),
            "idempotency_key": "new-chat-dev-2",
        }
    )
    assert chat_open._cmd_persona_instance_open_chat(distinct_args) == 0
    distinct = json.loads(capsys.readouterr().out)
    assert distinct["session_id"] != first["session_id"]
    assert distinct["idempotent_replay"] is False
    assert PersonaInstanceStore().get(existing.id).session_id == distinct["session_id"]


def test_persona_instance_open_chat_new_session_retry_recovers_reserved_root(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    existing = PersonaInstanceStore().create_operator_chat(
        persona_id="dev",
        display_name="Launcher Dev Agent",
    )
    original_session = existing.session_id
    args = Namespace(
        persona_id="dev",
        persona_instance_id=existing.id,
        session_id=None,
        new_session=True,
        idempotency_key="new-chat-recover-1",
        add_instance=False,
        json=True,
    )
    monkeypatch.setattr(
        chat_open,
        "_default_persona_session_db",
        lambda: _FailingTranscriptDB("session_create"),
    )
    monkeypatch.setattr(
        lifecycle_commands,
        "_default_persona_session_db",
        lambda: _FailingTranscriptDB("session_create"),
    )

    assert chat_open._cmd_persona_instance_open_chat(args) == 2
    failed = json.loads(capsys.readouterr().out)
    assert failed["error_kind"] == "chat_session_persist_failed"
    assert failed["mint_receipt_state"] == "reserved"
    assert PersonaInstanceStore().get(existing.id).session_id == original_session

    recovered_db = _TranscriptDB()
    monkeypatch.setattr(
        chat_open,
        "_default_persona_session_db",
        lambda: recovered_db,
    )
    monkeypatch.setattr(
        lifecycle_commands,
        "_default_persona_session_db",
        lambda: recovered_db,
    )
    assert chat_open._cmd_persona_instance_open_chat(args) == 0
    recovered = json.loads(capsys.readouterr().out)
    assert recovered["session_id"] == failed["session_id"]
    assert recovered["idempotent_replay"] is True
    assert recovered["mint_receipt_state"] == "bound"
    assert PersonaInstanceStore().get(existing.id).session_id == failed["session_id"]


def test_persona_instance_open_chat_new_session_rejects_idempotency_scope_conflict(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    from argparse import Namespace

    cfg = _assignment_config()
    session_db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: session_db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: session_db)
    store = PersonaInstanceStore()
    dev = store.create_operator_chat(persona_id="dev", display_name="Dev")
    qa = store.create_operator_chat(persona_id="qa", display_name="QA")

    def args_for(persona_id, instance_id):
        return Namespace(
            persona_id=persona_id,
            persona_instance_id=instance_id,
            session_id=None,
            new_session=True,
            idempotency_key="shared-key-is-a-client-bug",
            add_instance=False,
            json=True,
        )

    assert chat_open._cmd_persona_instance_open_chat(args_for("dev", dev.id)) == 0
    capsys.readouterr()
    assert chat_open._cmd_persona_instance_open_chat(args_for("qa", qa.id)) == 2
    conflict = json.loads(capsys.readouterr().out)
    assert conflict["error_kind"] == "idempotency_conflict"
    assert PersonaInstanceStore().get(qa.id).session_id == qa.session_id


def test_persona_instance_open_chat_can_target_additional_placement(monkeypatch, isolate_agent_runtime_root):
    from argparse import Namespace

    cfg = _assignment_config()
    session_db = _TranscriptDB()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(chat_open, "_default_persona_session_db", lambda: session_db)
    monkeypatch.setattr(lifecycle_commands, "_default_persona_session_db", lambda: session_db)

    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id="profile_reviewer",
            session_id="chat_old_123",
            add_instance=True,
            placement_id="reviewer_agent_2",
            json=True,
        )
    )

    assert code == 0
    primary_missing = True
    try:
        PersonaInstanceStore().get("personainst_profile_reviewer")
        primary_missing = False
    except Exception:
        pass
    additional = PersonaInstanceStore().get("personainst_reviewer_agent_2")
    assert primary_missing is True
    assert additional.persona_id == "profile_reviewer"
    assert additional.session_id == "chat_old_123"
    assert additional.mode == "chat"
    assert session_db.get_session(additional.session_id) is not None
    assert session_db.get_session_title(additional.session_id) == f"{additional.display_name} chat"


def test_persona_instance_open_chat_session_persistence_failure_is_typed_and_not_silent(
    monkeypatch,
    capsys,
    isolate_agent_runtime_root,
):
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(
        chat_open,
        "_default_persona_session_db",
        lambda: _FailingTranscriptDB("session_create"),
    )
    monkeypatch.setattr(
        lifecycle_commands,
        "_default_persona_session_db",
        lambda: _FailingTranscriptDB("session_create"),
    )

    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id="dev",
            session_id="chat_persist_failure_123",
            json=True,
        )
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error_kind"] == "chat_session_persist_failed"
    assert payload["persistence_operation"] == "session_create"
    assert payload["persona_id"] == "dev"
    assert payload["persona_instance_id"] == "personainst_dev"
    assert payload["session_id"] == "chat_persist_failure_123"


def test_open_chat_cli_targets_the_session_owner_not_the_canonical(monkeypatch, isolate_agent_runtime_root):
    # Poison origin fix: the console's open-chat of a sibling passes the sibling's
    # session with a bare persona id. The CLI must rebind the instance the session
    # was minted FOR (personainst_qa_agent_2), never overwrite the canonical
    # primary's (personainst_qa) pointer with it.
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)

    sibling = PersonaInstanceStore().add_instance(
        persona_id="qa", placement_id="qa_agent_2", display_name="QA Agent (2)"
    )
    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id="qa",
            persona_instance_id=sibling.id,
            session_id=None,
            new_session=True,
            idempotency_key="open-sibling-owner",
            json=True,
        )
    )

    assert code == 0
    fresh = PersonaInstanceStore()
    # The sibling was rebound to its own session; the canonical primary never
    # adopted it.
    sibling_root = fresh.get("personainst_qa_agent_2").default_chat_session_id
    assert sibling_root
    assert sibling_root != sibling.session_id
    primary_adopted = False
    try:
        primary_adopted = fresh.get("personainst_qa").default_chat_session_id == sibling_root
    except Exception:
        primary_adopted = False
    assert not primary_adopted


def test_open_chat_default_display_name_never_renames_an_existing_named_instance(
    isolate_agent_runtime_root,
):
    # DEFECT B: the send path stamps the persona DEFAULT display_name. It must
    # NEVER rename an existing instance — the placement sibling reads "QA Agent
    # (2)" and the "(2)" is load-bearing (launcher conversational fold keys on
    # persona+displayName). Two "sends" (open_chat with default_display_name)
    # must both preserve the deliberate name.
    store = PersonaInstanceStore()
    sibling = store.add_instance(
        persona_id="qa", placement_id="qa_agent_2", display_name="QA Agent (2)"
    )
    assert sibling.display_name == "QA Agent (2)"

    for _ in range(2):  # repeated sends thread onto the same instance
        store.open_chat(
            persona_id="qa",
            persona_instance_id="personainst_qa_agent_2",
            session_id=sibling.session_id,
            default_display_name="QA Agent",  # the persona default the send path passes
        )
    assert store.get("personainst_qa_agent_2").display_name == "QA Agent (2)"


def test_open_chat_same_authoritative_binding_is_a_true_no_op(
    isolate_agent_runtime_root,
):
    """Repeated first-turn binding must not rewrite the row or fan out another
    full-core stream event when every authoritative field is already equal."""

    from agent_runtime.events import EventLog

    events = EventLog()
    store = PersonaInstanceStore(event_log=events)
    session_id = "persona_chat_personainst_dev_aaaaaaaaaaaa"
    first = store.open_chat(
        persona_id="dev",
        session_id=session_id,
        default_display_name="Dev",
    )
    opened_before = [
        event
        for event in events.tail(20)
        if event.type == "persona_instance.chat_opened"
    ]

    reopened = store.open_chat(
        persona_id="dev",
        session_id=session_id,
        default_display_name="Dev",
    )
    opened_after = [
        event
        for event in events.tail(20)
        if event.type == "persona_instance.chat_opened"
    ]

    assert reopened.updated_at == first.updated_at
    assert len(opened_before) == 1
    assert len(opened_after) == 1


def test_open_chat_default_display_name_names_a_first_ever_holder(isolate_agent_runtime_root):
    # A brand-new chat holder with no name yet DOES take the persona default —
    # stamping only happens when the instance has none.
    store = PersonaInstanceStore()
    minted = persona_chat_session_id_for(persona_instance_id_for("qa"))
    instance = store.open_chat(
        persona_id="qa", session_id=minted, default_display_name="QA Agent"
    )
    assert instance.display_name == "QA Agent"


def test_open_chat_authoritative_display_name_still_renames(isolate_agent_runtime_root):
    # An AUTHORITATIVE display_name (create_operator_chat / add_instance / an
    # explicit name) is unchanged by the fix — it always applies, so deliberate
    # (re)naming through those paths keeps working.
    store = PersonaInstanceStore()
    first = store.create_operator_chat(persona_id="qa", display_name="QA One")
    assert first.display_name == "QA One"
    second = store.create_operator_chat(persona_id="qa", display_name="QA Two")
    assert second.id == first.id
    assert second.display_name == "QA Two"  # authoritative rename honored


def test_add_instance_stores_explicit_placement_name_verbatim(isolate_agent_runtime_root):
    # PRIMARY FIX: a deliberate placement's distinct name ("QA Agent (2)") is
    # AUTHORITATIVE and stored verbatim, so the launcher conversational fold
    # (keyed on persona+display_name) keeps the sibling distinct end to end.
    store = PersonaInstanceStore()
    placed = store.add_instance(
        persona_id="qa",
        placement_id="qa_agent_2",
        display_name="QA Agent (2)",
    )
    assert placed.id == persona_instance_id_for_placement("qa_agent_2")
    assert placed.display_name == "QA Agent (2)"


def test_add_instance_omitted_name_uses_honest_default_not_title_cased_id(
    isolate_agent_runtime_root,
):
    # DOCUMENTED FALLBACK: when the client omits the placement name the store
    # takes the persona's honest default ("QA Agent"), NEVER the title-cased
    # persona id ("Qa") the template fallback would otherwise mint — that was
    # the live 2026-07-19 personainst_qa_agent_2 == "Qa" defect.
    store = PersonaInstanceStore()
    placed = store.add_instance(
        persona_id="qa",
        placement_id="qa_agent_2",
        default_display_name="QA Agent",
    )
    assert placed.display_name == "QA Agent"
    assert placed.display_name != "Qa"


def test_add_instance_default_never_overwrites_a_deliberate_name(
    isolate_agent_runtime_root,
):
    # INGEST SAFETY: a later add_instance re-open that carries only the persona
    # default must NOT rewrite an existing deliberate placement name — the "(2)"
    # is load-bearing for the fold.
    store = PersonaInstanceStore()
    first = store.add_instance(
        persona_id="qa", placement_id="qa_agent_2", display_name="QA Agent (2)"
    )
    assert first.display_name == "QA Agent (2)"
    reopened = store.add_instance(
        persona_id="qa",
        placement_id="qa_agent_2",
        default_display_name="QA Agent",  # the persona default a later open passes
    )
    assert reopened.display_name == "QA Agent (2)"


def test_open_chat_cli_add_instance_threads_explicit_display_name(
    monkeypatch, isolate_agent_runtime_root
):
    # END-TO-END SEAM: the occupied-chat placement path sends the distinct name
    # through --display-name; the open-chat CLI must forward it to the new
    # placement instead of dropping it (the exact seam that minted the live
    # "Qa" — add_instance was called with no display_name).
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)

    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id="qa",
            session_id=None,
            add_instance=True,
            placement_id="qa_agent_2",
            display_name="QA Agent (2)",
            json=True,
        )
    )

    assert code == 0
    placed = PersonaInstanceStore().get("personainst_qa_agent_2")
    assert placed.display_name == "QA Agent (2)"


def test_open_chat_cli_add_instance_omitted_name_uses_persona_config_not_title_case(
    monkeypatch, isolate_agent_runtime_root
):
    # HONEST FALLBACK at the CLI seam: with --display-name omitted, the new
    # placement takes the persona's CONFIGURED display name ("QA Agent"), never
    # the store template's title-cased persona id ("Qa").
    from argparse import Namespace

    cfg = _assignment_config()
    monkeypatch.setattr(chat_open, "load_agent_runtime_config", lambda: cfg)
    monkeypatch.setattr(lifecycle_commands, "load_agent_runtime_config", lambda: cfg)
    qa_persona = AgentPersona(
        id="qa",
        display_name="QA Agent",
        role="qa",
        model="gpt-test",
        provider="openai-codex",
        api_mode="codex_responses",
        system_prompt_path="agent_runtime/prompts/qa.md",
        hermes_profile="profile-qa",
    )
    monkeypatch.setattr(chat_open, "_persona_by_id", lambda _cfg, _pid: qa_persona)
    monkeypatch.setattr(lifecycle_commands, "_persona_by_id", lambda _cfg, _pid: qa_persona)

    code = chat_open._cmd_persona_instance_open_chat(
        Namespace(
            persona_id="qa",
            session_id=None,
            add_instance=True,
            placement_id="qa_agent_2",
            display_name=None,
            json=True,
        )
    )

    assert code == 0
    placed = PersonaInstanceStore().get("personainst_qa_agent_2")
    assert placed.display_name == "QA Agent"
    assert placed.display_name != "Qa"


def _seed_live_run_binding(instance_store) -> AgentRun:
    """Seed a live execution binding straight onto the instance row.

    S56 deleted the worker session store (and ``update_from_worker``), so the
    RUN is the only remaining live-binding authority; these two tests seed it
    directly rather than through a worker projection.
    """

    run = _seed_run("dev", "task_live", "stage_1", session_id="persona_chat_personainst_dev_live")
    live = instance_store.ensure_for_persona(_persona("dev"))
    live.mode = "task_bound"
    live.state = WorkerSessionState.RUNNING
    live.current_task_id = "task_live"
    live.goal_id = None  # mission-shaped: a real task, not a goal (the decode keeps it)
    live.current_assignment_id = "assign_live"
    live.active_run_id = run.id
    live.session_id = "persona_chat_personainst_dev_live"
    instance_store.update(live)
    return run


def test_open_chat_updates_only_default_chat_pointer_during_live_run(isolate_agent_runtime_root):
    instance_store = PersonaInstanceStore()
    runs = RunStore()
    run = _seed_live_run_binding(instance_store)

    instance = instance_store.open_chat(
        persona_id="dev", session_id="persona_chat_personainst_dev_new"
    )

    assert instance.default_chat_session_id == "persona_chat_personainst_dev_new"
    assert instance.active_run_id == run.id
    assert instance.current_task_id == "task_live"
    assert runs.get(run.id).state == RunState.RUNNING


def test_add_instance_mints_distinct_placement_backed_instance(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    primary = store.create_operator_chat(persona_id="profile_reviewer", display_name="Reviewer")
    additional = store.add_instance(
        persona_id="profile_reviewer",
        placement_id="reviewer_agent_2",
        display_name="Reviewer 2",
    )

    assert primary.id == "personainst_profile_reviewer"
    assert additional.id == "personainst_reviewer_agent_2"
    assert additional.persona_id == "profile_reviewer"
    assert additional.profile_id == "reviewer"
    assert additional.session_id.startswith("persona_chat_personainst_reviewer_agent_2_")
    assert store.get(primary.id).session_id == primary.session_id
