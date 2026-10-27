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
