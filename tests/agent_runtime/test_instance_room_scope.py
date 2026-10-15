"""Room membership is explicit identity, not a workspace placement change."""
import pytest

from agent_runtime import paths
from agent_runtime.discussions.definitions import ParticipantRef
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore
from agent_runtime.workspace_create import conversations_workspace
from hermes_constants import get_hermes_home
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent, PERSONA, WORKSPACE


def test_explicit_room_member_keeps_placement_and_table_scope(monkeypatch, placed_agent):
    home = get_hermes_home()
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    context = NativeContext(paths.store_root(), home, "install")
    room_home = conversations_workspace().id
    ref = ParticipantRef("install", placed_agent["persona_instance_id"])
    store = PersonaInstanceStore()
    before = store.get(ref.instance_id)
    member = context.resolve_room(ref, room_home)
    assert member["instance_id"] == before.id
    assert member == context.resolve_member({"workspace_id": room_home, "table_id": None}, member)
    with pytest.raises(DiscussionError, match="foreign workspace"):
        context.resolve(ref, room_home)
    assert context.resolve(ref, WORKSPACE) == member
    assert store.get(ref.instance_id) == before

    persona = AgentStore().get(PERSONA)
    persona.hermes_profile = "missing_profile"
    AgentStore().save(persona)
    unavailable = context.resolve_room(ref, room_home)
    assert unavailable["profile"] == "missing_profile"
    with pytest.raises(DiscussionError, match="profile unavailable"):
        context.resolve_member({"workspace_id": room_home, "table_id": None}, unavailable)
    assert store.get(ref.instance_id) == before
