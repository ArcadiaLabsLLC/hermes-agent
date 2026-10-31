"""Reviewed reconciliation and full-store recovery retain one assignment owner.

All writes use the normal command/store owners under the fixture's isolated root.
Recovery exercises a stopped-store copy, never a downgrade to a legacy writer.
"""

import base64
import copy
import shutil

import pytest

from agent_runtime import paths
from agent_runtime.character_assignment import CharacterAssignmentRefused, resolve_character_assignment
from agent_runtime.character_assignment_migration import migrate_authored_character_assignments
from agent_runtime.character_assignment_service import preview_character_migration, write_character_assignment
from agent_runtime.models import AgentPersona, PersonaInstance
from agent_runtime.office_store import OfficeStore
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import AgentStore, WorkspaceStore
from agent_runtime.serve_rpc import handle_request


@pytest.fixture
def recovery_subject(isolate_agent_runtime_root):
    persona = AgentPersona(id="recovery_character", display_name="Recovery", role="dev", model=None, provider=None, api_mode=None)
    AgentStore().save(persona)
    store = PersonaInstanceStore()
    instances = []
    for suffix in ("aabbccdd", "11223344"):
        instance = PersonaInstance(id=f"personainst_recovery_agent_{suffix}", persona_id=persona.id,
            role="dev", display_name=suffix, profile_id=None, runtime_root="",
            current_chat_goal="Keep this goal", skill_overrides=["existing-skill"], state=WorkerSessionState.IDLE)
        store._write(instance)
        instances.append(instance)
    workspace = WorkspaceStore().create(name="Recovery office")
    payload = {"persona_id": persona.id, "persona_instance_id": instances[0].id, "items": [
        {"item_id": "recovery_agent_aabbccdd", "persona_id": persona.id, "kind": "agent", "position": [1, 2]},
    ]}
    actor = OfficeStore().upsert_actor(workspace.id, payload)
    return persona, instances, workspace.id, actor, payload


def _reviewed_choice(subject, mode, asset=None, *, operation="reviewed", sources=None):
    request = {**subject, "local_sources": sources or []}
    preview = preview_character_migration(request)
    return {**request, "expected_revision": preview["revision"],
        "source_fingerprint": preview["source_fingerprint"], "operation_id": operation,
        "mode": mode, "asset_reference": asset}


def test_reviewed_inheritance_keeps_unverified_history_and_sibling(recovery_subject):
    persona, instances, workspace, actor, _ = recovery_subject
    subject = {"kind": "instance", "id": instances[0].id, "persona_id": persona.id}
    actor_path = paths.office_actor_path(workspace, actor.actor_key)
    original = actor_path.read_bytes()
    result = migrate_authored_character_assignments()
    assert result["retained"][subject["id"]] == "character_migration_conflict"
    assert PersonaInstanceStore().get(subject["id"]).character_assignment is None
    # A concrete reviewed choice, not a guessed relationship between artworks.
    local = [{"scope": "view:legacy-persona-default", "value": "original-pet"}]
    request = _reviewed_choice(subject, "inherit", sources=local)
    ack = write_character_assignment(request)
    assert write_character_assignment(request) == ack
    receipt = ack["assignment"]["migration_receipt"]
    assert receipt["source_fingerprint"] == request["source_fingerprint"]
    assert {source["value"] for source in receipt["sources"]} == {None, "original-pet"}
    default_subject = {"kind": "persona", "id": persona.id, "persona_id": persona.id}
    for asset in ("original-pet", "chara:aura"):
        write_character_assignment(_reviewed_choice(default_subject, "assigned", asset, operation=asset))
        inherited = PersonaInstanceStore().get(subject["id"])
        assert resolve_character_assignment(inherited, AgentStore().get(persona.id))["asset_reference"] == asset
        assert inherited.character_assignment["migration_receipt"] == receipt
    assert PersonaInstanceStore().get(instances[1].id).character_assignment is None
    assert actor_path.read_bytes() == original


@pytest.mark.parametrize("mode, asset", [("inherit", None), ("unassigned", None), ("assigned", "existing-pet")])
def test_record_aware_recovery_preserves_choices_receipts_and_settings(recovery_subject, tmp_path, monkeypatch, mode, asset):
    persona, instances, workspace, actor, payload = recovery_subject
    subject = {"kind": "instance", "id": instances[0].id, "persona_id": persona.id}
    default_subject = {"kind": "persona", "id": persona.id, "persona_id": persona.id}
    write_character_assignment(_reviewed_choice(default_subject, "assigned", "persona-pet"))
    request = _reviewed_choice(subject, mode, asset)
    ack = write_character_assignment(request)
    root = paths.store_root()
    assert root.is_relative_to(tmp_path)
    profile_home = tmp_path / "profiles" / "existing-profile"
    monkeypatch.setenv("HERMES_HOME", str(profile_home))
    monkeypatch.setenv("HERMES_PROFILE", "existing-profile")
    portrait = profile_home / "assets" / "avatar.png"
    portrait.parent.mkdir(parents=True, exist_ok=True)
    portrait_bytes = b"\x89PNG\r\n\x1a\nexisting custom portrait: keep independent of character"
    portrait.write_bytes(portrait_bytes)
    # This is a quiescent full-store recovery checkpoint, AFTER acknowledged edits.
    # Restoring a pre-migration backup would discard those edits and is not tested
    # or advertised as safe rollback.
    checkpoint = tmp_path / "recovery-checkpoint"
    shutil.copytree(root, checkpoint)
    profile_checkpoint = tmp_path / "profile-checkpoint"
    shutil.copytree(profile_home, profile_checkpoint)
    original_files = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    store = PersonaInstanceStore()
    later = store.get(subject["id"])
    later.current_chat_goal = "Simulated damaged generation"
    store.update(later)
    shutil.copytree(checkpoint, root, dirs_exist_ok=True)
    shutil.copytree(profile_checkpoint, profile_home, dirs_exist_ok=True)
    assert all((root / name).read_bytes() == value for name, value in original_files.items())
    restarted = PersonaInstanceStore().get(subject["id"])
    assert restarted.character_assignment == ack["assignment"]
    assert (restarted.persona_id, restarted.current_chat_goal, restarted.skill_overrides) == (
        persona.id, "Keep this goal", ["existing-skill"])
    assert resolve_character_assignment(restarted, AgentStore().get(persona.id))["asset_reference"] == (
        "persona-pet" if mode == "inherit" else asset)
    assert write_character_assignment(request) == ack
    with pytest.raises(CharacterAssignmentRefused, match="current assignment"):
        write_character_assignment({**subject, "expected_revision": 0,
            "operation_id": "stale-editor", "mode": "assigned", "asset_reference": "wrong"})
    assert portrait.read_bytes() == portrait_bytes
    portrait_reply = handle_request({"jsonrpc": "2.0", "id": "portrait", "method": "runtime.profiles.avatar",
        "params": {"profile": "existing-profile"}})["result"]
    assert portrait_reply["ok"] is True
    assert base64.b64decode(portrait_reply["data_base64"]) == portrait_bytes
    # Old-client placement movement is allowed; its character writer is fenced.
    moved = copy.deepcopy(payload)
    moved["items"][0]["position"] = [3, 4]
    current = OfficeStore().upsert_actor(workspace, moved, expect_revision=actor.revision)
    moved["items"][0]["pet_slug"] = "wrong"
    with pytest.raises(CharacterAssignmentRefused, match="agent record"):
        OfficeStore().upsert_actor(workspace, moved, expect_revision=current.revision)
    assert PersonaInstanceStore().get(subject["id"]).character_assignment == ack["assignment"]
    assert migrate_authored_character_assignments()["migrated"] == []
