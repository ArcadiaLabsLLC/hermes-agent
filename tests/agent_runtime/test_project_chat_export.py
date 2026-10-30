"""Shared chats travel as per-chat per-writer turn logs (plan project-slots-and-shared-chats §5, row RT-PROJECT-CHAT-TURN-LOGS)."""

from __future__ import annotations

import json
import subprocess
from contextlib import closing

import pytest

from agent_runtime import project_chat_export as export
from agent_runtime.project_store import ProjectStore
from agent_runtime.workspace_slots import SlotRefused, bind_project

T0 = "2026-10-29T10:00:00+00:00"
SECRET = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz0123"


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin", "HOME": str(cwd)})


@pytest.fixture
def project(tmp_path):
    remote, checkout = tmp_path / "remote.git", tmp_path / "launcher"
    _git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    _git("clone", "-q", str(remote), str(checkout), cwd=tmp_path)
    (checkout / "README.md").write_text("x\n", encoding="utf-8")
    _git("add", "README.md", cwd=checkout)
    _git("commit", "-q", "-m", "init", cwd=checkout)
    _git("push", "-q", "origin", "HEAD:main", cwd=checkout)
    store = ProjectStore()
    store.declare("p1", [{"name": "launcher", "repo": {"clone_url": "https://example.com/launcher.git"}}],
                  issued_at=T0, machine="m")
    bind_project("p1", "launcher", str(checkout), issued_at=T0)
    store.set_category("p1", "chats", slot="launcher", subpath=None, shared=True, issued_at=T0)
    return {"remote": remote, "tmp": tmp_path}


@pytest.fixture
def chat(tmp_path):
    from hermes_state import SessionDB

    db = SessionDB(db_path=tmp_path / "state.db")
    db.create_session("chat_1", "harness")
    db.append_message("chat_1", "user", "hello there")
    yield db
    db.close()


def _published(remote, tmp_path, name):
    clone = tmp_path / name
    _git("clone", "-q", str(remote), str(clone), cwd=tmp_path)
    return clone / ".eternia" / "chats" / "chat_1"


def _lines(folder):
    files = sorted(folder.glob("*.jsonl"))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def test_a_shared_chat_exports_one_line_per_message_and_a_second_turn_appends_one(project, chat):
    first = export.share("p1", "chat_1", True, session_db=chat)
    assert first["exported"] == 1 and first["pushed"] is True
    chat.append_message("chat_1", "assistant", f"set {SECRET} in your shell")
    assert export.export_session("p1", "chat_1", chat)["exported"] == 1
    lines = _lines(_published(project["remote"], project["tmp"], "peer"))
    uids = [m["message_uid"] for m in chat.get_messages("chat_1")]
    assert [line["turn_uid"] for line in lines] == uids and [line["seq"] for line in lines] == [1, 2]
    assert lines[1]["parent_turn_uid"] == uids[0] and lines[0]["role"] == "user"
    assert "sk-abcdefghijklmnopqrstuvwxyz0123" not in lines[1]["content"]
    assert (_published(project["remote"], project["tmp"], "peer2") / "chat.json").is_file()
    # Nothing new: nothing exported, nothing committed.
    assert export.export_session("p1", "chat_1", chat)["exported"] == 0


def test_an_unshared_chat_exports_nothing(project, chat):
    assert export.export_session("p1", "chat_1", chat) == {"project_id": "p1", "session_id": "chat_1",
                                                           "exported": 0, "shared": False}
    assert export.export_after_turn(chat, "chat_1") is None


def test_unshare_removes_the_folder_in_one_commit(project, chat):
    export.share("p1", "chat_1", True, session_db=chat)
    done = export.share("p1", "chat_1", False, session_db=None)
    assert done["shared"] is False and done["commit"]
    assert not _published(project["remote"], project["tmp"], "after").exists()
    assert export.load_cursor("p1", "chat_1") is None
    log = subprocess.run(["git", "--git-dir", str(project["remote"]), "log", "-1", "--name-status", "--format=%s"],
                         capture_output=True, text=True, check=True).stdout
    assert "D\t.eternia/chats/chat_1/chat.json" in log


def test_a_chat_is_refused_when_the_projects_chats_are_not_shared(project, chat):
    ProjectStore().set_category("p1", "chats", slot="launcher", subpath=None, shared=False,
                                issued_at="2026-10-29T11:00:00+00:00")
    with pytest.raises(SlotRefused) as refused:
        export.share("p1", "chat_1", True, session_db=chat)
    assert refused.value.reason == "category_not_shared"
    assert export.load_cursor("p1", "chat_1") is None


def test_an_attachment_leaves_as_its_handle_never_its_path(tmp_path):
    """RT-PROJECT-CHAT-ATTACHMENT-HANDLES: a MEDIA: declaration line exports as ATTACHMENT:<handle>.

    Positive control: prose that only mentions the protocol (not an absolute image path) is unchanged.
    """
    from hermes_state import SessionDB

    from agent_runtime.media_handles import handle_for_bytes

    image = tmp_path / "shots" / "screen.png"
    image.parent.mkdir()
    image.write_bytes(b"\x89PNG fake bytes")
    db = SessionDB(db_path=tmp_path / "own.db")
    try:
        db.create_session("chat_a", "harness")
        db.append_message("chat_a", "user", f"look at this\nMEDIA:{image}\nMEDIA:{tmp_path / 'gone.png'}\n"
                                            "the MEDIA:<absolute path> line is how you attach")
        lines, _ = export.pending_lines(db, "chat_a", {})
    finally:
        db.close()
    line, = lines
    assert str(tmp_path) not in line["content"] and str(tmp_path) not in json.dumps(line)
    assert line["content"].splitlines() == ["look at this", f"ATTACHMENT:{handle_for_bytes(image.read_bytes())}",
                                            "ATTACHMENT:unavailable",
                                            "the MEDIA:<absolute path> line is how you attach"]
    assert line["attachments"] == [{"handle": handle_for_bytes(image.read_bytes()), "media_type": "image/png",
                                    "size_bytes": image.stat().st_size},
                                   {"handle": None, "status": "unavailable"}]


def test_project_show_answers_which_chats_this_machine_shares_into_it(project, chat):
    """RT-PROJECT-CHAT-SHARE-READ: the share state survives a relaunch because ``show`` reads the cursors."""

    from agent_runtime.project_store import show

    assert show("p1")["shared_chats"] == []
    export.share("p1", "chat_1", True, session_db=chat)
    assert show("p1")["shared_chats"] == ["chat_1"] and export.shared_projects_of("chat_1") == ["p1"]
    # A cursor that does not say ``shared`` is not a share (control: the same file with the flag is one).
    cursor = export.cursor_path("p1", "chat_1")
    record = json.loads(cursor.read_text(encoding="utf-8"))
    cursor.write_text(json.dumps({**record, "shared": False}), encoding="utf-8")
    assert show("p1")["shared_chats"] == [] and export.shared_projects_of("chat_1") == []
    cursor.write_text(json.dumps(record), encoding="utf-8")
    assert show("p1")["shared_chats"] == ["chat_1"]
    export.share("p1", "chat_1", False, session_db=None)
    assert show("p1")["shared_chats"] == []
