"""Portrait CAS writer preserves profile settings and character ownership.

Mutations: bypass expected-handle comparison; skip PNG validation; write before
the compare; advertise read tier. Each must turn the associated guard red.
"""
import base64
import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from agent_runtime.call_authorization import CALLER_DEVICE, RpcCaller, STDIO_OWNER, UNKNOWN_CALLER
from agent_runtime.media_handles import handle_for_bytes
from agent_runtime.serve_rpc import handle_request, manifest
from agent_runtime.serve_rpc.protocol import RpcContext


def portrait(color="red", size=(20, 30), fmt="PNG"):
    stream = io.BytesIO()
    Image.new("RGBA", size, color).save(stream, format=fmt)
    return stream.getvalue()


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "root" / "profiles" / "alice"
    (home / "assets").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "alice")
    return home


def call(data, expected=None, profile="alice", caller=STDIO_OWNER):
    return handle_request({"jsonrpc": "2.0", "id": "portrait", "method": "runtime.profiles.avatar.set",
                           "params": {"profile": profile, "expected_handle": expected,
                                      "data_base64": base64.b64encode(data).decode("ascii")}},
                          RpcContext(caller=caller))


def test_commit_readback_and_retry_leave_identity_and_other_art_intact(home):
    preserved = {"config.yaml": b"persona: original\nsettings: intact\n",
                 "agents.json": b'{"character":{"mode":"inherit"}}',
                 "assets/avatar.webp": b"prior custom art"}
    for path, content in preserved.items():
        (home / path).write_bytes(content)
    bob = home.parent / "bob"
    (bob / "assets").mkdir(parents=True)
    (bob / "assets/avatar.png").write_bytes(portrait("blue"))
    data = portrait()
    reply = call(data, handle_for_bytes(preserved["assets/avatar.webp"]))["result"]
    assert reply["profile"] == "alice"
    assert reply["handle"] == handle_for_bytes(data)
    assert base64.b64decode(reply["data_base64"]) == data
    assert (home / "assets/avatar.png").read_bytes() == data
    assert call(data)["result"] == reply  # lost-ack retry is idempotent
    read = handle_request({"jsonrpc": "2.0", "id": "read", "method": "runtime.profiles.avatar",
                           "params": {"profile": "alice"}}, RpcContext(caller=STDIO_OWNER))
    assert read["result"] == reply
    assert all((home / path).read_bytes() == content for path, content in preserved.items())
    assert (bob / "assets/avatar.png").read_bytes() == portrait("blue")


def test_stale_and_concurrent_writers_never_overwrite_a_new_portrait(home):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, [portrait("blue"), portrait("green")]))
    assert sum("result" in result for result in results) == 1
    loser = next(result for result in results if "error" in result)
    assert loser["error"]["data"]["reason"] == "stale_avatar"
    before = (home / "assets/avatar.png").read_bytes()
    assert call(portrait())["error"]["data"]["reason"] == "stale_avatar"
    assert (home / "assets/avatar.png").read_bytes() == before


@pytest.mark.parametrize("data", [b"invalid", b"x" * (512 * 1024 + 1),
                                  portrait(size=(1025, 1)), portrait(fmt="WEBP")],
                         ids=["invalid", "oversized", "too-wide", "webp"])
def test_invalid_upload_leaves_existing_art_untouched(home, data):
    path = home / "assets/avatar.png"
    original = portrait("blue")
    path.write_bytes(original)
    assert call(data, handle_for_bytes(original))["error"]["data"]["reason"] == "invalid_avatar"
    assert path.read_bytes() == original


@pytest.mark.parametrize("profile", ["../bob", "..\\bob", "missing", ""])
def test_invalid_subject_cannot_create_or_write_a_profile(home, profile):
    assert call(portrait(), profile=profile)["error"]["data"]["reason"] == "invalid_profile"
    assert not (home / "assets/avatar.png").exists()


def test_non_ascii_base64_is_a_typed_refusal(home):
    reply = handle_request({"jsonrpc": "2.0", "id": "bad", "method": "runtime.profiles.avatar.set", "params": {
        "profile": "alice", "expected_handle": None, "data_base64": "\u2603"}}, RpcContext(caller=STDIO_OWNER))
    assert reply["error"]["data"]["reason"] == "invalid_avatar"


def test_atomic_failure_preserves_previous_bytes(home, monkeypatch):
    original = portrait("blue")
    path = home / "assets/avatar.png"
    path.write_bytes(original)
    def fail(*args, **kwargs):
        raise OSError("fixture write failure")
    monkeypatch.setattr("utils.atomic_write_bytes", fail)
    assert call(portrait(), handle_for_bytes(original))["error"]["data"]["reason"] == "unavailable"
    assert path.read_bytes() == original


def test_write_is_console_only_and_discovery_is_explicit(home):
    assert "error" in call(portrait(), caller=UNKNOWN_CALLER)
    viewer = RpcCaller(kind=CALLER_DEVICE, device_id="viewer", device_tier="read")
    assert "error" in call(portrait(), caller=viewer)
    assert not (home / "assets/avatar.png").exists()
    published = manifest()
    assert published["tiers"]["runtime.profiles.avatar.set"] == "console"
    assert published["params"]["runtime.profiles.avatar.set"] == ["data_base64", "expected_handle", "profile"]


def test_portrait_write_preserves_real_persona_and_instance_records(home, isolate_agent_runtime_root):
    from agent_runtime.character_assignment import CharacterAssignmentChange, resolve_character_assignment
    from agent_runtime.models import AgentPersona, PersonaInstance
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from agent_runtime.states import WorkerSessionState
    from agent_runtime.store import AgentStore

    personas, instances = AgentStore(), PersonaInstanceStore()
    persona = AgentPersona(id="portrait_persona", display_name="Original", role="dev", model=None, provider=None, api_mode=None)
    personas.save(persona)
    persona = personas.save(persona, character_change=CharacterAssignmentChange(0, "assigned", "chara:anime-girl", "default"))
    instance = PersonaInstance(id="personainst_portrait_agent_aabbccdd", persona_id=persona.id,
                               role="dev", display_name="My agent", profile_id="alice", runtime_root="",
                               state=WorkerSessionState.IDLE, current_chat_goal="Keep this goal", skill_overrides=["review"])
    instances._write(instance)
    inherited = instances.get(instance.id)
    assert inherited.character_assignment["mode"] == "inherit"
    assert call(portrait())["result"]["ok"] is True
    restored_persona, restored_instance = AgentStore().get(persona.id), PersonaInstanceStore().get(instance.id)
    assert restored_persona == persona
    assert restored_instance == inherited
    assert resolve_character_assignment(restored_instance, restored_persona)["asset_reference"] == "chara:anime-girl"


def test_symlink_target_is_refused_without_touching_external_bytes(home, tmp_path):
    external = tmp_path / "outside.png"
    original = portrait("green")
    external.write_bytes(original)
    try:
        (home / "assets/avatar.png").symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("host does not permit symlinks")
    assert call(portrait(), handle_for_bytes(original))["error"]["data"]["reason"] == "unavailable"
    assert external.read_bytes() == original
