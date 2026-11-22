"""``status`` and ``diff`` on a project folder (``agent_runtime.project_files.changes``) and their serve verbs.

Row ``MC-PHONE-FILES-GIT-STATUS-AND-DIFF-ON-A-PHONE-PROJECT-FOLDER``: a phone project with one edited and one
new file shows both in status and the edit as a diff. Every test runs once per git backend
(``sync_git_backend``; the dulwich arm puts a git stand-in on PATH that fails, so a process would red it).

Killing mutations (run 2026-11-21, w1118a-pfiles):
- ``changes.status`` naming every row ``changed`` (drop the ``untracked`` read) ->
  ``test_status_names_the_edit_and_the_new_file`` red on both arms;
- ``changes._confined`` skipping its ``resolve_within_root`` check ->
  ``test_diff_refuses_a_path_through_a_symlink_out_of_the_root`` red;
- ``runtime.files.diff`` dropped from ``LOCAL_CONSOLE_METHODS`` ->
  ``test_a_paired_device_never_names_this_devices_folder`` red (a console device admitted).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from agent_runtime import serve_rpc
from agent_runtime.project_files import changes
from agent_runtime.project_files.rules import ProjectFileRefusal

pytestmark = pytest.mark.usefixtures("sync_git_backend")


def _sh(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main",
                    *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path) -> Path:
    """A phone project: two committed files, then one edited and one new (made by the FIXTURE's git)."""

    root = tmp_path / "projects" / "notes"
    root.mkdir(parents=True)
    _sh(root, "init", "-q")
    (root / "readme.md").write_text("hello\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "plan.md").write_text("one\n", encoding="utf-8")
    _sh(root, "add", "-A")
    _sh(root, "commit", "-q", "-m", "seed")
    (root / "docs" / "plan.md").write_text("one\ntwo\n", encoding="utf-8")
    (root / "docs" / "idea.md").write_text("new\n", encoding="utf-8")
    return root


def test_status_names_the_edit_and_the_new_file(project):
    reply = changes.status(str(project))
    assert reply["entries"] == [{"path": "docs/idea.md", "state": "new"}, {"path": "docs/plan.md", "state": "changed"}]
    assert (reply["total"], reply["offset"], "next" in reply) == (2, 0, False)
    assert changes.status(str(project), offset=1)["entries"] == [{"path": "docs/plan.md", "state": "changed"}]


def test_diff_shows_the_edit_and_pages_it(project):
    reply = changes.diff(str(project), "docs/plan.md")
    assert reply == {"path": "docs/plan.md", "change": "modified", "body": "text", "chars": len(reply["content"]),
                     "offset": 0, "content": "--- a/docs/plan.md\n+++ b/docs/plan.md\n@@ -1 +1,2 @@\n one\n+two\n"}
    assert changes.diff(str(project), "docs/idea.md")["change"] == "added"
    assert changes.diff(str(project), "docs/plan.md", offset=4)["content"] == reply["content"][4:]


def test_status_and_diff_refuse_by_the_spec(project, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    for call, args in ((changes.status, (str(plain),)), (changes.diff, (str(plain), "a.txt"))):
        with pytest.raises(ProjectFileRefusal) as refused:
            call(*args)
        assert refused.value.code == "not_a_git_root"
    for path, code in (("../x", "invalid_path"), (".git/config", "ignored"), ("nowhere.md", "not_found"),
                       ("/etc/passwd", "invalid_path")):
        with pytest.raises(ProjectFileRefusal) as refused:
            changes.diff(str(project), path)
        assert refused.value.code == code, path
    with pytest.raises(ProjectFileRefusal) as refused:
        changes.status("relative/root")
    assert refused.value.code == "invalid_path"


def test_diff_refuses_a_path_through_a_symlink_out_of_the_root(project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep out\n", encoding="utf-8")
    os.symlink(outside, project / "door")
    with pytest.raises(ProjectFileRefusal) as refused:
        changes.diff(str(project), "door/secret.txt")
    assert refused.value.code == "outside_root"


# -- the serve verbs: the device's own Eternia names the folder; a paired caller never does ---------------


def _call(method: str, params: dict) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})


def test_the_serve_verbs_answer_the_local_owner(project):
    status = _call("runtime.files.status", {"root": str(project)})["result"]
    assert [entry["path"] for entry in status["entries"]] == ["docs/idea.md", "docs/plan.md"]
    diff = _call("runtime.files.diff", {"root": str(project), "path": "docs/plan.md"})["result"]
    assert diff["change"] == "modified" and "+two\n" in diff["content"]
    assert _call("runtime.files.diff", {"root": str(project), "path": 7})["error"]["data"]["reason"] == "invalid_path"
    assert _call("runtime.files.status", {"root": "relative"})["error"]["data"]["reason"] == "invalid_path"
    missing = _call("runtime.files.diff", {"root": str(project), "path": "gone.md"})
    assert missing["error"]["data"]["reason"] == "not_found"


def test_a_paired_device_never_names_this_devices_folder(project):
    from agent_runtime.call_authorization import (
        CALLER_DEVICE, LOCAL_CONSOLE, LOCAL_CONSOLE_METHODS, TIER_CONSOLE, TRANSPORT_GATEWAY, RpcCaller,
        authorize_call,
    )

    device = RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev_1", device_tier=TIER_CONSOLE)
    for name in ("runtime.files.status", "runtime.files.diff"):
        assert name in LOCAL_CONSOLE_METHODS
        assert serve_rpc.manifest()["tiers"][name] == TIER_CONSOLE
        assert authorize_call(TIER_CONSOLE, device, method=name).ok is False
        assert authorize_call(TIER_CONSOLE, LOCAL_CONSOLE, method=name).ok
