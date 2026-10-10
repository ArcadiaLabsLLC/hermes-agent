"""``realm sync history`` (H1): the realm subtree's versions, read from the local clone.

Contract consumer: `EterniaLauncher/lib/features/mission_control/sync/realm_sync_history.dart`
(``RealmRemoteHistory.fromEnvelopeJson``) — ``history`` rows ``{sha, at, author,
changed_paths[{family, container, item_key}], is_local_head, is_upstream_head}``.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from agent_runtime import paths as runtime_paths
from agent_runtime.realm_sync.history import realm_sync_history
from agent_runtime.store import RealmStore
from tests.agent_runtime._harness_cli import run_harness_in_process


#: Every commit lands in the same second, so the order under test is the graph's, never the clock's
#: (the bundled run reordered [third, second, first] when the commits shared a timestamp).
_ONE_INSTANT = "2026-10-06T00:00:00+00:00"


def _git(repo: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_DATE": _ONE_INSTANT, "GIT_COMMITTER_DATE": _ONE_INSTANT}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout


def _identity(repo: Path, name: str) -> None:
    _git(repo, "config", "user.email", f"{name}@localhost")
    _git(repo, "config", "user.name", name)


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def _realm_with_remote(tmp_path: Path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True, text=True)
    realm = RealmStore().create(name="History Realm")
    repo = tmp_path / "realm-sync-repo"
    subprocess.run(["git", "clone", str(bare), str(repo)], check=True, capture_output=True, text=True)
    _identity(repo, "alice")
    realm.sync_manifest_ref = str(repo)
    realm = RealmStore().save(realm)
    return realm, repo, bare, f"realms/{runtime_paths.safe_path_token(realm.id)}"


def test_history_lists_local_and_upstream_versions_with_their_items(isolate_agent_runtime_root, tmp_path):
    realm, repo, bare, sub = _realm_with_remote(tmp_path)
    first = _commit(repo, {f"{sub}/manifest.json": "{}", f"{sub}/store/boards/b1/board.json": "{}",
                           f"{sub}/store/boards/b1/cards/c1.json": "{}"}, "Publish 1")
    _commit(repo, {"realms/other-realm/store/personas.yaml": "x: 1\n"}, "another realm")
    second = _commit(repo, {f"{sub}/store/office/ws1/actors/a1.json": "{}", f"{sub}/store/personas.yaml": "p: 1\n",
                            f"{sub}/skills/deploy/SKILL.md": "# s\n"}, "Publish 2")
    _git(repo, "push", "-u", "origin", "HEAD")
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(bare), str(peer)], check=True, capture_output=True, text=True)
    _identity(peer, "bob")
    third = _commit(peer, {f"{sub}/store/levels/lvl1.json": "{}"}, "Publish 3 (peer)")
    _git(peer, "push")
    _git(repo, "fetch")

    data = realm_sync_history(realm.id)

    assert [row["sha"] for row in data["history"]] == [third, second, first]
    by_sha = {row["sha"]: row for row in data["history"]}
    assert by_sha[third]["author"] == "bob" and by_sha[third]["is_upstream_head"] and not by_sha[third]["is_local_head"]
    assert by_sha[second]["is_local_head"] and not by_sha[second]["is_upstream_head"]
    assert not by_sha[first]["is_local_head"] and not by_sha[first]["is_upstream_head"]
    items = lambda sha: sorted((i["family"], i["container"], i["item_key"]) for i in by_sha[sha]["changed_paths"])
    assert items(first) == [("board", "b1", "board"), ("board_card", "b1", "c1")]  # manifest.json is not an item
    assert items(second) == [("office_actor", "ws1", "a1"), ("persona_config", "", "personas"), ("skill", "", "deploy")]
    assert items(third) == [("level", "", "lvl1")]
    assert realm_sync_history(realm.id, limit=1)["history"][0]["sha"] == third


def test_the_verb_answers_json_and_an_unsynced_realm_has_an_empty_history(isolate_agent_runtime_root, tmp_path):
    realm = RealmStore().create(name="Never Synced")
    realm.sync_manifest_ref = str(tmp_path / "absent-repo")
    realm = RealmStore().save(realm)
    proc = run_harness_in_process("realm", "sync", "history", realm.id, "--limit", "5", "--json")
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout)
    body = body.get("data", body)
    assert body["history"] == [] and body["limit"] == 5
    assert not (tmp_path / "absent-repo").exists()  # a read never creates the clone
