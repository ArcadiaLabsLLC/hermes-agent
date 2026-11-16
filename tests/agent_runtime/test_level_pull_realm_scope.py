"""A realm's sync only brings in levels for that realm's own workspaces.

Row ``RT-REALM-PULL-ADMITS-ONLY-ITS-OWN-LEVELS``. Two homes in one process (the
publisher's PC and a teammate's), one realm, a local bare git origin. The
publisher's realm subtree also carries a level filed under a workspace of
ANOTHER realm (a hand edit or a misbehaving publisher: the publish scan itself
never ships one). The teammate's ``pull_realm_sync`` must refuse it typed
(``level_outside_realm``) and never write it, while the realm's own workspace's
level is adopted. Killed by dropping the ``admit`` from
``level_sync.apply_level_pull`` — the foreign level is adopted.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_runtime import paths
from agent_runtime.level_sync import LevelStore


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True, text=True)


def _clone(bare: Path, repo: Path) -> None:
    _git("clone", str(bare), str(repo))
    _git("-C", str(repo), "config", "user.email", "level-scope-test@localhost")
    _git("-C", str(repo), "config", "user.name", "Level Scope Test")


def _home(monkeypatch, tmp_path: Path, name: str) -> None:
    home = tmp_path / name
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(home / "agent-runtime"))


def _level(x: float) -> bytes:
    return json.dumps({"version": 6, "scene": {"props": [{"x": x}]}}, indent=2).encode("utf-8")


def test_a_realm_pull_refuses_a_level_for_another_realms_workspace(
    isolate_agent_runtime_root, persisted_persona_samples, monkeypatch, tmp_path
):
    from agent_runtime.realm_sync import publish_realm_sync, pull_realm_sync
    from agent_runtime.store import RealmStore, WorkspaceStore

    bare = tmp_path / "origin.git"
    _git("init", "--bare", str(bare))
    seed = tmp_path / "seed"
    _clone(bare, seed)
    _git("-C", str(seed), "commit", "--allow-empty", "-m", "init")
    _git("-C", str(seed), "push", "origin", "HEAD")

    # The publisher's PC: a realm with one workspace and its level.
    _home(monkeypatch, tmp_path, "a")
    repo_a = tmp_path / "repo-a"
    _clone(bare, repo_a)
    realm = RealmStore().create(name="Level Realm")
    realm.sync_manifest_ref = str(repo_a)
    realm = RealmStore().save(realm)
    ours = WorkspaceStore().create(name="Ours", realm_id=realm.id).id
    other_realm = RealmStore().create(name="Other Realm")
    foreign = WorkspaceStore().create(name="Theirs", realm_id=other_realm.id).id
    ours_token, foreign_token = paths.safe_path_token(ours), paths.safe_path_token(foreign)
    LevelStore().write(ours_token, _level(1.0))
    publish_realm_sync(realm.id)

    # A level for the other realm's workspace lands in this realm's subtree.
    levels = repo_a / "realms" / paths.safe_path_token(realm.id) / "store" / "levels"
    assert (levels / f"{ours_token}.json").is_file()
    (levels / f"{foreign_token}.json").write_bytes(_level(9.0))
    _git("-C", str(repo_a), "add", "-A")
    _git("-C", str(repo_a), "commit", "-m", "plant a foreign level")
    _git("-C", str(repo_a), "push", "origin", "HEAD")
    record = json.loads(paths.realm_path(realm.id).read_text(encoding="utf-8"))

    # The teammate's PC: its own clone, the realm record and nothing else.
    _home(monkeypatch, tmp_path, "b")
    repo_b = tmp_path / "repo-b"
    _clone(bare, repo_b)
    record["sync_manifest_ref"] = str(repo_b)
    paths.realm_path(realm.id).parent.mkdir(parents=True, exist_ok=True)
    paths.realm_path(realm.id).write_text(json.dumps(record), encoding="utf-8")

    level_sync = pull_realm_sync(realm.id)["level_sync"]

    assert level_sync["adopted"] == [ours_token]
    assert [(row["key"], row["code"]) for row in level_sync["refused"]] == [(foreign_token, "level_outside_realm")]
    assert LevelStore().read(ours_token) == _level(1.0)
    assert LevelStore().read(foreign_token) is None
    assert level_sync["upstream_absent"] == []
