"""Group adoption keeps the public log while changing all execution owners together."""
from contextlib import closing
from types import SimpleNamespace

import pytest

from agent_runtime.conversations.model import ConversationScope, ConversationError
from agent_runtime.conversations.service import ConversationService
from agent_runtime.discussions import group_migration_store
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.service import DiscussionService
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.mission_chat_turns import transition_mission_chat_turn
from agent_runtime.models import AgentPersona
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore
from hermes_constants import get_hermes_home
from hermes_state import SessionDB
from tests.agent_runtime.conversation_support import WorkerFactory
from tests.agent_runtime.office_seed import seed_workspace_record
from tests.agent_runtime.test_discussion_profile_groups import complete, sends
from tests.agent_runtime.test_discussion_runtime import room_timings, wait_until

pytestmark = pytest.mark.timeout(90)

OWNER = "a" * 64
WORKSPACE = "ws_migrated_group"


@pytest.fixture
def adoption(isolate_agent_runtime_root, tmp_path, monkeypatch):
    root, home = isolate_agent_runtime_root, get_hermes_home()
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "default")
    seed_workspace_record(WORKSPACE)
    install = ensure_install_identity(root).install_id
    agents = {}
    for profile in ("a", "b"):
        folder = home / "profiles" / profile
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        persona = AgentStore().save(AgentPersona(id="migration_" + profile, display_name=profile,
            role="qa", model=None, provider=None, api_mode=None, system_prompt_path="", hermes_profile=profile))
        agents[profile] = PersonaInstanceStore().ensure_for_persona(persona)
    factory = WorkerFactory()
    conversations = ConversationService(root, install, profile_home=lambda p: home / "profiles" / p,
        worker_factory=factory)
    native_calls = []

    def model(args):
        with closing(SessionDB(db_path=home / "state.db")) as db:
            history = db.get_messages(args.session_id)
        assert any(m["content"] == "Original answer" for m in history)
        native_calls.append(args)
        for state in ("pending", "executing", "native_committed"):
            transition_mission_chat_turn(session_id=args.session_id, client_message_id=args.client_message_id,
                turn_id=args.client_message_id, state=state, metadata={"root_chat_session_id": args.session_id,
                    "native_committed": state == "native_committed", "stored_reply": "Native continuation",
                    "auxiliary_result": {"clarify": None}})
        args.payload_sink({"ok": True, "reply": "Native continuation"})
        return 0

    context = NativeContext(root, home, install, invoke=model)
    service = DiscussionService(context, **room_timings(), conversations=lambda: conversations)
    service.start()
    scope = execute(service, "capabilities", {"client_scope": OWNER}, actor_id="operator")["group_scope"]
    run = execute(service, "run.start_group", {"client_scope": OWNER, "workspace_id": scope,
        "idempotency_key": "legacy", "spec": {"name": "Saved group", "cwd": str(tmp_path), "participants": [
            {"install_id": install, "profile": p, "home": str(home / "profiles" / p), "name": p}
            for p in agents]}}, actor_id="operator")["run"]
    wait_until(lambda: service.runs.get(run["run_id"])["phase"] == "open")
    result = SimpleNamespace(service=service, conversations=conversations, factory=factory, run=run,
        agents=agents, home=home, install=install, native_calls=native_calls)
    yield result
    result.service.close()
    result.conversations.close()


def command(a, operation, key, **fields):
    return execute(a.service, "run." + operation, {"client_scope": OWNER, "workspace_id": a.run["workspace_id"],
        "run_id": a.run["run_id"], "expect_revision": a.service.runs.get(a.run["run_id"])["revision"],
        "idempotency_key": key, **fields}, actor_id="operator")


def prepare(a):
    command(a, "send", "old", message="Original request", response={"mode": "compare", "members": []})
    wait_until(lambda: len(sends(a.factory)) == 2 or any(t["status"] == "failed" for t in
        a.service.view(a.run["workspace_id"], a.run["run_id"])["tasks"]), timeout=15)
    assert len(sends(a.factory)) == 2, [t["error"] for t in a.service.view(a.run["workspace_id"], a.run["run_id"])["tasks"]]
    complete(a.factory, "Original answer")
    wait_until(lambda: len([e for e in a.service.view(a.run["workspace_id"], a.run["run_id"])["log"]["events"]
                           if e["kind"] == "message.member"]) == 2)
    command(a, "stop", "pause")
    wait_until(lambda: a.service.runs.get(a.run["run_id"])["phase"] == "paused")
    for member in a.service.runs.members(a.run["run_id"]):
        route = a.conversations.store.get(member["session_id"], ConversationScope("operator", OWNER, member["profile"]))
        with closing(SessionDB(db_path=a.home / "profiles" / member["profile"] / "state.db")) as db:
            assert db.import_sessions([{"id": route.native_id, "source": "eternia_intelligence", "started_at": 1,
                "messages": [{"role": "user", "content": "Original request", "timestamp": 1},
                             {"role": "assistant", "content": "Original answer", "timestamp": 2}]}])["ok"]


def params(a):
    return {"workspace_id": a.run["workspace_id"], "run_id": a.run["run_id"], "client_scope": OWNER,
        "expect_revision": a.service.runs.get(a.run["run_id"])["revision"], "target_workspace_id": WORKSPACE,
        "members": [{"member_id": m["member_id"], "participant": {"install_id": a.install,
                     "instance_id": a.agents[m["profile"]].id}} for m in a.service.runs.members(a.run["run_id"])]}


def move(a, request=None):
    return execute(a.service, "run.migrate_group", request or params(a), actor_id="operator")["run"]


def test_atomic_adoption_preserves_log_member_ids_defaults_and_continues_natively(adoption):
    a = adoption
    prepare(a)
    before = a.service.view(a.run["workspace_id"], a.run["run_id"])
    defaults = {p: PersonaInstanceStore().get(i.id).default_chat_session_id for p, i in a.agents.items()}
    request = params(a)
    migrated = move(a, request)
    assert migrated["run_id"] == a.run["run_id"] and migrated["workspace_id"] == WORKSPACE
    assert migrated["phase"] == "paused" and "group" not in migrated["initial"]
    after = a.service.view(a.run["workspace_id"], a.run["run_id"])
    assert after["log"] == before["log"] and after["tasks"] == before["tasks"]
    assert [m["member_id"] for m in after["members"]] == [m["member_id"] for m in before["members"]]
    assert all(m["instance_id"] == a.agents[m["profile"]].id and "binding" not in m for m in after["members"])
    assert move(a, request) == migrated
    assert not a.native_calls and len(sends(a.factory)) == 2
    assert {p: PersonaInstanceStore().get(i.id).default_chat_session_id for p, i in a.agents.items()} == defaults
    for member in before["members"]:
        with pytest.raises(ConversationError):
            a.conversations.send(ConversationScope("operator", OWNER, member["profile"]), member["session_id"],
                                 "retired-send", {"text": "Must refuse"})
    command(a, "send", "new", message="Continue here", response={"mode": "compare", "members": []})
    wait_until(lambda: len(a.native_calls) == 2)
    wait_until(lambda: len([e for e in a.service.view(WORKSPACE, a.run["run_id"])["log"]["events"]
                           if e["kind"] == "message.member"]) == 4)
    assert len(sends(a.factory)) == 2


def test_partial_import_fences_commands_and_reuses_roots_after_retry(adoption, monkeypatch):
    a = adoption
    prepare(a)
    request = params(a)
    original = group_migration_store.commit
    with monkeypatch.context() as patch:
        patch.setattr(group_migration_store, "commit", lambda *args: (_ for _ in ()).throw(OSError("lost before commit")))
        with pytest.raises(OSError):
            move(a, request)
    pending = a.service.runs.get(a.run["run_id"])
    assert pending["initial"]["group_migration"]["state"] == "pending"
    assert all(m["instance_id"] is None for m in a.service.runs.members(a.run["run_id"]))
    with pytest.raises(DiscussionError, match="migration in progress"):
        command(a, "send", "forbidden", message="Do not replay")
    with closing(SessionDB(db_path=a.home / "state.db")) as db:
        roots = {r[0] for r in db._conn.execute("SELECT id FROM sessions WHERE id LIKE 'persona_chat_%'")}
    assert len(roots) == 2
    assert group_migration_store.commit is original
    context = a.service.context
    a.service.close()
    a.service = DiscussionService(context, **room_timings(), conversations=lambda: a.conversations)
    a.service.start()
    migrated = move(a, request)
    assert migrated["phase"] == "paused"
    assert {m["session_id"] for m in a.service.runs.members(a.run["run_id"])} == roots
    assert not a.native_calls


def test_owner_mapping_and_pause_are_verified_before_any_adoption(adoption):
    a = adoption
    request = params(a)
    with pytest.raises(DiscussionError, match="pause before migration"):
        move(a, request)
    command(a, "stop", "pause")
    wait_until(lambda: a.service.runs.get(a.run["run_id"])["phase"] == "paused")
    request = params(a)
    with pytest.raises(DiscussionError, match="conversation owner changed"):
        move(a, {**request, "client_scope": "b" * 64})
    swapped = [dict(row) for row in request["members"]]
    swapped[0]["participant"], swapped[1]["participant"] = swapped[1]["participant"], swapped[0]["participant"]
    with pytest.raises(ConversationError):
        move(a, {**request, "members": swapped})
    assert "group_migration" not in a.service.runs.get(a.run["run_id"])["initial"]
    assert not a.factory.workers and not a.native_calls
    migrated = move(a, request)
    assert migrated["phase"] == "paused"
    assert len({m["session_id"] for m in a.service.runs.members(a.run["run_id"])}) == 2
