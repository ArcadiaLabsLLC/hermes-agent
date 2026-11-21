"""A realm that is behind says what pulling it would change, by kind (``incoming_artifact_counts``).

RT-FU-A-REALM-STATUS-SAYS-WHAT-A-PULL-WOULD-CHANGE (review w1118a.72). Seen live 2026-11-21: a realm one commit
behind by a commit that changed nothing under ``realms/`` was listed by Eternia's banner as "19 skills · 1 board · …",
because status filled ``artifact_counts`` with the WHOLE realm. Status now also answers the realm artifacts
``HEAD...@{u}`` changes, classified by ``families._kind_for_sync_path``, the paths the pull refuses left out, a skill
counted once per package; ``artifact_counts`` keeps its meaning for the sheet.

Killing mutations (run 2026-11-21):
- ``incoming_artifact_counts`` answered with the whole-realm ``artifact_kind_counts(artifacts)`` ->
  all three red (the fixture's in-sync ``{}`` read errors first).
- counting every skill file (drop the per-package ``continue``) ->
  ``test_a_three_file_skill_change_counts_one_skill`` red (``{skill: 3}``).
- dropping the ``is_secretish_path`` filter -> ``test_a_three_file_skill_change_counts_one_skill`` red
  (the ``.env`` counts as an ``artifact``).
- the git port's ``changed_between`` listing only adds and changes (the ``old`` side dropped) ->
  ``test_a_deleted_workspace_counts_as_incoming`` red.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime import paths as runtime_paths
from agent_runtime.realm_sync import publish_realm_sync, realm_sync_status
from agent_runtime.store import WorkspaceStore
from tests.agent_runtime.test_realm_sync import _git_in, _realm_with_remote

pytestmark = pytest.mark.usefixtures("persisted_persona_samples", "isolate_agent_runtime_root")


def _teammate(tmp_path: Path) -> Path:
    other = tmp_path / "other-member"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)],
                   check=True, capture_output=True, text=True)
    _git_in(other, "config", "user.email", "other-member@localhost")
    _git_in(other, "config", "user.name", "Other Member")
    return other


def _push(other: Path, message: str) -> None:
    _git_in(other, "add", "-A")
    _git_in(other, "commit", "-q", "-m", message)
    _git_in(other, "push", "-q")


@pytest.fixture
def published(tmp_path):
    realm, _repo = _realm_with_remote(tmp_path)
    WorkspaceStore().create(name="Launcher", realm_id=realm.id, agent_ids=["dev"])
    publish_realm_sync(realm.id)
    assert realm_sync_status(realm.id)["incoming_artifact_counts"] == {}
    other = _teammate(tmp_path)
    return realm, other, other / "realms" / runtime_paths.safe_path_token(realm.id)


def test_a_commit_outside_the_realm_answers_no_incoming_change(published):
    realm, other, _subtree = published
    (other / "NOTES.md").write_text("not a realm artifact\n", encoding="utf-8")
    _push(other, "outside the realm")

    status = realm_sync_status(realm.id)

    assert status["behind"] == 1
    assert status["incoming_artifact_counts"] == {}
    assert status["artifact_counts"]  # the whole realm, for the sheet, unchanged in meaning


def test_a_three_file_skill_change_counts_one_skill(published):
    realm, other, subtree = published
    skill = subtree / "skills" / "incoming-skill"
    skill.mkdir(parents=True)
    for name in ("SKILL.md", "notes.md", "helper.py"):
        (skill / name).write_text(f"{name}\n", encoding="utf-8")
    (subtree / ".env").write_text("TOKEN=refused-by-the-pull\n", encoding="utf-8")
    _push(other, "one skill, three files, and a path the pull refuses")

    assert realm_sync_status(realm.id)["incoming_artifact_counts"] == {"skill": 1}


def test_a_deleted_workspace_counts_as_incoming(published):
    realm, other, subtree = published
    workspaces = sorted((subtree / "store" / "workspaces").glob("*"))
    assert workspaces
    _git_in(other, "rm", "-q", str(workspaces[0].relative_to(other)))
    _git_in(other, "commit", "-q", "-m", "delete a workspace")
    _git_in(other, "push", "-q")

    assert realm_sync_status(realm.id)["incoming_artifact_counts"] == {"workspace": 1}
