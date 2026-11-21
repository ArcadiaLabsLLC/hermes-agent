"""Agents that lived nowhere become ordinary agents in the Default workspace.

Row ``RT-AGENTS-THAT-LIVED-NOWHERE-BECOME-ORDINARY-AGENTS-IN-THE-DEFAULT-WORKSPACE`` (plan
``docs/agent-runtime-harness/planned/agent-template-vs-canonical-instance-2026-11-21.md`` §5(iii), §6;
review w1118a.78). The fixture is a namespace holding runtime-global ``personainst_<persona>`` rows, the
Default workspace made the way the serve boot makes it, and the reconciler run the way the CLI runs it.
Every write assertion reads the raw JSON, so the decode cannot hide what is stored.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.default_scope import DEFAULT_REALM_ID, DEFAULT_WORKSPACE_ID, ensure_default_scope
from agent_runtime.models import PersonaInstance
from agent_runtime.office_store import OfficeStore
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_id_for
from agent_runtime.persona_assignments.identity import (
    is_canonical_persona_channel,
    row_is_canonical_persona_channel,
)
from agent_runtime.persona_instance_adoption import adopt_global_rows
from agent_runtime.persona_instance_identity import reconcile_persona_instances
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import RealmStore

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

PERSONA = "neko_supervisor"
CANONICAL = persona_instance_id_for(PERSONA)
CHAT = f"persona_chat_{CANONICAL}_0123456789ab"


def _seed(instance_id: str = CANONICAL, *, persona_id: str = PERSONA, **fields) -> None:
    row = PersonaInstance(
        id=instance_id, persona_id=persona_id, role=persona_id, display_name="Neko", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, mode="chat", **fields,
    )
    path = paths.persona_instance_path(instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(row), indent=2, sort_keys=True), encoding="utf-8")


def _raw(instance_id: str = CANONICAL) -> dict:
    return json.loads(paths.persona_instance_path(instance_id).read_text(encoding="utf-8"))


def _desk_ids(workspace_id: str = DEFAULT_WORKSPACE_ID) -> set[str]:
    try:
        return {a.persona_instance_id for a in OfficeStore().scan_actors(workspace_id).actors}
    except Exception:
        return set()


def _fates(report: list[dict]) -> dict[str, tuple]:
    return {item["persona_instance_id"]: (item["fate"], item.get("reason")) for item in report}


def test_an_adopted_row_is_not_the_canonical_channel():
    """Kill-mutation: drop the stamp test in ``row_is_canonical_persona_channel`` → red."""
    assert row_is_canonical_persona_channel(CANONICAL, PERSONA)
    assert not row_is_canonical_persona_channel(CANONICAL, PERSONA, "2026-11-21")
    _seed(adopted_from_global="2026-11-21", workspace_id=DEFAULT_WORKSPACE_ID, realm_id=DEFAULT_REALM_ID)
    instance = PersonaInstanceStore().get(CANONICAL)
    assert not is_canonical_persona_channel(instance)
    assert instance.workspace_id == DEFAULT_WORKSPACE_ID  # the decode keeps an adopted row's workspace


def test_a_row_holding_a_chat_becomes_an_ordinary_seated_agent_keeping_its_id():
    ensure_default_scope(seed_active_pointers=False)
    _seed(default_chat_session_id=CHAT)
    data = reconcile_persona_instances(apply=True)
    assert _fates(data["adoption"]) == {CANONICAL: ("adopted", None)}
    raw = _raw()
    assert raw["id"] == CANONICAL and raw["default_chat_session_id"] == CHAT
    assert raw["workspace_id"] == DEFAULT_WORKSPACE_ID and raw["realm_id"] == DEFAULT_REALM_ID
    assert raw["adopted_from_global"]
    assert CANONICAL in _desk_ids()
    decoded = PersonaInstanceStore().get(CANONICAL)
    assert decoded.workspace_id == DEFAULT_WORKSPACE_ID and not is_canonical_persona_channel(decoded)
    # Nothing was retired or archived by this row.
    assert not paths.persona_instances_archive_dir().exists() or not any(
        paths.persona_instances_archive_dir().rglob("*.json"))


def test_a_reconcile_keeps_an_adopted_rows_workspace():
    """A second run does nothing, and phase 6 does not clear the adopted row's pointers.
    Kill-mutation: drop the stamp argument in ``clear_canonical_scope_pointers`` → red."""
    ensure_default_scope(seed_active_pointers=False)
    _seed(default_chat_session_id=CHAT)
    reconcile_persona_instances(apply=True)
    first = _raw()
    second = reconcile_persona_instances(apply=True)
    assert second["adoption"] == [] and second["canonical_scope_cleared"] == []
    assert _raw() == first


def test_the_dry_run_names_each_rows_fate_and_writes_nothing():
    ensure_default_scope(seed_active_pointers=False)
    _seed(default_chat_session_id=CHAT)
    _seed(persona_instance_id_for("qa"), persona_id="qa")  # holds nothing
    _seed(persona_instance_id_for("dev"), persona_id="dev", assigned_slots=["app"], active_run_id="run_1")
    before = {i: _raw(i) for i in (CANONICAL, persona_instance_id_for("qa"), persona_instance_id_for("dev"))}
    data = reconcile_persona_instances(apply=False)
    assert _fates(data["adoption"]) == {
        CANONICAL: ("would_adopt", None),
        persona_instance_id_for("qa"): ("left_empty", None),
        persona_instance_id_for("dev"): ("skipped", "mid_turn"),
    }
    assert {i: _raw(i) for i in before} == before
    assert CANONICAL not in _desk_ids()


def test_an_empty_row_is_left_as_it_is():
    ensure_default_scope(seed_active_pointers=False)
    _seed()
    before = _raw()
    assert _fates(adopt_global_rows(apply=True)) == {CANONICAL: ("left_empty", None)}
    assert _raw() == before and CANONICAL not in _desk_ids()


@pytest.mark.parametrize(
    "fields, holds",
    [
        ({"assigned_slots": ["app"]}, ["slots"]),
        ({"current_chat_goal": "ship it"}, ["goal"]),
        ({"current_task_id": "task_1"}, ["work"]),
    ],
)
def test_a_row_holding_a_goal_work_or_slots_is_adopted(fields, holds):
    ensure_default_scope(seed_active_pointers=False)
    _seed(**fields)
    report = adopt_global_rows(apply=True)
    assert report[0]["fate"] == "adopted" and report[0]["holds"] == holds


def test_a_saved_chat_the_move_ledger_names_counts_as_holding_a_chat():
    from agent_runtime.persona_assignments.chat_moves import record_chat_move

    ensure_default_scope(seed_active_pointers=False)
    _seed()
    record_chat_move("persona_chat_other_0123456789ab", CANONICAL)
    assert adopt_global_rows(apply=True)[0]["holds"] == ["chat"]


def test_a_gateway_bound_row_is_adopted():
    from agent_runtime.serve_gateway_auth.store import write_devices

    ensure_default_scope(seed_active_pointers=False)
    _seed()
    write_devices(paths.store_root(), {"dev_1": {
        "device_id": "dev_1", "tier": "console", "kind": "channel", "bound_instances": [CANONICAL]}})
    assert adopt_global_rows(apply=True)[0]["holds"] == ["gateway"]


def test_a_row_whose_chat_runs_a_goal_is_skipped_until_the_next_run(monkeypatch):
    from types import SimpleNamespace

    import agent_runtime.chat_goal as chat_goal

    ensure_default_scope(seed_active_pointers=False)
    _seed(default_chat_session_id=CHAT)
    monkeypatch.setattr(chat_goal, "bindings", lambda: [SimpleNamespace(root_session_id=CHAT)])
    assert _fates(adopt_global_rows(apply=True)) == {CANONICAL: ("skipped", "running_goal")}
    assert "adopted_from_global" not in _raw() or not _raw()["adopted_from_global"]


def test_a_default_realm_with_a_backup_remote_adopts_nothing():
    """§6 rule 1. Kill-mutation: drop the ``sync_manifest_ref`` test in ``_default_scope`` → red."""
    ensure_default_scope(seed_active_pointers=False)
    realm = RealmStore().get(DEFAULT_REALM_ID)
    realm.sync_manifest_ref = "https://example.invalid/backup.git"
    RealmStore().save(realm, emit_event=False)
    _seed(default_chat_session_id=CHAT)
    assert _fates(adopt_global_rows(apply=True)) == {CANONICAL: ("skipped", "default_realm_syncs")}
    assert not _raw().get("adopted_from_global") and CANONICAL not in _desk_ids()


def test_no_default_workspace_is_skipped_and_reported():
    _seed(default_chat_session_id=CHAT)
    assert _fates(adopt_global_rows(apply=True)) == {CANONICAL: ("skipped", "no_default_workspace")}


def _adopted_beside_a_placed_desk() -> str:
    """The adopted row plus an ordinary placed instance's desk in the same workspace (the control)."""
    from agent_runtime.agent_create.seat import seat_added_instance

    ensure_default_scope(seed_active_pointers=False)
    _seed(default_chat_session_id=CHAT)
    adopt_global_rows(apply=True)
    placed = f"{CANONICAL}_agent_2"
    _seed(placed, workspace_id=DEFAULT_WORKSPACE_ID, realm_id=DEFAULT_REALM_ID)
    assert seat_added_instance(PersonaInstanceStore().get(placed)).seated
    return placed


def test_an_adopted_agents_desk_is_not_published():
    """Kill-mutation: drop the stamp skip in ``_office_publish_scan`` → red."""
    from agent_runtime.persona_instance_sync.projection import project_persona_instances
    from agent_runtime.realm_sync.publish_scans import _office_publish_scan
    from agent_runtime.store import WorkspaceStore

    placed = _adopted_beside_a_placed_desk()
    scan = _office_publish_scan([WorkspaceStore().get(DEFAULT_WORKSPACE_ID)])
    assert placed in scan.instance_ids and CANONICAL not in scan.instance_ids
    key_of = {a.persona_instance_id: a.actor_key for a in OfficeStore().scan_actors(DEFAULT_WORKSPACE_ID).actors}
    shipped = {a.relative_path.rsplit("/", 1)[-1] for a in scan.artifacts}
    assert paths.office_actor_path(DEFAULT_WORKSPACE_ID, key_of[placed]).name in shipped
    assert paths.office_actor_path(DEFAULT_WORKSPACE_ID, key_of[CANONICAL]).name not in shipped
    # The projection's own guard, asked directly of the adopted record.
    projection = project_persona_instances({CANONICAL}, records={CANONICAL: PersonaInstanceStore().get(CANONICAL)})
    assert CANONICAL in projection.skipped_canonical


def test_an_adopted_agents_desk_is_no_drift():
    """Kill-mutation: drop the stamp skip in ``_office_store_drift_items`` → red."""
    from agent_runtime.realm_sync.drift import _office_store_drift_items
    from agent_runtime.store import WorkspaceStore

    placed = _adopted_beside_a_placed_desk()
    keys = {item.item_key for item in _office_store_drift_items(
        DEFAULT_REALM_ID, [WorkspaceStore().get(DEFAULT_WORKSPACE_ID)])}
    office = OfficeStore().scan_actors(DEFAULT_WORKSPACE_ID).actors
    key_of = {a.persona_instance_id: a.actor_key for a in office}
    assert key_of[placed] in keys and key_of[CANONICAL] not in keys


def test_a_peer_roster_omits_an_adopted_agent():
    """Kill-mutation: drop the stamp filter in ``peer_roster_projection`` → red."""
    from agent_runtime.peer_directory import peer_roster_projection

    placed = _adopted_beside_a_placed_desk()
    handles = {row.get("handle") for row in peer_roster_projection(scope_workspace_id=DEFAULT_WORKSPACE_ID)["rows"]}
    assert placed in handles and CANONICAL not in handles


def test_peer_thread_read_refuses_an_adopted_agent():
    """Kill-mutation: drop the ``peer`` refusal in ``read_chat_lane_tail`` → red."""
    from agent_runtime.peer_directory import read_chat_lane_tail

    _adopted_beside_a_placed_desk()
    refused = read_chat_lane_tail(CANONICAL, session_id=CHAT, peer=True)
    assert refused["ok"] is False and refused["error_kind"] == "unsupported_persona"
    local = read_chat_lane_tail(CANONICAL, session_id=CHAT)
    assert local.get("error_kind") != "unsupported_persona"


def test_the_dry_run_does_not_adopt_a_row_an_earlier_phase_archives():
    """A row of a persona this runtime no longer has is pruned by phase 2; the dry run's phase 7
    must not preview it as ``would_adopt`` (seen in the lane's CLI read on a bare home).
    Kill-mutation: drop the ``leaving`` test in ``adopt_global_rows`` → red."""
    ensure_default_scope(seed_active_pointers=False)
    ghost = persona_instance_id_for("ghost_persona")
    _seed(ghost, persona_id="ghost_persona", default_chat_session_id=f"persona_chat_{ghost}_0123456789ab")
    applied_twin = reconcile_persona_instances(apply=False)
    assert ghost in {item["persona_instance_id"] for item in applied_twin["pruned"]}
    assert ghost not in {item["persona_instance_id"] for item in applied_twin["adoption"]}
