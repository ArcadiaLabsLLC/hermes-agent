"""The workspace slot document carries the categories, guidance and machines (row RT-WS-ABSORB-CONTENT-DOC).

Plan ``EterniaLauncher/docs/mission_control/planned/WORKSPACE_ABSORBS_PROJECTS_2026-11-04.md`` §3 / §6.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.call_authorization import LOCAL_CONSOLE_METHODS
from agent_runtime.workspace_chat_export import ChatHome, share
from agent_runtime.workspace_chat_fold import open_shared_store
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_slots import bind, declare, load_document
from agent_runtime.workspace_slots_sync import apply_workspace_slots_pull, merge_documents

OLD = "2026-11-04T10:00:00+00:00"
NEW = "2026-11-04T12:00:00+00:00"
CLONED = {"name": "launcher", "repo": {"clone_url": "https://example.com/launcher.git"}}
LOCAL = {"name": "notes", "repo": {"local": True}}
CONTENT_VERBS = ("runtime.workspace.category.set", "runtime.workspace.guidance.set",
                 "runtime.workspace.artifacts.list", "runtime.workspace.chat.share", "runtime.workspace.chat.fold")


def _rpc(verb, **params):
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": verb, "params": params})


def _workspace(slots=(CLONED, LOCAL), issued_at=OLD):
    workspace_id = WorkspaceStore().create(name="Team").id
    declare(workspace_id, list(slots), issued_at=issued_at, machine="mach_a")
    return workspace_id


def test_the_slot_document_round_trips_categories_and_guidance_through_the_verbs():
    ws = _workspace()
    done = _rpc("runtime.workspace.category.set", workspace_id=ws, category="documents", slot="launcher",
                subpath="docs/shared", shared=True, issued_at=OLD, context_files=["a.md", "a.md", "b.md"])
    assert done["result"]["record"] == {"slot": "launcher", "subpath": "docs/shared", "shared": True,
                                        "issued_at": OLD, "revision": 1, "context_files": ["a.md", "b.md"]}
    assert _rpc("runtime.workspace.category.set", workspace_id=ws, category="guidance", shared=True,
                issued_at=OLD)["result"]["record"]["subpath"] is None
    guidance = _rpc("runtime.workspace.guidance.set", workspace_id=ws, description="The team", instructions="Be kind.",
                    issued_at=OLD)["result"]["guidance"]
    assert guidance == {"description": "The team", "instructions": "Be kind.", "issued_at": OLD, "revision": 1}
    shown = _rpc("runtime.workspace.slots.show", workspace_id=ws)["result"]
    assert shown["document"]["categories"]["documents"]["shared"] is True
    assert shown["document"]["guidance"]["instructions"] == "Be kind." and shown["shared_chats"] == []
    assert json.loads(paths.workspace_slots_path(ws).read_text(encoding="utf-8"))["guidance"] == guidance
    # Turning the guidance share off takes the text out of the document: unshared guidance never syncs.
    _rpc("runtime.workspace.category.set", workspace_id=ws, category="guidance", shared=False, issued_at=NEW)
    assert "guidance" not in load_document(ws)


def test_the_content_verbs_refuse_with_typed_reasons():
    ws = _workspace()
    refused = _rpc("runtime.workspace.category.set", workspace_id=ws, category="chats", slot="notes", shared=True,
                   issued_at=OLD)["error"]
    assert refused["data"]["reason"] == "category_not_source_controlled" and refused["code"] == -32602
    assert "chats" not in load_document(ws).get("categories", {})
    cases = {
        "unknown_category": ("runtime.workspace.category.set", {"category": "bogus", "shared": False}),
        "slot_not_declared": ("runtime.workspace.category.set", {"category": "boards", "slot": "gone", "shared": False}),
        "guidance_not_shared": ("runtime.workspace.guidance.set", {"description": "d", "instructions": "i"}),
        "workspace_not_found": ("runtime.workspace.artifacts.list", {"workspace_id": "ws_missing"}),
    }
    for reason, (verb, params) in cases.items():
        reply = _rpc(verb, **{"workspace_id": ws, "issued_at": OLD, **params})
        assert reply["error"]["data"]["reason"] == reason, (reason, reply)
    _rpc("runtime.workspace.category.set", workspace_id=ws, category="guidance", shared=True, issued_at=OLD)
    too_long = _rpc("runtime.workspace.guidance.set", workspace_id=ws, description="", instructions="x" * 32001,
                    issued_at=OLD)["error"]["data"]["reason"]
    assert too_long == "guidance_too_long"
    # A retried older write is stale; positive control: the newer one lands.
    _rpc("runtime.workspace.category.set", workspace_id=ws, category="boards", slot="launcher", shared=False,
         issued_at=NEW)
    stale = _rpc("runtime.workspace.category.set", workspace_id=ws, category="boards", slot="launcher", shared=False,
                 issued_at=OLD)["error"]["data"]["reason"]
    assert stale == "stale_revision"


def test_making_a_shared_categorys_slot_local_unshares_it_at_the_declare():
    ws = _workspace()
    _rpc("runtime.workspace.category.set", workspace_id=ws, category="boards", slot="launcher", subpath="brain",
         shared=True, issued_at=OLD)
    result = declare(ws, [{"name": "launcher", "repo": {"local": True}}, LOCAL], issued_at=NEW, machine="mach_a")
    assert result["categories_unshared"] == ["boards"]
    assert load_document(ws)["categories"]["boards"]["shared"] is False


def _peer(ws, slots, categories=None, **extra):
    return {"schema_version": 1, "workspace_id": ws, "issued_at": NEW, "slots": slots, "machines": {},
            **({"categories": categories} if categories is not None else {}), **extra}


def _slot(url="https://example.com/launcher.git", issued_at=NEW, revision=0, local=False):
    repo = {"clone_url": None, "default_branch": "main", "local": True} if local else \
        {"clone_url": url, "default_branch": "main"}
    return {"repo": repo, "toolchain": {}, "context": {"files": ["CLAUDE.md"]},
            "recipe": {"revision": revision, "steps": []}, "issued_at": issued_at, "removed_at": None}


def test_a_peers_categories_and_guidance_merge_key_by_key_and_a_bad_entry_drops_alone(tmp_path):
    ws = _workspace()
    published = tmp_path / "store" / "workspace_slots"
    published.mkdir(parents=True)
    peer = _peer(ws, {"launcher": _slot(revision=5)},
                 {"documents": {"slot": "launcher", "subpath": "docs", "shared": True, "issued_at": NEW, "revision": 3},
                  "chats": {"slot": "launcher", "subpath": "../out", "shared": True, "issued_at": NEW, "revision": 1},
                  "bogus": {"slot": None}},
                 guidance={"description": "", "instructions": "x" * 32001, "issued_at": NEW, "revision": 1})
    (published / paths.workspace_slots_path(ws).name).write_text(json.dumps(peer), encoding="utf-8")
    summary = apply_workspace_slots_pull("realm", tmp_path)
    refused = sorted((row.get("category") or row.get("field"), row["reason"]) for row in summary.refused)
    assert refused == [("chats", "invalid_category"), ("guidance", "invalid_guidance"), ("unknown", "invalid_category")]
    document = load_document(ws)
    assert document["categories"] == {"documents": {"slot": "launcher", "subpath": "docs", "shared": True,
                                                    "issued_at": NEW, "revision": 3}}
    assert "guidance" not in document
    assert apply_workspace_slots_pull("realm", tmp_path).changed is False


def test_the_newer_revision_wins_a_category_and_the_share_rule_runs_after_the_merge():
    local = _peer("ws", {"launcher": _slot(local=True, revision=2)},
                  {"boards": {"slot": "launcher", "subpath": "a", "shared": False, "issued_at": NEW, "revision": 4}})
    remote = _peer("ws", {"launcher": _slot(issued_at=OLD)},
                   {"boards": {"slot": "launcher", "subpath": "b", "shared": False, "issued_at": NEW, "revision": 2},
                    "chats": {"slot": "launcher", "subpath": ".eternia/chats", "shared": True, "issued_at": NEW,
                              "revision": 1}},
                   guidance={"description": "", "instructions": "x", "issued_at": NEW, "revision": 1})
    merged = merge_documents(local, remote)
    assert merged["categories"]["boards"]["subpath"] == "a"  # revision 4 beats revision 2
    assert merged["categories"]["chats"]["shared"] is False  # the winning slot is local
    assert "guidance" not in merged  # its switch was never on
    # Positive control: with the guidance switch on, the peer's guidance merges in.
    remote["categories"]["guidance"] = {"slot": None, "subpath": None, "shared": True, "issued_at": NEW, "revision": 1}
    assert merge_documents(local, remote)["guidance"]["instructions"] == "x"


def test_artifacts_list_names_the_folders_files_on_this_machine(tmp_path):
    ws = _workspace()
    checkout = tmp_path / "launcher"
    (checkout / "out" / "nested").mkdir(parents=True)
    (checkout / "out" / "a.png").write_bytes(b"12345")
    (checkout / "out" / "nested" / "b.txt").write_bytes(b"x")
    (checkout / "out" / ".hidden").mkdir()
    (checkout / "out" / ".hidden" / "c").write_bytes(b"y")
    assert _rpc("runtime.workspace.artifacts.list", workspace_id=ws)["result"] == {
        "workspace_id": ws, "here": False, "files": [], "truncated": False}
    bind(ws, "launcher", str(checkout), issued_at=OLD)
    _rpc("runtime.workspace.category.set", workspace_id=ws, category="artifacts", slot="launcher", subpath="out",
         shared=False, issued_at=OLD)
    listed = _rpc("runtime.workspace.artifacts.list", workspace_id=ws)["result"]
    assert listed["here"] is True and listed["files"] == [{"name": "a.png", "size": 5}, {"name": "nested/b.txt", "size": 1}]


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


@pytest.fixture
def shared_workspace(tmp_path):
    remote, checkout = tmp_path / "remote.git", tmp_path / "launcher"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    _git("clone", "-q", str(remote), str(checkout), cwd=tmp_path)
    (checkout / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=checkout)
    _git("commit", "-q", "-m", "init", cwd=checkout)
    _git("push", "-q", "origin", "HEAD:main", cwd=checkout)
    ws = _workspace(slots=(CLONED,))
    bind(ws, "launcher", str(checkout), issued_at=OLD)
    _rpc("runtime.workspace.category.set", workspace_id=ws, category="chats", slot="launcher", shared=True,
         issued_at=OLD)
    return ws


@pytest.fixture
def chat(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("chat_1", "harness")
    db.append_message("chat_1", "user", "hello there")
    yield db
    db.close()


def test_a_chat_shared_into_the_workspace_folds_into_the_workspaces_own_store(shared_workspace, chat):
    ws = shared_workspace
    home = ChatHome.workspace(ws)
    first = share(home, "chat_1", True, session_db=chat)
    assert first["workspace_id"] == ws and first["exported"] == 1 and first["pushed"] is True
    assert _rpc("runtime.workspace.slots.show", workspace_id=ws)["result"]["shared_chats"] == ["chat_1"]
    folded = _rpc("runtime.workspace.chat.fold", workspace_id=ws)["result"]
    assert folded["workspace_id"] == ws and folded["inserted"] == 1 and folded["sessions"] == ["chat_1"]
    assert paths.workspace_chat_store_path(ws).is_file() and not (paths.store_root() / "project_chats").exists()
    db = open_shared_store(home, read_only=True)
    try:
        assert [m["content"] for m in db.get_messages("chat_1")] == ["hello there"]
    finally:
        db.close()
    stopped = _rpc("runtime.workspace.chat.share", workspace_id=ws, session_id="chat_1", shared=False)["result"]
    assert stopped["shared"] is False and stopped["commit"]
    assert _rpc("runtime.workspace.slots.show", workspace_id=ws)["result"]["shared_chats"] == []
    # Unsharing the category drops the workspace's store and nothing else.
    _rpc("runtime.workspace.category.set", workspace_id=ws, category="chats", slot="launcher", shared=False,
         issued_at=NEW)
    assert not paths.workspace_chat_store_path(ws).exists()


def test_a_workspace_whose_chats_are_not_shared_refuses_the_share_and_the_fold(chat):
    ws = _workspace()
    from agent_runtime.workspace_slots import SlotRefused

    with pytest.raises(SlotRefused) as refused:
        share(ChatHome.workspace(ws), "chat_1", True, session_db=chat)
    assert refused.value.reason == "category_not_shared"
    assert _rpc("runtime.workspace.chat.fold", workspace_id=ws)["error"]["data"]["reason"] == "category_not_shared"


def test_the_content_verbs_are_console_verbs_in_the_manifest_and_the_fold_stays_on_this_machine():
    manifest = serve_rpc.manifest()
    assert {manifest["tiers"][verb] for verb in CONTENT_VERBS} == {"console"}
    assert manifest["params"]["runtime.workspace.chat.share"] == ["workspace_id", "session_id", "shared", "credential"]
    assert "runtime.workspace.chat.fold" in LOCAL_CONSOLE_METHODS
