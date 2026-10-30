"""Durable character choices cannot be reverted by unrelated agent writes."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_runtime.character_assignment import (
    CharacterAssignmentChange,
    CharacterAssignmentRefused,
    resolve_character_assignment,
)
from agent_runtime.models import AgentPersona, PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import AgentStore


@pytest.fixture
def character_records(isolate_agent_runtime_root):
    persona = AgentPersona(id="profile_character_test", display_name="Character Test", role="dev", model=None, provider=None, api_mode=None)
    AgentStore().save(persona)
    store = PersonaInstanceStore()
    instance = PersonaInstance(id="personainst_character_agent_aabbccdd", persona_id=persona.id, role="dev", display_name="First", profile_id=None, runtime_root="", state=WorkerSessionState.IDLE)
    store._write(instance)
    return persona, instance


def test_restart_preserves_inherit_clear_and_assignment(character_records):
    persona, instance = character_records
    AgentStore().save(persona, character_change=CharacterAssignmentChange(0, "assigned", "chara:aura", "persona-first"))
    store = PersonaInstanceStore()
    for revision, mode, asset in [(0, "inherit", None), (1, "unassigned", None), (2, "assigned", "amelia")]:
        saved = store.set_character_assignment(instance.id, CharacterAssignmentChange(revision, mode, asset, f"write-{revision}"))
        restarted = PersonaInstanceStore().get(instance.id)
        assert restarted.character_assignment == saved.character_assignment
        resolved = resolve_character_assignment(restarted, AgentStore().get(persona.id))
        assert resolved["authority"] == "record"
        assert resolved["asset_reference"] == ("chara:aura" if mode == "inherit" else asset)


def test_inheritance_tracks_persona_but_a_sibling_override_does_not(character_records):
    persona, instance = character_records
    store = PersonaInstanceStore()
    inherited = store.set_character_assignment(instance.id, CharacterAssignmentChange(0, "inherit", None, "inherit"))
    sibling = PersonaInstance(id="personainst_character_agent_11223344", persona_id=persona.id, role="dev", display_name="Sibling", profile_id=None, runtime_root="", state=WorkerSessionState.IDLE)
    store._write(sibling)
    fixed = store.set_character_assignment(sibling.id, CharacterAssignmentChange(0, "assigned", "other", "sibling"))
    for revision, asset in enumerate(["amelia", "chara:aura"]):
        base = AgentStore().save(persona, character_change=CharacterAssignmentChange(revision, "assigned", asset, f"default-{revision}"))
        assert resolve_character_assignment(inherited, base)["asset_reference"] == asset
        assert resolve_character_assignment(fixed, base)["asset_reference"] == "other"
    assert store.get(instance.id).persona_id == persona.id


def test_stale_whole_row_saves_keep_character_choices_and_other_settings(character_records):
    persona, instance = character_records
    store = PersonaInstanceStore()
    stale = store.get(instance.id)
    receipt = {"version": 1, "sources": [{"source": "office", "value": "amelia"}]}
    picked = store.set_character_assignment(instance.id, CharacterAssignmentChange(0, "assigned", "amelia", "pick", receipt))
    stale.current_chat_goal = "Preserved goal"
    stale.skill_overrides = ["existing-skill"]
    store.update(stale)
    after = store.get(instance.id)
    assert after.character_assignment == picked.character_assignment
    assert (after.current_chat_goal, after.skill_overrides) == ("Preserved goal", ["existing-skill"])
    chosen_persona = AgentStore().save(persona, character_change=CharacterAssignmentChange(0, "unassigned", None, "clear"))
    persona.display_name = "Renamed"
    AgentStore().save(persona)
    assert AgentStore().get(persona.id).character_assignment == chosen_persona.character_assignment
    assert AgentStore().get(persona.id).display_name == "Renamed"


def test_retry_is_idempotent_and_stale_or_reused_operations_refuse(character_records):
    _, instance = character_records
    store = PersonaInstanceStore()
    change = CharacterAssignmentChange(0, "assigned", "amelia", "retry")
    first = store.set_character_assignment(instance.id, change)
    assert store.set_character_assignment(instance.id, change).character_assignment == first.character_assignment
    with pytest.raises(CharacterAssignmentRefused, match="Operation id"):
        store.set_character_assignment(instance.id, CharacterAssignmentChange(0, "unassigned", None, "retry"))
    with pytest.raises(CharacterAssignmentRefused, match="current assignment"):
        store.set_character_assignment(instance.id, CharacterAssignmentChange(0, "assigned", "different", "stale"))


def test_concurrent_character_writes_have_one_winner(character_records):
    _, instance = character_records

    def write(asset):
        try:
            PersonaInstanceStore().set_character_assignment(instance.id, CharacterAssignmentChange(0, "assigned", asset, asset))
            return "saved"
        except CharacterAssignmentRefused:
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["amelia", "other"]))
    assert sorted(results) == ["saved", "stale"]
    assert PersonaInstanceStore().get(instance.id).character_assignment["revision"] == 1


@pytest.mark.parametrize("mode,asset,revision", [("assigned", "chara:", 0), ("unassigned", "amelia", 0), ("unknown", None, 0), ("assigned", "amelia", True)])
def test_invalid_changes_do_not_activate_or_modify_records(character_records, mode, asset, revision):
    _, instance = character_records
    with pytest.raises(CharacterAssignmentRefused):
        PersonaInstanceStore().set_character_assignment(instance.id, CharacterAssignmentChange(revision, mode, asset, "invalid"))
    assert PersonaInstanceStore().get(instance.id).character_assignment is None


def test_config_persona_keeps_other_defaults_live(isolate_agent_runtime_root):
    from hermes_constants import get_config_path
    from utils import atomic_roundtrip_yaml_update
    from agent_runtime import paths
    from agent_runtime.config.roster import ensure_persisted_personas

    config = get_config_path()
    atomic_roundtrip_yaml_update(config, "agent_runtime.personas.character_config", {
        "display_name": "Config persona", "role": "dev", "model": "original-model",
    })
    persona = next(p for p in ensure_persisted_personas() if p.id == "character_config")
    AgentStore().save(persona, character_change=CharacterAssignmentChange(0, "assigned", "amelia", "config-choice"))
    assert not paths.agent_path(persona.id).exists()
    atomic_roundtrip_yaml_update(config, "agent_runtime.personas.character_config.model", "new-model")
    reloaded = next(p for p in ensure_persisted_personas() if p.id == persona.id)
    assert reloaded.model == "new-model"
    assert reloaded.character_assignment["asset_reference"] == "amelia"
    # A different editor can still hold the pre-migration config persona.
    # Its existing whole-record save must carry the latest assignment forward.
    persona.display_name = "Renamed from older draft"
    saved = AgentStore().save(persona)
    assert saved.character_assignment == reloaded.character_assignment
    assert AgentStore().get(persona.id).character_assignment == reloaded.character_assignment
    assert saved.display_name == "Renamed from older draft"


def test_unknown_future_record_is_unavailable_and_survives_unrelated_save(character_records):
    import json
    from agent_runtime import paths

    persona, instance = character_records
    path = paths.persona_instance_path(instance.id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["character_assignment"] = {"version": 99, "future": "keep"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    read = PersonaInstanceStore().get(instance.id)
    assert resolve_character_assignment(read, persona)["authority"] == "unavailable"
    read.display_name = "Changed name"
    PersonaInstanceStore().update(read)
    assert PersonaInstanceStore().get(instance.id).character_assignment == raw["character_assignment"]


def test_realm_adoption_preserves_local_state_and_old_peer_omission(character_records):
    from agent_runtime.persona_instance_sync import project_persona_instance

    _, instance = character_records
    store = PersonaInstanceStore()
    assigned = store.set_character_assignment(instance.id, CharacterAssignmentChange(0, "assigned", "amelia", "local"))
    body = project_persona_instance(assigned)
    body.pop("character_assignment")
    body["display_name"] = "Peer name"
    # The snapshot used by the pull predates a local execution-state update.
    running = store.get(instance.id)
    running.active_run_id = "local-run"
    store.update(running)
    store.replicate_instance(body, realm_id="realm_character", adopt_existing=assigned)
    reloaded = store.get(instance.id)
    assert reloaded.character_assignment == assigned.character_assignment
    assert reloaded.active_run_id == "local-run"
    assert reloaded.display_name == "Peer name"


def test_new_instance_inherits_migrated_persona_without_cutting_over_old_siblings(character_records):
    from dataclasses import replace

    persona, legacy = character_records
    store = PersonaInstanceStore()
    persona = AgentStore().save(persona, character_change=CharacterAssignmentChange(0, "assigned", "amelia", "default"))
    created = replace(legacy, id="personainst_character_new_33445566")
    store._write(created)
    restarted = store.get(created.id)
    assert restarted.character_assignment["mode"] == "inherit"
    assert resolve_character_assignment(restarted, persona)["asset_reference"] == "amelia"
    store.update(legacy)
    assert store.get(legacy.id).character_assignment is None
    persona = AgentStore().save(persona, character_change=CharacterAssignmentChange(1, "assigned", "chara:aura", "changed-default"))
    assert resolve_character_assignment(restarted, persona)["asset_reference"] == "chara:aura"
