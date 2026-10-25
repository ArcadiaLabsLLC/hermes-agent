"""Native room model controls share exact-session storage and admission guards."""
from contextlib import closing

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.discussions.service import DiscussionService
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_session import _chat_model_override_from_config, _session_model_config
from agent_runtime.session_model_catalog import model_key
from hermes_constants import get_hermes_home
from tests.agent_runtime.office_seed import seed_workspace_record
from tests.agent_runtime.test_discussion_runtime import room_timings, wait_until
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OWNER, OTHER
from tests.agent_runtime.test_operator_session_models import catalog, PROVIDER
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent, PERSONA, WORKSPACE

pytestmark = pytest.mark.timeout(90)


@pytest.fixture
def native_room(placed_agent, catalog):
    second = serve_rpc.handle_request(dict(jsonrpc="2.0", id="second", method="runtime.agent.create",
        params=dict(persona_id=PERSONA, workspace_id=WORKSPACE, position=[3.0, 2.0],
                    idempotency_key="second-model-member")))["result"]
    install = ensure_install_identity(paths.store_root()).install_id
    seed_workspace_record("ws_conversations")
    context = NativeContext(paths.store_root(), get_hermes_home(), install)
    service = DiscussionService(context, **room_timings())
    service.start()
    try:
        run = execute(service, "run.start_room", dict(workspace_id="ws_conversations",
            idempotency_key="models", topic="", client_scope=OWNER,
            spec=dict(name="Native room", participants=[
                dict(install_id=install, instance_id=row["persona_instance_id"])
                for row in (placed_agent, second)],
                settings=dict(rounds=1, user_participates=True, allow_invitations=True,
                              moderator=None))), actor_id="operator")["run"]
        wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "open")
        yield service, run, service.runs.members(run["run_id"])
    finally:
        service.close()


def model_call(service, run, member, *, owner=OWNER, **values):
    return execute(service, "run.member_model" if values else "run.member_models",
        dict(workspace_id=run["workspace_id"], run_id=run["run_id"],
             member_id=member["member_id"], client_scope=owner, **values),
        actor_id="operator")["facts"]


def test_native_member_model_changes_only_exact_room_session(native_room):
    service, run, (first, second) = native_room
    store = PersonaInstanceStore()
    before = store.get(first["instance_id"])
    facts = model_call(service, run, first)
    peer = model_call(service, run, second)
    chosen = model_call(service, run, first, model_id=model_key(PROVIDER, "first"))
    assert chosen["session_id"] == facts["session_id"] == first["session_id"]
    assert chosen["current_model_id"] == model_key(PROVIDER, "first")
    assert model_call(service, run, second)["current_model_id"] == peer["current_model_id"]
    assert store.get(first["instance_id"]) == before
    with closing(default_persona_session_db()) as db:
        config = _session_model_config(db, first["session_id"])
        assert config["client_scope"] == OWNER
        assert _chat_model_override_from_config(config)["model"] == "first"
    assert not service.attempts.rows(run["run_id"])
    saved = model_call(service, run, first, model_id=model_key(PROVIDER, "second"), save_default=True)
    assert saved["default_model_id"] == model_key(PROVIDER, "second")
    after = store.get(first["instance_id"])
    assert after.model == "second"
    assert after.default_chat_session_id == before.default_chat_session_id
    assert after.workspace_id == WORKSPACE


def test_native_member_model_refuses_foreign_owner_and_unsettled_turn(native_room):
    service, run, (member, _) = native_room
    choice = dict(model_id=model_key(PROVIDER, "first"))
    with pytest.raises(DiscussionError, match="conversation owner changed"):
        model_call(service, run, member, owner=OTHER, **choice)
    with pytest.raises(DiscussionError, match="member not found"):
        model_call(service, run, {"member_id": "missing"}, **choice)
    persist_mission_chat_turn(session_id=member["session_id"], client_message_id="pending",
                             turn_id="pending", state="outcome_unknown", elements=[])
    with pytest.raises(DiscussionError, match="conversation busy"):
        model_call(service, run, member, **choice)
    with closing(default_persona_session_db()) as db:
        assert _chat_model_override_from_config(_session_model_config(db, member["session_id"])) is None
