"""A chat's scratch folder inside the namespace (chat-folder plan §2.1–2.3).

``docs/agent-runtime-harness/planned/chat-folder-in-namespace-2026-10-26.md``.
"""
from pathlib import Path

import pytest

from agent_runtime import paths
from agent_runtime.conversations.model import ConversationError, ConversationScope, conversation_route_id
from agent_runtime.conversations.rpc import _open
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.conversation_support import WorkerFactory

pytestmark = pytest.mark.timeout(45)


@pytest.fixture
def runtime(tmp_path):
    for name in ("runtime", "work", "a"):
        (tmp_path / name).mkdir()
    service = ConversationService(tmp_path / "runtime", "install", profile_home=lambda p: tmp_path / p,
                                  worker_factory=WorkerFactory())
    yield service, tmp_path
    service.close()


def _route_cwd(service, scope, session_id) -> str:
    return service.store.get(session_id, scope).cwd


def test_chat_folder_is_instance_then_session_under_the_store_root(tmp_path):
    folder = paths.chat_folder("personainst_qa", "chat_1", root=tmp_path)
    assert folder == tmp_path / "chat_folders" / "personainst_qa" / "chat_1"
    assert not folder.exists(), "the helper names a path; it never creates one"
    assert paths.native_route_chat_folder_owner("alice") == "profile-alice"


def test_open_without_cwd_mints_the_route_folder_and_stores_it(runtime):
    service, root = runtime
    scope = ConversationScope("operator", "account-a", "a")
    reply = service.open(scope, key="thread", expected_home=str(root / "a"))
    sid = reply["session_id"]
    expected = (root / "runtime" / "chat_folders" / "profile-a" / sid).resolve()
    assert sid == conversation_route_id(scope, "thread")
    assert expected.is_dir()
    assert _route_cwd(service, scope, sid) == str(expected)
    assert service.capabilities()["minted_chat_folder"] is True
    # A resume that omits cwd presents the same minted folder.
    again = service.open(scope, key="thread", resume=sid, expected_home=str(root / "a"))
    assert again["session_id"] == sid


def test_a_given_cwd_keeps_todays_behaviour(runtime):
    service, root = runtime
    scope = ConversationScope("operator", "account-a", "a")
    sid = service.open(scope, key="thread", cwd=str(root / "work"), expected_home=str(root / "a"))["session_id"]
    assert _route_cwd(service, scope, sid) == str((root / "work").resolve())
    assert not (root / "runtime" / "chat_folders").exists()
    # Positive control: omitting cwd on the resume of a project-folder route is a different directory.
    with pytest.raises(ConversationError, match="conversation_owner_changed"):
        service.open(scope, key="thread", resume=sid, expected_home=str(root / "a"))


def test_a_resume_of_an_unknown_route_mints_nothing(runtime):
    service, root = runtime
    scope = ConversationScope("operator", "account-a", "a")
    with pytest.raises(ConversationError, match="conversation_unavailable"):
        service.open(scope, key="thread", resume="conversation-nope", expected_home=str(root / "a"))
    assert not (root / "runtime" / "chat_folders").exists()


def test_the_rpc_lane_accepts_an_omitted_cwd(runtime):
    service, root = runtime
    scope = ConversationScope("operator", "account-a", "a")
    reply = _open(service, scope, {"key": "thread", "profile_home": str(root / "a")})
    assert Path(_route_cwd(service, scope, reply["session_id"])).parent.name == "profile-a"


# ── §2.3: the Mission Control workdir ladder's rung 4 ────────────────────────


def test_the_chat_folder_rung_outranks_home_and_is_created_when_reached(tmp_path):
    from agent_runtime.mission_chat_workdir import WORKDIR_SOURCE_CHAT_FOLDER, resolve_mission_chat_workdir

    home, folder = tmp_path / "home", tmp_path / "chat_folders" / "inst" / "chat"
    home.mkdir()
    resolved = resolve_mission_chat_workdir(chat_folder_path=str(folder), home_fallback=str(home))
    assert (resolved.source, resolved.path) == (WORKDIR_SOURCE_CHAT_FOLDER, str(folder.resolve()))
    assert folder.is_dir()


def test_a_rung_above_wins_and_the_chat_folder_is_never_created(tmp_path):
    from agent_runtime.mission_chat_workdir import WORKDIR_SOURCE_PERSONA_REPO_SCOPE, resolve_mission_chat_workdir

    repo, folder = tmp_path / "repo", tmp_path / "chat_folders" / "inst" / "chat"
    repo.mkdir()
    resolved = resolve_mission_chat_workdir(repo_scope=str(repo), chat_folder_path=str(folder),
                                            home_fallback=str(tmp_path))
    assert resolved.source == WORKDIR_SOURCE_PERSONA_REPO_SCOPE
    assert not folder.exists()


def test_a_turn_with_no_grounding_runs_in_its_chat_folder(tmp_path, monkeypatch):
    from agent_runtime.mission_chat_turn_context import _default_mission_chat_workdir
    from agent_runtime.mission_chat_workdir import WORKDIR_SOURCE_CHAT_FOLDER
    from tests.agent_runtime.test_mission_chat_turn_context import _build, _resolvers

    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    context = _build(resolvers=_resolvers(mission_chat_workdir=_default_mission_chat_workdir))
    expected = paths.chat_folder("personainst_dev", "chat-root-1")
    assert context.workdir.source == WORKDIR_SOURCE_CHAT_FOLDER
    assert Path(context.workdir.path) == expected.resolve()


# ── §2.4: the one-shot move off the launcher's AppData folders ──────────────


def _launcher_route(store, workspaces, name, *, files=()):
    from agent_runtime.conversations.model import ConversationScope

    folder = workspaces / name
    folder.mkdir(parents=True)
    for file in files:
        (folder / file).write_text("scratch", encoding="utf-8")
    route, _ = store.reserve(ConversationScope("operator", "account-a", "a"), name, str(folder), "/home/a")
    return route


def test_chat_folder_migrate_plans_then_moves_each_route_once(tmp_path):
    from agent_runtime.conversations.chat_folder_migration import (
        FolderStep, RouteStep, apply_chat_folder_move, plan_chat_folder_moves)
    from agent_runtime.conversations.model import ConversationScope
    from agent_runtime.conversations.store import ConversationStore

    root = tmp_path / "runtime"
    root.mkdir()
    workspaces = tmp_path / "AppData" / "eternia_launcher" / "agents" / "workspaces"
    store = ConversationStore(root / "native_conversation_routes.db")
    empty = _launcher_route(store, workspaces, "aaa")
    full = _launcher_route(store, workspaces, "bbb", files=("notes.md",))
    bound = _launcher_route(store, workspaces, "ccc", files=("draft.md",))
    store.reserve_migration(bound, "qa", "personainst_qa")
    project = tmp_path / "project"
    project.mkdir()
    store.reserve(ConversationScope("operator", "account-a", "a"), "project", str(project), "/home/a")
    roots = {bound.id: ("personainst_qa", "chat_root_1")}

    def bound_root(_store, route):
        return roots.get(route.id)

    moves = {move.route_id: move for move in plan_chat_folder_moves(store, root=root, bound_root=bound_root)}
    assert set(moves) == {empty.id, full.id, bound.id}, "a project-folder route is never a candidate"
    assert (moves[empty.id].folder, moves[empty.id].route) == (FolderStep.REMOVE_EMPTY, RouteStep.REWRITE)
    assert (moves[full.id].folder, moves[full.id].route) == (FolderStep.MOVE, RouteStep.REWRITE)
    assert moves[bound.id].route is RouteStep.DELETE
    assert (workspaces / "aaa").is_dir(), "planning touches nothing"

    for move in moves.values():
        apply_chat_folder_move(store, move)
    native = root / "chat_folders" / "profile-a"
    assert not (workspaces / "aaa").exists() and (native / empty.id).is_dir()
    assert (native / full.id / "notes.md").read_text(encoding="utf-8") == "scratch"
    assert store.find_route(full.id, ConversationScope("operator", "account-a", "a")).cwd == str(
        (native / full.id).resolve())
    assert (root / "chat_folders" / "personainst_qa" / "chat_root_1" / "draft.md").is_file()
    assert store.find_route(bound.id, ConversationScope("operator", "account-a", "a")) is None
    assert plan_chat_folder_moves(store, root=root, bound_root=bound_root) == [], "a second run finds nothing"


def test_chat_folder_migrate_skips_a_route_with_unsettled_work(tmp_path):
    from agent_runtime.conversations.chat_folder_migration import RouteStep, plan_chat_folder_moves
    from agent_runtime.conversations.store import ConversationStore

    root = tmp_path / "runtime"
    root.mkdir()
    store = ConversationStore(root / "native_conversation_routes.db")
    route = _launcher_route(store, tmp_path / "eternia_launcher" / "agents" / "workspaces", "ddd")
    store.admit(route, "turn-1", {"text": "hi"})
    [move] = plan_chat_folder_moves(store, root=root, bound_root=lambda *_: None)
    assert move.route is RouteStep.SKIP_BUSY and move.new_cwd == move.old_cwd


def test_the_verb_is_a_dry_run_unless_applied(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from agent_runtime.conversations.store import ConversationStore
    from hermes_cli.harness_parts.conversation_commands import _cmd_conversation_chat_folder_migrate

    root = tmp_path / "runtime"
    root.mkdir()
    monkeypatch.setattr(paths, "store_root", lambda: root)
    store = ConversationStore(root / "native_conversation_routes.db")
    workspaces = tmp_path / "eternia_launcher" / "agents" / "workspaces"
    _launcher_route(store, workspaces, "eee")
    assert _cmd_conversation_chat_folder_migrate(SimpleNamespace(apply=False, json=True)) == 0
    import json as _json

    dry = _json.loads(capsys.readouterr().out)
    assert dry["applied"] is False and dry["counts"] == {"rewrite_cwd": 1}
    assert (workspaces / "eee").is_dir()
    assert _cmd_conversation_chat_folder_migrate(SimpleNamespace(apply=True, json=True)) == 0
    assert not (workspaces / "eee").exists()


def test_a_route_counts_as_bound_only_with_its_import_and_a_bound_receipt(tmp_path, monkeypatch):
    import json as _json

    from agent_runtime.chat_session_scope import SessionDbAccess, open_chat_session_db
    from agent_runtime.conversations.chat_folder_migration import _bound_persona_root
    from agent_runtime.conversations.store import ConversationStore

    head = tmp_path / "profiles" / "base"
    head.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))
    root = paths.store_root()
    root.mkdir(parents=True, exist_ok=True)
    store = ConversationStore(root / "native_conversation_routes.db")
    route = _launcher_route(store, tmp_path / "eternia_launcher" / "agents" / "workspaces", "fff")
    assert _bound_persona_root(store, route) is None, "no migration fence"
    store.reserve_migration(route, "qa", "personainst_qa")
    db = open_chat_session_db(access=SessionDbAccess.WRITE)
    db.create_session("personainst_qa_root", "agent_runtime_persona_chat", model_config={
        "legacy_conversation": {"route_id": route.id}})
    db.close()
    receipt = paths.persona_chat_mint_receipt_path("digest1")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    body = {"persona_instance_id": "personainst_qa", "session_id": "personainst_qa_root", "state": "reserved"}
    receipt.write_text(_json.dumps(body), encoding="utf-8")
    assert _bound_persona_root(store, route) is None, "a reserved receipt is not bound"
    receipt.write_text(_json.dumps({**body, "state": "bound"}), encoding="utf-8")
    assert _bound_persona_root(store, route) == ("personainst_qa", "personainst_qa_root")


@pytest.mark.parametrize("kind", ["per_profile", "process"])
def test_a_bound_root_is_read_from_its_per_profile_instances_head(tmp_path, monkeypatch, kind):
    """RT-CHAT-HEAD-FOLDER-MIGRATION-READ. Positive control: stamped ``process``, the root is not in base."""
    import json as _json

    from agent_runtime.chat_session_scope import ChatHeadSource, ChatSessionScope, SessionDbAccess, open_chat_session_db
    from agent_runtime.conversations.chat_folder_migration import _bound_persona_root
    from agent_runtime.conversations.store import ConversationStore
    from agent_runtime.persona_assignments import PersonaInstanceStore

    head, alice = tmp_path / "profiles" / "base", tmp_path / "profiles" / "alice"
    for path in (head, alice):
        path.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HEAD_HOME", str(head))
    root = paths.store_root()
    root.mkdir(parents=True, exist_ok=True)
    instances = PersonaInstanceStore()
    instance = instances.open_chat(persona_id="qa", session_id="personainst_qa_root", persona_instance_id="personainst_qa")
    instance.chat_head_home, instance.chat_head_kind = str(alice), kind
    instances.update(instance)
    store = ConversationStore(root / "native_conversation_routes.db")
    route = _launcher_route(store, tmp_path / "eternia_launcher" / "agents" / "workspaces", "ggg")
    store.reserve_migration(route, "qa", "personainst_qa")
    db = open_chat_session_db(ChatSessionScope(alice, ChatHeadSource.INSTANCE_RECORDED), access=SessionDbAccess.WRITE)
    db.create_session("personainst_qa_root", "agent_runtime_persona_chat", model_config={
        "legacy_conversation": {"route_id": route.id}})
    db.close()
    receipt = paths.persona_chat_mint_receipt_path("digest2")
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(_json.dumps({"persona_instance_id": "personainst_qa", "session_id": "personainst_qa_root",
                                    "state": "bound"}), encoding="utf-8")
    expected = ("personainst_qa", "personainst_qa_root") if kind == "per_profile" else None
    assert _bound_persona_root(store, route) == expected
