"""Character cutover preserves placement history and refuses ambiguous sources."""

import copy

import pytest

from agent_runtime import paths
from agent_runtime.character_assignment import CharacterAssignmentRefused
from agent_runtime.character_assignment_service import preview_character_migration, write_character_assignment
from agent_runtime.models import AgentPersona, PersonaInstance
from agent_runtime.office_store import OfficeStore
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import AgentStore, WorkspaceStore


@pytest.fixture
def character_migration_subject(isolate_agent_runtime_root):
    persona = AgentPersona(id="character_migration", display_name="Pilot", role="dev", model=None, provider=None, api_mode=None)
    AgentStore().save(persona)
    instance = PersonaInstance(id="personainst_migration_agent_abcddcba", persona_id=persona.id, role="dev", display_name="Pilot instance", profile_id=None, runtime_root="", state=WorkerSessionState.IDLE)
    PersonaInstanceStore()._write(instance)
    workspace = WorkspaceStore().create(name="Character migration")
    payload = {"persona_id": persona.id, "persona_instance_id": instance.id, "items": [
        {"item_id": "migration_agent_abcddcba", "persona_id": persona.id, "kind": "agent", "position": [1, 2], "pet_slug": "amelia"},
    ]}
    actor = OfficeStore().upsert_actor(workspace.id, payload)
    subject = {"kind": "instance", "id": instance.id, "persona_id": persona.id}
    return subject, workspace.id, actor, payload


def _migration_request(subject, **extra):
    preview = preview_character_migration({**subject, **extra})
    return {**subject, **extra, "expected_revision": preview["revision"], "source_fingerprint": preview["source_fingerprint"], "operation_id": "migration-test"}


def test_migration_ack_and_restart_keep_original_bytes(character_migration_subject):
    subject, workspace, actor, _ = character_migration_subject
    path = paths.office_actor_path(workspace, actor.actor_key)
    before = path.read_bytes()
    request = _migration_request(subject)
    ack = write_character_assignment(request, migrate=True)
    assert ack["id"] == subject["id"] and ack["revision"] == 1
    assert ack["assignment"]["asset_reference"] == "amelia"
    assert ack["assignment"]["migration_receipt"]["sources"][0]["item_id"] == "migration_agent_abcddcba"
    assert path.read_bytes() == before
    assert PersonaInstanceStore().get(subject["id"]).character_assignment == ack["assignment"]
    assert write_character_assignment(request, migrate=True) == ack


def test_stale_inventory_does_not_activate_record(character_migration_subject):
    subject, workspace, actor, payload = character_migration_subject
    request = _migration_request(subject)
    changed = copy.deepcopy(payload)
    changed["items"][0]["pet_slug"] = "changed-before-migration"
    OfficeStore().upsert_actor(workspace, changed, expect_revision=actor.revision)
    with pytest.raises(CharacterAssignmentRefused, match="current migration inventory"):
        write_character_assignment(request, migrate=True)
    assert PersonaInstanceStore().get(subject["id"]).character_assignment is None


def test_conflicting_local_source_is_retained_until_explicit_choice(character_migration_subject):
    subject, workspace, actor, _ = character_migration_subject
    request = _migration_request(subject, local_sources=[{"scope": "view:workspace", "value": "other"}])
    before = paths.office_actor_path(workspace, actor.actor_key).read_bytes()
    with pytest.raises(CharacterAssignmentRefused, match="disagree"):
        write_character_assignment(request, migrate=True)
    assert PersonaInstanceStore().get(subject["id"]).character_assignment is None
    ack = write_character_assignment({**request, "mode": "assigned", "asset_reference": "chosen"})
    assert ack["assignment"]["asset_reference"] == "chosen"
    assert {s["value"] for s in ack["assignment"]["migration_receipt"]["sources"]} == {"amelia", "other"}
    assert paths.office_actor_path(workspace, actor.actor_key).read_bytes() == before


def test_old_client_can_move_but_cannot_change_migrated_character(character_migration_subject):
    subject, workspace, actor, payload = character_migration_subject
    write_character_assignment(_migration_request(subject), migrate=True)
    moved = copy.deepcopy(payload)
    moved["items"][0]["position"] = [7, 8]
    accepted = OfficeStore().upsert_actor(workspace, moved, expect_revision=actor.revision)
    assert accepted.items[0].position == [7, 8]
    moved["items"][0]["pet_slug"] = "stale-client-change"
    with pytest.raises(CharacterAssignmentRefused, match="agent record"):
        OfficeStore().upsert_actor(workspace, moved, expect_revision=accepted.revision)
    assert OfficeStore().get_actor(workspace, actor.actor_key).items[0].pet_slug == "amelia"


def test_identity_mismatch_has_no_write(character_migration_subject):
    subject, _, _, _ = character_migration_subject
    with pytest.raises(CharacterAssignmentRefused, match="identity"):
        preview_character_migration({**subject, "persona_id": "someone_else"})
    assert PersonaInstanceStore().get(subject["id"]).character_assignment is None


def test_migration_retry_cannot_restore_old_character_after_edit(character_migration_subject):
    subject, _, _, _ = character_migration_subject
    request = _migration_request(subject)
    write_character_assignment(request, migrate=True)
    changed = write_character_assignment({**subject, "expected_revision": 1, "operation_id": "clear", "mode": "unassigned", "asset_reference": None})
    assert write_character_assignment(request, migrate=True) == changed


def test_startup_migrates_verified_placements_once_without_a_new_identity(character_migration_subject, monkeypatch):
    from agent_runtime.character_assignment_migration import migrate_authored_character_assignments

    subject, workspace, actor, _ = character_migration_subject
    before = paths.office_actor_path(workspace, actor.actor_key).read_bytes()
    scans = []
    scan = OfficeStore.scan_actors

    def counted(store, workspace_id, **kwargs):
        scans.append(workspace_id)
        return scan(store, workspace_id, **kwargs)

    monkeypatch.setattr(OfficeStore, "scan_actors", counted)
    result = migrate_authored_character_assignments()
    assert result["migrated"] == [subject["id"]]
    assert scans == [workspace]
    assert paths.office_actor_path(workspace, actor.actor_key).read_bytes() == before
    assert PersonaInstanceStore().get(subject["id"]).persona_id == subject["persona_id"]
    assert migrate_authored_character_assignments()["migrated"] == []
    assert scans == [workspace]


def test_startup_preserves_mixed_explicit_and_inherited_placements(character_migration_subject):
    from agent_runtime.character_assignment_migration import migrate_authored_character_assignments

    subject, workspace, actor, payload = character_migration_subject
    mixed = copy.deepcopy(payload)
    mixed["items"].append({**mixed["items"][0], "item_id": "another_placement", "pet_slug": None})
    OfficeStore().upsert_actor(workspace, mixed, expect_revision=actor.revision)
    before = paths.office_actor_path(workspace, actor.actor_key).read_bytes()
    result = migrate_authored_character_assignments()
    assert result["migrated"] == []
    assert result["retained"][subject["id"]] == "character_migration_conflict"
    assert PersonaInstanceStore().get(subject["id"]).character_assignment is None
    assert paths.office_actor_path(workspace, actor.actor_key).read_bytes() == before


def test_rpc_authorizes_writes_and_returns_the_saved_subject(character_migration_subject):
    from agent_runtime.call_authorization import UNKNOWN_CALLER
    from agent_runtime.serve_rpc import handle_request
    from agent_runtime.serve_rpc.protocol import RpcContext

    subject, _, _, _ = character_migration_subject
    request = {"jsonrpc": "2.0", "id": "preview", "method": "runtime.character.assignment.preview_migration", "params": subject}
    for invalid_kind in ([], {}, None):
        invalid = {**request, "params": {**subject, "kind": invalid_kind}}
        refused = handle_request(invalid)["error"]
        assert refused["data"]["reason"] == "invalid_character_assignment"
    preview = handle_request(request, RpcContext(caller=UNKNOWN_CALLER))["result"]
    request.update(id="migrate", method="runtime.character.assignment.migrate", params={
        **subject, "expected_revision": 0, "operation_id": "rpc-migrate", "source_fingerprint": preview["source_fingerprint"],
    })
    assert "error" in handle_request(request, RpcContext(caller=UNKNOWN_CALLER))
    assert PersonaInstanceStore().get(subject["id"]).character_assignment is None
    ack = handle_request(request)["result"]
    assert ack["id"] == subject["id"] and ack["assignment"]["asset_reference"] == "amelia"
    request.update(method="runtime.character.assignment.set", params={**subject, "expected_revision": 0, "operation_id": "stale", "mode": "unassigned"})
    refused = handle_request(request)["error"]
    assert refused["data"]["reason"] == "stale_character_revision"
    assert PersonaInstanceStore().get(subject["id"]).character_assignment == ack["assignment"]
