"""Instance rooms use the same model authority as operator chat."""
from contextlib import closing
from dataclasses import replace

import pytest

from agent_runtime import paths
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.service import DiscussionService
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_assignments import PersonaInstanceStore
from hermes_state import SessionDB
from agent_runtime.persona_chat_session import _chat_model_override_from_config, _session_model_config
from agent_runtime.mission_chat_turns import persist_mission_chat_turn
from agent_runtime.session_model_catalog import model_key
from agent_runtime.workspace_create import conversations_workspace
from hermes_constants import get_hermes_home
from tests.agent_runtime.test_discussion_runtime import wait_until
from tests.agent_runtime.test_instance_conversation_owner import chat_head, OWNER, OTHER
from tests.agent_runtime.test_operator_session_models import catalog, PROVIDER
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent

pytestmark = pytest.mark.timeout(60)


def test_room_models_preserve_instance_owner_peer_and_busy_work(placed_agent, catalog):
    store = PersonaInstanceStore()
    first = store.get(placed_agent["persona_instance_id"])
    second = replace(first, id=first.id + "_two")
    store._write(second)
    install = ensure_install_identity(paths.store_root()).install_id
    workspace = conversations_workspace().id
    context = NativeContext(paths.store_root(), get_hermes_home(), install)
    service = DiscussionService(context, active_poll_interval=.01)
    service.start()
    try:
        spec = {"name": "Pair", "participants": [
            {"install_id": install, "instance_id": p.id} for p in (first, second)],
            "settings": {"rounds": 3, "allow_invitations": True,
                         "user_participates": True, "moderator": None}}
        run = execute(service, "run.start_room", {
            "workspace_id": workspace, "spec": spec, "idempotency_key": "new",
            "topic": "", "client_scope": OWNER}, actor_id="operator")["run"]
        wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "open")
        a, b = service.runs.members(run["run_id"])
        params = {"workspace_id": workspace, "run_id": run["run_id"],
                  "member_id": a["member_id"], "client_scope": OWNER}
        facts = execute(service, "run.member_models", params, actor_id="operator")["facts"]
        assert facts["session_id"] == a["session_id"]
        selected = execute(service, "run.member_model", {
            **params, "model_id": model_key(PROVIDER, "first")}, actor_id="operator")["facts"]
        assert selected["current_model_id"] == model_key(PROVIDER, "first")
        with closing(SessionDB(db_path=context.home / "state.db", read_only=True)) as db:
            assert _chat_model_override_from_config(_session_model_config(db, a["session_id"]))["model"] == "first"
            assert _chat_model_override_from_config(_session_model_config(db, b["session_id"])) is None
            assert db.get_session(a["session_id"])["cwd"]
        assert store.get(first.id) == first and store.get(second.id) == second
        with pytest.raises(DiscussionError, match="conversation owner changed"):
            execute(service, "run.member_models", {**params, "client_scope": OTHER}, actor_id="operator")
        persist_mission_chat_turn(session_id=a["session_id"], client_message_id="uncertain",
            turn_id="uncertain", state="outcome_unknown", elements=[])
        with pytest.raises(DiscussionError, match="conversation busy"):
            execute(service, "run.member_model", {
                **params, "model_id": model_key(PROVIDER, "second")}, actor_id="operator")
    finally:
        service.close()
