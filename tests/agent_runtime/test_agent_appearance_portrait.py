"""One instance revision owns character and portrait; shared artwork survives."""
import base64
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from agent_runtime.agent_portrait import read_agent_portrait, write_agent_appearance
from agent_runtime.character_assignment import CharacterAssignmentChange, CharacterAssignmentRefused, CharacterAssignmentReplication, resolve_character_assignment
from agent_runtime.character_assignment_service import write_character_assignment
from agent_runtime.config.roster import ensure_persisted_personas
from agent_runtime.models import AgentPersona, PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.profile_avatar import ProfileAvatarRefused
from agent_runtime.profile_context import active_profile_name
from agent_runtime.states import WorkerSessionState
from agent_runtime.store import AgentStore
from hermes_constants import get_hermes_home


def png(color="red"):
    output = io.BytesIO()
    Image.new("RGBA", (24, 32), color).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def appearance(isolate_agent_runtime_root):
    home = get_hermes_home()
    (home / "assets").mkdir(parents=True, exist_ok=True)
    (home / "assets/avatar.png").write_bytes(png("blue"))
    persona = AgentPersona(id="appearance_persona", display_name="Pilot", role="dev", model=None, provider=None, api_mode=None)
    AgentStore().save(persona, character_change=CharacterAssignmentChange(0, "assigned", "chara:existing", "default"))
    for suffix in ("aabbccdd", "bbccddee"):
        instance = PersonaInstance(id=f"personainst_appearance_agent_{suffix}", persona_id=persona.id,
            role="dev", display_name="Same profile", profile_id=active_profile_name(), runtime_root="", state=WorkerSessionState.IDLE)
        PersonaInstanceStore()._write(instance)
    subject = {"kind": "instance", "id": "personainst_appearance_agent_aabbccdd", "persona_id": persona.id}
    return subject, home


def request(subject, *, color="red", revision=1, operation="appearance"):
    return {**subject, "mode": "inherit", "asset_reference": None, "expected_revision": revision,
        "operation_id": operation, "portrait": {"mode": "custom", "data_base64": base64.b64encode(png(color)).decode("ascii")}}


def test_restart_siblings_inheritance_and_ordinary_settings_saves(appearance):
    subject, home = appearance
    store = PersonaInstanceStore()
    stale = store.get(subject["id"])
    sibling_before = store.get("personainst_appearance_agent_bbccddee").character_assignment
    ack = write_agent_appearance(request(subject))
    assert ack["revision"] == 2 and ack["assignment"]["mode"] == "inherit"
    assert base64.b64decode(read_agent_portrait(subject)["data_base64"]) == png()
    assert (home / "assets/avatar.png").read_bytes() == png("blue")
    sibling = store.get("personainst_appearance_agent_bbccddee")
    assert sibling.character_assignment == sibling_before
    stale.current_chat_goal = "Keep this goal"
    store.update(stale)
    reloaded = PersonaInstanceStore().get(subject["id"])
    assert reloaded.character_assignment == ack["assignment"]
    assert reloaded.current_chat_goal == "Keep this goal"
    persona = next(p for p in ensure_persisted_personas() if p.id == subject["persona_id"])
    changed = AgentStore().save(persona, character_change=CharacterAssignmentChange(1, "assigned", "chara:next", "next-default"))
    assert resolve_character_assignment(reloaded, changed)["asset_reference"] == "chara:next"
    assert resolve_character_assignment(sibling, changed)["asset_reference"] == "chara:next"


def test_character_edit_keeps_portrait_and_explicit_reset_keeps_original_art(appearance):
    subject, home = appearance
    ack = write_agent_appearance(request(subject))
    changed = write_character_assignment({**subject, "mode": "assigned", "asset_reference": "existing-other",
        "expected_revision": 2, "operation_id": "old-client"})
    assert changed["assignment"]["portrait"] == ack["assignment"]["portrait"]
    cleared = write_agent_appearance({**request(subject, revision=3, operation="clear"), "portrait": {"mode": "character"}})
    assert cleared["assignment"]["portrait"] == {"mode": "character"}
    assert "data_base64" not in read_agent_portrait(subject)
    assert (home / "assets/avatar.png").read_bytes() == png("blue")


def test_atomic_revision_and_idempotent_ack(appearance):
    subject, _ = appearance
    draft = request(subject)
    ack = write_agent_appearance(draft)
    assert write_agent_appearance(draft) == ack
    with pytest.raises(CharacterAssignmentRefused):
        write_agent_appearance(request(subject, color="green", operation="stale"))
    with pytest.raises(CharacterAssignmentRefused):
        write_agent_appearance(request(subject, color="green"))
    assert PersonaInstanceStore().get(subject["id"]).character_assignment == ack["assignment"]


def test_concurrent_saves_have_one_owner(appearance):
    subject, _ = appearance
    def write(color):
        try:
            write_agent_appearance(request(subject, color=color, operation=color))
            return "saved"
        except CharacterAssignmentRefused:
            return "stale"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ["red", "green"])) == ["saved", "stale"]


def test_wrong_subject_and_invalid_upload_do_not_change_records(appearance):
    subject, _ = appearance
    before = PersonaInstanceStore().get(subject["id"]).character_assignment
    with pytest.raises(CharacterAssignmentRefused):
        write_agent_appearance(request({**subject, "persona_id": "another"}))
    with pytest.raises(ProfileAvatarRefused):
        write_agent_appearance({**request(subject), "portrait": {"mode": "custom", "data_base64": "not-png"}})
    assert PersonaInstanceStore().get(subject["id"]).character_assignment == before


def test_older_peer_cannot_drop_portrait_ownership(appearance):
    subject, _ = appearance
    assignment = write_agent_appearance(request(subject))["assignment"]
    older = {k: v for k, v in assignment.items() if k != "portrait"}
    with pytest.raises(CharacterAssignmentRefused, match="portrait ownership"):
        CharacterAssignmentReplication(assignment, older).apply(assignment)


def test_realm_asset_roundtrip_uses_existing_file_owner_and_refuses_tampering(appearance, tmp_path):
    from agent_runtime.realm_sync.persona_artifacts import _instance_portrait_artifacts
    from agent_runtime.persona_instance_sync import project_persona_instances
    from agent_runtime.profile_artifact_sync import read_remote_profile_files
    subject, _ = appearance
    write_agent_appearance(request(subject))
    sibling = {**subject, "id": "personainst_appearance_agent_bbccddee"}
    write_agent_appearance(request(sibling, color="green"))
    records = {p.id: p for p in PersonaInstanceStore().list_all()}
    projection = project_persona_instances([subject["id"]], records=records)
    assets, held = _instance_portrait_artifacts(projection)
    assert not _instance_portrait_artifacts(project_persona_instances([], records=records))[0]
    portrait = [a for a in assets if a.kind == "profile_portrait"]
    assert len(portrait) == 1 and not any(r["kind"] == "profile_portrait" for r in held)
    path = tmp_path / portrait[0].relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(portrait[0].read_bytes())
    entries, refusals, _, _ = read_remote_profile_files(tmp_path)
    assert not refusals and next(iter(entries.values())).data == png()
    path.write_bytes(png("green"))
    entries, refusals, _, _ = read_remote_profile_files(tmp_path)
    assert not entries and refusals[0]["code"] == "invalid_portrait"
