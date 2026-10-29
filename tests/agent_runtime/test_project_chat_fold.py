"""The shared chat store per Project, folded by turn (plan project-slots-and-shared-chats §6, row RT-PROJECT-CHAT-SHARED-FOLD)."""

from __future__ import annotations

import json

from agent_runtime import paths
from agent_runtime.chat_session_scope import is_canonical_session_persistence
from agent_runtime.project_chat_fold import SHARED_SOURCE, drop_project_chats, fold, open_shared_store
from agent_runtime.project_store import ProjectStore
from agent_runtime.store import WorkspaceStore
from agent_runtime.workspace_projects import set_project_connection

T0 = "2026-10-29T10:00:00+00:00"


def _line(uid, ts, seq, role, content, machine):
    return {"turn_uid": uid, "seq": seq, "role": role, "ts": ts, "content": content, "parent_turn_uid": None,
            "author": {"persona_instance_id": f"personainst_{machine}", "machine_id": machine, "namespace": "base"}}


def _write(folder, session, writer, *lines):
    path = folder / session / f"{writer}.base.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.writelines(json.dumps(line) + "\n" for line in lines)


def _messages(project_id, session):
    db = open_shared_store(project_id, read_only=True)
    try:
        return [(m["message_uid"], m["content"]) for m in db.get_messages(session)]
    finally:
        db.close()


def test_two_writers_of_one_chat_fold_into_one_session_in_turn_order(tmp_path):
    folder = tmp_path / "chats"
    _write(folder, "chat_1", "mach_a", _line("u1", 100.0, 1, "user", "a1", "mach_a"),
           _line("u3", 300.0, 2, "assistant", "a2", "mach_a"))
    _write(folder, "chat_1", "mach_b", _line("u2", 200.0, 1, "user", "b1", "mach_b"))
    result = fold("p1", folder)
    assert result["inserted"] == 3 and result["sessions"] == ["chat_1"]
    assert _messages("p1", "chat_1") == [("u1", "a1"), ("u2", "b1"), ("u3", "a2")]
    db = open_shared_store("p1", read_only=True)
    assert db.get_session("chat_1")["source"] == SHARED_SOURCE
    db.close()
    # A turn appended later by one writer folds alone, after the others.
    _write(folder, "chat_1", "mach_b", _line("u4", 400.0, 2, "user", "b2", "mach_b"))
    assert fold("p1", folder)["inserted"] == 1
    assert [uid for uid, _ in _messages("p1", "chat_1")] == ["u1", "u2", "u3", "u4"]


def test_a_refold_inserts_nothing_even_when_the_offsets_are_lost(tmp_path):
    folder = tmp_path / "chats"
    _write(folder, "chat_1", "mach_a", _line("u1", 100.0, 1, "user", "a1", "mach_a"))
    fold("p1", folder)
    assert fold("p1", folder)["inserted"] == 0
    paths.project_chat_fold_path("p1").unlink()  # a re-pull that rewrote the files: every line read again
    again = fold("p1", folder)
    assert again["inserted"] == 0 and again["skipped"] == 1
    assert len(_messages("p1", "chat_1")) == 1


def test_the_shared_store_is_never_canonical_chat_persistence(tmp_path):
    from hermes_state import SessionDB

    fold("p1", tmp_path)  # creates the store
    shared = open_shared_store("p1", read_only=True)
    own = SessionDB(db_path=tmp_path / "state.db")
    try:
        assert is_canonical_session_persistence(shared) is False
        assert is_canonical_session_persistence(own) is True  # positive control: the real store is
    finally:
        shared.close()
        own.close()


def test_disconnecting_the_last_workspace_drops_the_store_and_nothing_else(tmp_path):
    from hermes_state import SessionDB

    own_path = tmp_path / "own" / "state.db"
    own_path.parent.mkdir()
    own = SessionDB(db_path=own_path)
    own.create_session("mine", "harness")
    own.append_message("mine", "user", "my own chat")
    own.close()
    before = own_path.read_bytes()
    one, two = WorkspaceStore().create(name="One").id, WorkspaceStore().create(name="Two").id
    set_project_connection(one, "p1", connected=True, expected_revision=0)
    set_project_connection(two, "p1", connected=True, expected_revision=0)
    folder = tmp_path / "chats"
    _write(folder, "chat_1", "mach_a", _line("u1", 100.0, 1, "user", "a1", "mach_a"))
    fold("p1", folder)
    fold("p2", folder)
    set_project_connection(one, "p1", connected=False, expected_revision=1)
    assert paths.project_chat_store_path("p1").is_file()  # another workspace still holds it
    set_project_connection(two, "p1", connected=False, expected_revision=1)
    assert not paths.project_chat_store_path("p1").exists()
    assert not paths.project_chat_fold_path("p1").exists()
    assert paths.project_chat_store_path("p2").is_file() and (folder / "chat_1").is_dir()
    assert own_path.read_bytes() == before


def test_unsharing_the_chats_drops_the_store(tmp_path):
    ProjectStore().declare("p1", [{"name": "launcher", "repo": {"clone_url": "https://example.com/l.git"}}],
                           issued_at="2026-10-29T10:00:00+00:00", machine="m")
    store = ProjectStore()
    store.set_category("p1", "chats", slot="launcher", subpath=None, shared=True, issued_at="2026-10-29T10:00:00+00:00")
    fold("p1", tmp_path)
    assert paths.project_chat_store_path("p1").is_file()
    store.set_category("p1", "chats", slot="launcher", subpath=None, shared=False, issued_at="2026-10-29T11:00:00+00:00")
    assert not paths.project_chat_store_path("p1").exists()
    assert drop_project_chats("p1", reason="again")["removed"] == []


def _git(*args, cwd):
    import subprocess

    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


def test_a_realm_pull_folds_a_peers_shared_turns_on_a_machine_that_sent_none(tmp_path):
    """RT-PROJECT-CHAT-FOLD-WITHOUT-SENDING: the pull's project_chat_fold applier fetches and folds.

    Positive control: before the applier runs, the reader machine's store holds nothing.
    """
    import types

    from agent_runtime.realm_sync.pull import PULL_APPLIERS, _pull_project_chats
    from agent_runtime.store import RealmStore
    from agent_runtime.workspace_slots import bind_project

    remote, peer, mine = tmp_path / "remote.git", tmp_path / "peer", tmp_path / "mine"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    _git("clone", "-q", str(remote), str(peer), cwd=tmp_path)
    _write(peer / ".eternia" / "chats", "chat_s", "peer-box", _line("u1", 100.0, 1, "user", "from the peer", "peer-box"))
    _git("add", ".", cwd=peer)
    _git("commit", "-q", "-m", "peer turn", cwd=peer)
    _git("push", "-q", "origin", "HEAD:main", cwd=peer)
    _git("clone", "-q", str(remote), str(mine), cwd=tmp_path)
    store = ProjectStore()
    store.declare("p1", [{"name": "launcher", "repo": {"clone_url": "https://example.com/l.git"}}], issued_at=T0,
                  machine="m")
    bind_project("p1", "launcher", str(mine), issued_at=T0)
    store.set_category("p1", "chats", slot="launcher", subpath=None, shared=True, issued_at=T0)
    realm = RealmStore().create(name="Realm")
    workspace = WorkspaceStore().create(name="Team", realm_id=realm.id)
    set_project_connection(workspace.id, "p1", connected=True, expected_revision=0)
    assert open_shared_store("p1", read_only=True) is None or _messages("p1", "chat_s") == []
    run = types.SimpleNamespace(realm=realm, project_chats=None)
    assert _pull_project_chats(run) is False  # a fold changes no realm artifact
    assert run.project_chats["folded"] == [{"project_id": "p1", "inserted": 1, "stale": False}]
    assert _messages("p1", "chat_s") == [("u1", "from the peer")]
    assert "project_chat_fold" in [applier.name for applier in PULL_APPLIERS]
