"""Group adoption keeps the public log while changing all execution owners together.

A profile group is retired with the profile-scoped conversation path
(RT-ONE-TURN-ENGINE-FOR-OPERATOR-CHAT-AND-INTELLIGENCE-CHAT), so a group here is SAVED data — its run,
members, room log, route receipts and member transcripts seeded as the retired path left them
(``legacy_conversation_seed``) — and adoption is what happens to it: explicit (``run.migrate_group``) or
at the discussion service's start (``adopt_legacy_groups``).
"""
from contextlib import closing
from types import SimpleNamespace

import pytest

from agent_runtime.conversations.legacy_routes import LegacyRoutes
from agent_runtime.conversations.model import ConversationError, ConversationScope, TurnState
from agent_runtime.discussions import group_migration_store
from agent_runtime.discussions.group_migration import NO_SINGLE_AGENT
from agent_runtime.discussions.native_context import NativeContext
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.run_values import DiscussionError, discussion_run_id
from agent_runtime.discussions.service import DiscussionService
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.mission_chat_turns import transition_mission_chat_turn
from agent_runtime.models import AgentPersona
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore
from gateway import hosted_rooms as rooms
from hermes_cli.sqlite_util import transaction
from hermes_constants import get_hermes_home
from hermes_state import SessionDB
from tests.agent_runtime.legacy_conversation_seed import seed_group, seed_route, seed_transcript
from tests.agent_runtime.office_seed import seed_workspace_record
from tests.agent_runtime.test_discussion_runtime import room_timings, wait_until
from tests.agent_runtime.persona_instance_mint import mint_hidden_copy

pytestmark = pytest.mark.timeout(90)

OWNER = "a" * 64
WORKSPACE = "ws_migrated_group"


def _persona(profile, persona_id=None):
    return AgentStore().save(AgentPersona(id=persona_id or "migration_" + profile, display_name=profile,
        role="qa", model=None, provider=None, api_mode=None, system_prompt_path="", hermes_profile=profile))


def _service(a):
    return DiscussionService(a.context, **room_timings(), legacy_routes=lambda: a.conversations)


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
        agents[profile] = mint_hidden_copy(store=PersonaInstanceStore(), persona=_persona(profile))
    conversations = LegacyRoutes(root, install, profile_home=lambda p: home / "profiles" / p)
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
    a = SimpleNamespace(context=context, conversations=conversations, agents=agents, home=home, install=install,
                        native_calls=native_calls, cwd=str(tmp_path), run=None, service=None)
    a.service = _service(a)
    a.service.start()
    a.scope = execute(a.service, "capabilities", {"client_scope": OWNER}, actor_id="operator")["group_scope"]
    yield a
    a.service.close()


def saved_group(a, *, phase="paused", history=True, key="legacy"):
    """A profile group as the retired path left it: run + members, its room, and with ``history`` one
    exchange — the user's message in the room, each member's answer in its route's transcript."""
    run_id = discussion_run_id(a.scope, key)
    seeded = seed_group(a.service.db_path, install=a.install, run_id=run_id, workspace_id=a.scope,
        actor="operator", client=OWNER, cwd=a.cwd, phase=phase,
        members=[(p, a.home / "profiles" / p, p) for p in ("a", "b")])
    rooms.create_room(a.service.db_path, room_id=run_id, name="Saved group",
        members=a.service.state.roster(a.service.runs.members(run_id)), authority_gateway_id=a.install)
    if history:
        a.service.state.append_user(a.service.runs.get(run_id), "old", "Original request", actor_id="operator")
        for member in seeded["members"]:
            scope = ConversationScope("operator", OWNER, member["profile"])
            native = "native-" + member["profile"]
            seed_route(a.conversations.store, scope, run_id, a.cwd, a.home / "profiles" / member["profile"],
                       native_id=native, turns=[("task-1", TurnState.COMPLETED)])
            seed_transcript(a.home / "profiles" / member["profile"], native,
                            [("user", "Original request"), ("assistant", "Original answer")])
    a.run = a.service.runs.get(run_id)
    return a.run


def command(a, operation, key, **fields):
    return execute(a.service, "run." + operation, {"client_scope": OWNER, "workspace_id": a.run["workspace_id"],
        "run_id": a.run["run_id"], "expect_revision": a.service.runs.get(a.run["run_id"])["revision"],
        "idempotency_key": key, **fields}, actor_id="operator")


def params(a):
    return {"workspace_id": a.run["workspace_id"], "run_id": a.run["run_id"], "client_scope": OWNER,
        "expect_revision": a.service.runs.get(a.run["run_id"])["revision"], "target_workspace_id": WORKSPACE,
        "members": [{"member_id": m["member_id"], "participant": {"install_id": a.install,
                     "instance_id": a.agents[m["profile"]].id}} for m in a.service.runs.members(a.run["run_id"])]}


def move(a, request=None):
    return execute(a.service, "run.migrate_group", request or params(a), actor_id="operator")["run"]


def restart(a):
    a.service.close()
    a.service = _service(a)
    a.service.start()


def test_atomic_adoption_preserves_log_member_ids_defaults_and_continues_natively(adoption):
    a = adoption
    saved_group(a)
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
    assert not a.native_calls
    assert {p: PersonaInstanceStore().get(i.id).default_chat_session_id for p, i in a.agents.items()} == defaults
    command(a, "send", "new", message="Continue here", response={"mode": "compare", "members": []})
    wait_until(lambda: len(a.native_calls) == 2)
    wait_until(lambda: len([e for e in a.service.view(WORKSPACE, a.run["run_id"])["log"]["events"]
                           if e["kind"] == "message.member"]) == 2)


def test_partial_import_fences_commands_and_reuses_roots_after_retry(adoption, monkeypatch):
    a = adoption
    saved_group(a)
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
        command(a, "stop", "forbidden")
    with closing(SessionDB(db_path=a.home / "state.db")) as db:
        roots = {r[0] for r in db._conn.execute("SELECT id FROM sessions WHERE id LIKE 'persona_chat_%'")}
    assert len(roots) == 2
    assert group_migration_store.commit is original
    restart(a)  # the start's own adoption finishes the pending one, on the intent it recorded
    migrated = a.service.runs.get(a.run["run_id"])
    assert migrated["phase"] == "paused" and "group" not in migrated["initial"]
    assert {m["session_id"] for m in a.service.runs.members(a.run["run_id"])} == roots
    assert not a.native_calls


def test_owner_mapping_and_pause_are_verified_before_any_adoption(adoption):
    a = adoption
    saved_group(a, phase="open", history=False)
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
    assert not a.native_calls
    migrated = move(a, request)
    assert migrated["phase"] == "paused"
    assert len({m["session_id"] for m in a.service.runs.members(a.run["run_id"])}) == 2


def test_a_saved_group_runs_nothing_and_refuses_a_send(adoption):
    """Mutation: drop the legacy-group check in ``DiscussionService.command`` -> red (the send is admitted)."""
    a = adoption
    saved_group(a, phase="paused")
    with pytest.raises(DiscussionError, match="profile group retired"):
        command(a, "send", "late", message="Run this on the old path")
    assert a.service.runs.get(a.run["run_id"])["phase"] == "paused"
    assert not a.service.runs.pending(a.run["run_id"]) and not a.native_calls


def test_every_saved_group_is_adopted_when_the_service_starts(adoption):
    """The owner's ruling, as data: a profile group left from before the retirement becomes an agent room at
    the next start, with no one asking — its room log, member ids and route receipts kept, each member's
    transcript in its agent's chat, its queued command failed rather than run.
    Mutation: drop the ``adopt_legacy_groups`` call from ``DiscussionService.start`` -> red (still a group)."""
    from agent_runtime.workspace_create import conversations_workspace

    a = adoption
    saved_group(a, phase="open")
    with transaction(a.service.runs.connect(), immediate=True) as conn:
        conn.execute("INSERT INTO mc_discussion_commands VALUES(?,?,?,?,?,'pending',?)",
                     (a.run["run_id"], "queued", "send", "d", "{}", 1.0))
    before = a.service.view(a.run["workspace_id"], a.run["run_id"])
    receipts = {m["member_id"]: a.conversations.store.turn_receipts(a.conversations.store.get(
        m["session_id"], ConversationScope("operator", OWNER, m["profile"])))
        for m in a.service.runs.members(a.run["run_id"])}
    members = a.service.runs.members(a.run["run_id"])
    restart(a)
    with a.context.scope():
        target = conversations_workspace().id
    adopted = a.service.runs.get(a.run["run_id"])
    assert "group" not in adopted["initial"] and adopted["initial"]["group_migration"]["state"] == "complete"
    assert adopted["workspace_id"] == target and adopted["phase"] == "paused"
    after = a.service.view(target, a.run["run_id"])
    assert after["log"] == before["log"]
    assert [m["member_id"] for m in after["members"]] == [m["member_id"] for m in before["members"]]
    assert {m["profile"]: m["instance_id"] for m in after["members"]} == {p: i.id for p, i in a.agents.items()}
    assert [c["state"] for c in a.service.runs.commands(a.run["run_id"])] == ["failed:profile_group_retired"]
    for member in after["members"]:
        with closing(SessionDB(db_path=a.home / "state.db")) as db:
            texts = [m["content"] for m in db.get_messages(member["session_id"])]
        assert texts == ["Original request", "Original answer"], member
    for member in members:
        route = a.conversations.store.get(member["session_id"], ConversationScope("operator", OWNER, member["profile"]))
        assert a.conversations.store.turn_receipts(route) == receipts[member["member_id"]]
        assert a.conversations.store.migration_target(route) is not None
    assert not a.native_calls


def test_a_saved_group_with_no_single_agent_waits_paused_and_whole(adoption):
    """Adoption never guesses between two agents on one profile: the group is paused, named, and kept whole
    for an explicit ``run.migrate_group``. Mutation: ``_single_agents`` takes the first agent of a profile
    with several -> red (the group is adopted onto a guessed agent)."""
    a = adoption
    saved_group(a, phase="open")
    mint_hidden_copy(store=PersonaInstanceStore(), persona=_persona("a", "migration_a_copy"))
    before = a.service.view(a.run["workspace_id"], a.run["run_id"])
    restart(a)
    waiting = a.service.runs.get(a.run["run_id"])
    assert "group" in waiting["initial"] and waiting["phase"] == "paused"
    assert waiting["error"] == NO_SINGLE_AGENT
    assert a.service.view(a.run["workspace_id"], a.run["run_id"])["log"] == before["log"]
    migrated = move(a)
    assert "group" not in migrated["initial"]


def test_a_retired_groups_unsettled_turn_reads_failed(adoption):
    """A turn the retired path left running can never settle: it reads failed ``profile_group_retired``,
    a view folding it in memory and a decision writing it. Mutation: ``RetiredGroupTurns.recover`` returns the
    row unchanged -> red (the turn stays running and the room can never pause or be adopted)."""
    a = adoption
    run = saved_group(a, phase="paused")
    member = a.service.runs.members(run["run_id"])[0]
    attempts = a.service.attempts
    row = attempts.begin(run["run_id"], "task-1", 1, member, "Original request")
    attempts.update(row, stage="running")
    row = attempts.get(run["run_id"], "task-1", 1)
    turns = a.service.executions.for_run(run).turns
    viewed = turns.recover(row, fresh=True, record=False)
    assert viewed["stage"] == "terminal" and viewed["receipt"]["error"] == "profile_group_retired"
    assert attempts.get(run["run_id"], "task-1", 1)["stage"] == "running"  # a view writes nothing
    recorded = turns.recover(row)
    assert recorded["stage"] == "terminal" and recorded["receipt"]["status"] == "failed"
    assert attempts.get(run["run_id"], "task-1", 1)["stage"] == "terminal"
    assert not turns.is_live(recorded) and turns.execution_absent(recorded)
