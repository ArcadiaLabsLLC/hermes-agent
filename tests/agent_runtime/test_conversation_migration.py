"""A retired profile conversation's route is adopted into an agent's chat: real route receipts and
canonical SessionDB imports, with no worker and no turn (``conversations.legacy_routes``)."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os

import psutil
import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE
from agent_runtime.conversation_owner import session_client_scope
from agent_runtime.conversations import migration
from agent_runtime.conversations.legacy_routes import LegacyRoutes
from agent_runtime.conversations.model import ConversationError, Refusal, TurnState, caller_scope
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_mints import PersonaChatMintTransaction
from hermes_state import SessionDB
from tests.agent_runtime.legacy_conversation_seed import seed_route, seed_turn, set_worker
from tests.agent_runtime.test_instance_conversation_owner import OWNER, OTHER, chat_head
from tests.agent_runtime.test_serve_rpc_open_chat import PERSONA, WORKSPACE, qa_persona, placed_agent


@pytest.fixture
def legacy(placed_agent, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_PROFILE", "default")
    home = tmp_path / "old-profile"
    home.mkdir()
    install = ensure_install_identity(paths.store_root()).install_id
    (tmp_path / "receipts").mkdir()
    service = LegacyRoutes(tmp_path / "receipts", install, profile_home=lambda _: home)
    scope = caller_scope(LOCAL_CONSOLE, OWNER, "default")
    route = seed_route(service.store, scope, "old-thread", str(tmp_path), home, native_id="legacy-root",
                       turns=[("old-turn", TurnState.COMPLETED)], worker=(2147480000, 1.0))
    params = {"install_id": install, "client_scope": OWNER, "profile": "default", "session_id": route.id,
              "persona_id": PERSONA, "persona_instance_id": placed_agent["persona_instance_id"]}
    with closing(SessionDB(db_path=home / "state.db")) as db:
        result = db.import_sessions([
            {"id": "legacy-root", "source": "eternia_intelligence", "started_at": 1,
             "end_reason": "compression", "ended_at": 2, "title": "Existing work", "messages": [
                 {"role": "user", "content": "Original request", "timestamp": 1},
                 {"role": "assistant", "content": "Archived answer", "timestamp": 2,
                  "active": 0, "compacted": 1}]},
            {"id": "legacy-tip", "source": "eternia_intelligence", "started_at": 3,
             "parent_session_id": "legacy-root", "messages": [
                 {"role": "assistant", "content": "Current answer", "timestamp": 3}]},
        ])
        assert result["ok"] and result["imported"] == 2
    yield service, scope, params, home


def migrate(legacy, **changes):
    service, scope, params, _ = legacy
    return service.migrate(scope, params["session_id"], {**params, **changes})


def selected(instance_id):
    instance = PersonaInstanceStore().get(instance_id)
    return instance.session_id, instance.default_chat_session_id


def test_imported_choice_is_used_by_native_inspection_and_next_turn_without_changing_defaults(legacy):
    from agent_runtime.operator_session_inspection import inspect_operator_settings
    from agent_runtime.persona_chat_session import _chat_model_override_from_config, _session_model_config
    from tests.agent_runtime.test_operator_session_models import next_turn

    _, _, params, home = legacy
    before = PersonaInstanceStore().get(params["persona_instance_id"])
    with closing(SessionDB(db_path=home / "state.db")) as db:
        db.update_session_meta("legacy-root", json.dumps({"provider": "anthropic"}), "earlier-model")
        db.update_session_meta("legacy-tip", json.dumps({"provider": "openai-codex",
            "reasoning_config": {"effort": "high"}}), "gpt-6-luna")
        donor = db.export_session_lineage("legacy-root", include_inactive=True)
    result = migrate(legacy)
    target = {**params, "session_id": result["session_id"], "workspace_id": result["workspace_id"]}
    effective = inspect_operator_settings(target)["model"]
    assert effective["effective_provider"] == "openai-codex"
    assert effective["effective_model"] == "gpt-6-luna"
    assert effective["effective_reasoning_effort"] == "high"
    admitted = next_turn(target)
    assert admitted["effective_provider"] == "openai-codex"
    assert admitted["effective_model"] == "gpt-6-luna"
    with closing(default_persona_session_db()) as db:
        override = _chat_model_override_from_config(_session_model_config(db, result["session_id"]))
        assert override["provider"] == "openai-codex" and override["model"] == "gpt-6-luna"
        assert override["source"] == "profile_migration"
    assert PersonaInstanceStore().get(params["persona_instance_id"]) == before
    with closing(SessionDB(db_path=home / "state.db", read_only=True)) as db:
        assert db.export_session_lineage("legacy-root", include_inactive=True) == donor


def test_directory_resolves_adopted_source_before_paging_and_with_account_isolation(legacy):
    _, _, params, _ = legacy
    result = migrate(legacy)
    newer = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "newer",
        "method": "runtime.agent.conversation.create", "params": {
            "install_id": params["install_id"], "client_scope": OWNER,
            "persona_id": PERSONA, "persona_instance_id": params["persona_instance_id"],
            "idempotency_key": "newer-unrelated"}})
    assert "result" in newer, newer
    assert newer["result"]["session_id"] != result["session_id"]
    def query(**changes):
        return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "lookup",
            "method": "runtime.operator.conversation.list", "params": {
                "install_id": params["install_id"], "client_scope": OWNER,
                "legacy_route_id": params["session_id"], "limit": 1, **changes}})
    own = query()["result"]
    assert own["legacy_route_id"] == params["session_id"] and own["next_cursor"] is None
    row, = own["conversations"]
    assert row["session_id"] == result["session_id"]
    assert row["legacy_conversation"] == {"route_id": params["session_id"], "profile": "default"}
    assert query(client_scope=OTHER)["result"]["conversations"] == []
    assert query(legacy_route_id="absent")["result"]["conversations"] == []
    assert query(legacy_route_id=17)["error"]["data"]["reason"] == "invalid_history_query"


def test_import_is_atomic_retry_stable_owned_and_keeps_compression_history(legacy):
    service, scope, params, home = legacy
    before = selected(params["persona_instance_id"])
    with closing(SessionDB(db_path=home / "state.db", read_only=True)) as db:
        donor = db.export_session_lineage("legacy-root", include_inactive=True)
    first = migrate(legacy)
    replay = migrate(legacy)
    assert first["session_id"] == replay["session_id"] and replay["idempotent_replay"]
    assert first["legacy_session_id"] == params["session_id"] and first["workspace_id"] == WORKSPACE
    assert selected(params["persona_instance_id"]) == before
    with closing(default_persona_session_db()) as db:
        root = first["session_id"]
        exported = db.export_session_lineage(root, include_inactive=True)
        assert len(exported["segments"]) == 2
        assert [m["content"] for m in exported["messages"]] == [
            "Original request", "Archived answer", "Current answer"]
        assert exported["messages"][1]["active"] == 0 and exported["messages"][1]["compacted"] == 1
        for segment in exported["segments"]:
            assert session_client_scope(segment) == OWNER
            config = json.loads(segment["model_config"])
            assert config["persona_instance_id"] == params["persona_instance_id"]
            assert config["mission_chat_root_id"] == root
        assert db.resolve_resume_session_id(root) == exported["segments"][-1]["id"]
    with closing(SessionDB(db_path=home / "state.db", read_only=True)) as db:
        assert db.export_session_lineage("legacy-root", include_inactive=True) == donor
    route = service.store.get(params["session_id"], scope)
    assert service.store.migration_target(route) == (PERSONA, params["persona_instance_id"])


def test_import_continues_through_existing_operator_lane_without_selecting_default(legacy):
    _, _, params, _ = legacy
    result = migrate(legacy)
    target = {key: result[key] for key in (
        "install_id", "client_scope", "persona_id", "persona_instance_id", "workspace_id", "session_id")}
    before = selected(params["persona_instance_id"])
    read = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "read", "method": "runtime.operator.conversation.read",
                                     "params": target})
    assert read["result"]["session_id"] == result["session_id"]
    executions = []
    sent = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "send", "method": "runtime.operator.conversation.message",
                                    "params": {**target, "turn_request_id": "new-native-turn", "message": "Continue"}},
                                   serve_rpc.RpcContext(spawn_chat_turn=lambda *args: executions.append(args)))
    assert sent["result"]["accepted"] and len(executions) == 1
    assert selected(params["persona_instance_id"]) == before


def test_missing_owner_wrong_profile_and_foreign_route_cannot_fence_or_import(legacy):
    service, scope, params, _ = legacy
    with pytest.raises(ConversationError):
        service.migrate(replace(scope, client=OTHER), params["session_id"], params)
    with pytest.raises(ConversationError):
        service.migrate(replace(scope, profile="different"), params["session_id"], params)
    with pytest.raises(ConversationError):
        migrate(legacy, persona_id="other-agent")
    route = service.store.get(params["session_id"], scope)
    assert service.store.migration_target(route) is None
    assert migrate(legacy)["client_scope"] == OWNER


def test_uncertain_dead_execution_is_preserved_without_replay_but_live_owner_refuses(legacy):
    service, scope, params, _ = legacy
    route = service.store.get(params["session_id"], scope)
    seed_turn(service.store, route, "uncertain-turn", TurnState.RUNNING)
    service.store.recover()
    set_worker(service.store, route, os.getpid(), psutil.Process().create_time())
    with pytest.raises(ConversationError, match=Refusal.BUSY):
        migrate(legacy)
    assert service.store.migration_target(route) is None
    set_worker(service.store, route, 2147480000, 1.0)
    assert len(service.store.unsettled()) == 1
    result = migrate(legacy)
    assert result["turns"][-1]["state"] == "unknown"
    assert service.store.unsettled() == []
    assert service.store.turn_receipts(route)[-1]["state"] == TurnState.UNKNOWN
    with closing(default_persona_session_db()) as db:
        config = json.loads(db.get_session(result["session_id"])["model_config"])
        assert config["legacy_conversation"]["turns"][-1]["turn_id"] == "uncertain-turn"


def test_lost_commit_ack_recovers_same_root_and_does_not_resurrect_deleted_history(legacy, monkeypatch):
    original = PersonaChatMintTransaction.mark_bound
    def lost_ack(_):
        raise OSError("Lost acknowledgement after atomic import")
    monkeypatch.setattr(PersonaChatMintTransaction, "mark_bound", lost_ack)
    with pytest.raises(OSError):
        migrate(legacy)
    with closing(default_persona_session_db()) as db:
        count = db.session_count()
    monkeypatch.setattr(PersonaChatMintTransaction, "mark_bound", original)
    recovered = migrate(legacy)
    with closing(default_persona_session_db()) as db:
        assert db.session_count() == count
        db.delete_session(recovered["session_id"])
    with pytest.raises(ConversationError, match=Refusal.UNAVAILABLE):
        migrate(legacy)
    with closing(default_persona_session_db()) as db:
        assert db.get_session(recovered["session_id"]) is None


def test_parallel_migration_and_restart_use_one_root(legacy):
    service, scope, params, home = legacy
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: migrate(legacy), range(2)))
    assert replies[0]["session_id"] == replies[1]["session_id"]
    restarted = LegacyRoutes(service.root, service.install_id, profile_home=lambda _: home)
    result = restarted.migrate(scope, params["session_id"], params)
    assert result["session_id"] == replies[0]["session_id"]


def test_failed_import_keeps_durable_fence_and_requires_original_instance(legacy, monkeypatch):
    service, scope, params, _ = legacy
    original = migration._source_segments
    def unavailable(*_):
        raise OSError("Source temporarily unreadable")
    monkeypatch.setattr(migration, "_source_segments", unavailable)
    with pytest.raises(OSError):
        migrate(legacy)
    route = service.store.get(params["session_id"], scope)
    assert service.store.migration_target(route) == (PERSONA, params["persona_instance_id"])
    with pytest.raises(ConversationError, match=Refusal.CONFLICT):
        service.store.reserve_migration(route, PERSONA, "another-instance")
    monkeypatch.setattr(migration, "_source_segments", original)
    assert migrate(legacy)["persona_instance_id"] == params["persona_instance_id"]


@pytest.mark.parametrize("expires", ["2099-01-01T00:00:00Z", "2001-01-01T00:00:00Z"])
def test_session_permissions_keep_expiry_and_remaining_turns_without_overwriting_later_changes(legacy, expires):
    from agent_runtime.tool_permissions import ChatToolPermissionStore, permission_state_for_subject
    from agent_runtime.permission_modes import profile_permission_subject

    _, _, params, _ = legacy
    permissions = ChatToolPermissionStore()
    permissions.set(persona_id=profile_permission_subject("default"), session_id=params["session_id"],
                    mode="read_only", reason="Existing restriction", expires_at=expires, turns_remaining=1)
    before = permission_state_for_subject(profile_permission_subject("default"), session_id=params["session_id"])
    result = migrate(legacy)
    after = permission_state_for_subject(PERSONA, session_id=result["session_id"])
    assert {k: before[k] for k in ("mode", "expires_at", "turns_remaining")} == {
        k: after[k] for k in ("mode", "expires_at", "turns_remaining")}
    # A late acknowledgement retry cannot undo the user's later native setting.
    permissions.set(persona_id=PERSONA, session_id=result["session_id"], mode="bounded", reason="Changed later")
    migrate(legacy)
    assert permissions.get(persona_id=PERSONA, session_id=result["session_id"]).mode == "bounded"
