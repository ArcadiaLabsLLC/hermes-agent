"""The default clone folder a slot not set up here offers (row RT-SLOT-DEFAULT-CLONE-FOLDER, Eternia
``MC-SLOT-JOIN-ONE-PROMPT-SETUP``, owner ruling 2026-11-13): ``<namespace>/repos/<realm folder>/<slot>``.

Read through the verb Eternia calls, ``runtime.workspace.slots.show`` (``here.<slot>.default_clone_path``), and
the clone door it feeds, ``runtime.workspace.slot.clone``. Killing mutations are named per test.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import RealmStore, WorkspaceStore
from agent_runtime.workspace_slot_clone_home import repos_root

APP_URL = "https://github.com/ArcadiaLabsLLC/EterniaLauncher.git"
APP_SSH = "git@github.com:ArcadiaLabsLLC/EterniaLauncher.git"
OTHER_URL = "https://github.com/ArcadiaLabsLLC/eternia-backend.git"
ISSUED = "2026-11-13T12:00:00+00:00"


def call(method: str, params: dict) -> dict:
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "t", "method": method, "params": params})
    assert "result" in reply, reply
    return reply["result"]


def _realm(name: str, realm_id: str) -> str:
    return RealmStore().create(name=name, realm_id=realm_id).id


def _workspace(realm_id: str | None, slots: list[dict], name: str = "Slots") -> str:
    machine_roots_cache_clear()
    workspace_id = WorkspaceStore().create(name=name, realm_id=realm_id).id
    call("runtime.workspace.slots.declare", {"workspace_id": workspace_id, "slots": slots, "issued_at": ISSUED})
    return workspace_id


def _slot(name: str, url: str | None = APP_URL) -> dict:
    return {"name": name, "repo": {"clone_url": url, "default_branch": "main"}}


def _default(workspace_id: str, slot: str) -> str | None:
    return call("runtime.workspace.slots.show", {"workspace_id": workspace_id})["here"][slot]["default_clone_path"]


def _checkout(path: Path, url: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", url], check=True)
    return path


def _bind(workspace_id: str, slot: str, path: Path) -> None:
    call("runtime.workspace.slot.bind", {"workspace_id": workspace_id, "slot": slot, "path": str(path),
                                         "issued_at": ISSUED})


def test_the_realm_folder_comes_from_its_name_and_stays_when_the_realm_is_renamed():
    """Mutation: ``realm_folder`` returning the safe name without reading the mapping → the rename moves it."""

    realm_id = _realm("Team: Alpha", "realm_alpha")
    workspace_id = _workspace(realm_id, [_slot("launcher")])
    expected = paths.store_root().parent / "repos" / "Team-Alpha" / "launcher"
    assert _default(workspace_id, "launcher") == str(expected) and expected.is_absolute()
    realm = RealmStore().get(realm_id)
    realm.name = "Renamed Realm"
    RealmStore().save(realm)
    assert _default(workspace_id, "launcher") == str(expected)


def test_two_realms_of_one_folder_name_suffix_the_second():
    first = _workspace(_realm("Team", "realm_one"), [_slot("launcher")], name="One")
    second = _workspace(_realm("team!", "realm_two"), [_slot("launcher")], name="Two")
    assert _default(first, "launcher") == str(repos_root() / "Team" / "launcher")
    assert _default(second, "launcher") == str(repos_root() / "team-2" / "launcher")


def test_a_slot_folder_held_by_another_repository_is_suffixed():
    """Bound to a different repo in the realm → ``-2``; on disk and not this repo → ``-3``."""

    realm_id = _realm("Team", "realm_team")
    elsewhere = _workspace(realm_id, [_slot("launcher", OTHER_URL)], name="Backend")
    _bind(elsewhere, "launcher", _checkout(repos_root() / "Team" / "launcher", OTHER_URL))
    stray = repos_root() / "Team" / "launcher-2"
    stray.mkdir(parents=True)
    (stray / "notes.txt").write_text("not a checkout", encoding="utf-8")
    workspace_id = _workspace(realm_id, [_slot("launcher")])
    assert _default(workspace_id, "launcher") == str(repos_root() / "Team" / "launcher-3")


def test_one_repository_is_cloned_once_per_realm():
    """A slot of another workspace of the realm bound to the same repo under ``repos/<realm>/`` is the default
    (the ssh and https spellings are one repo); another realm's clone is not. Mutation: ``shared_clone``
    answering None → ``repos/Team/frontend``."""

    realm_id = _realm("Team", "realm_team")
    owner = _workspace(realm_id, [_slot("app")], name="Owner")
    shared = _checkout(repos_root() / "Team" / "app", APP_URL)
    _bind(owner, "app", shared)
    joiner = _workspace(realm_id, [_slot("frontend", APP_SSH)], name="Joiner")
    assert _default(joiner, "frontend") == str(shared)
    stranger = _workspace(_realm("Others", "realm_others"), [_slot("frontend")], name="Stranger")
    assert _default(stranger, "frontend") == str(repos_root() / "Others" / "frontend")


def test_null_when_bound_here_or_local_only(tmp_path):
    workspace_id = _workspace(_realm("Team", "realm_team"),
                              [_slot("launcher"), {"name": "notes", "repo": {"clone_url": None, "local": True}}])
    assert _default(workspace_id, "notes") is None
    _bind(workspace_id, "launcher", _checkout(tmp_path / "mine" / "launcher", APP_URL))
    assert _default(workspace_id, "launcher") is None


class _Registry:
    def __init__(self):
        self.spawned = []

    def spawn_local(self, command, **kwargs):
        self.spawned.append((command, kwargs))
        return types.SimpleNamespace(id="proc_0001", exited=False, exit_code=None, output_buffer="",
                                     completion_reason="exited")

    def get(self, sid):
        return None


def test_clone_into_the_default_creates_its_parent_folders():
    """Mutation: drop ``dest.parent.mkdir`` in ``clone_slot`` → the realm folder does not exist."""

    from agent_runtime.workspace_slot_setup import clone_slot

    workspace_id = _workspace(_realm("Fresh Realm", "realm_fresh"), [_slot("launcher")])
    dest = Path(_default(workspace_id, "launcher"))
    assert not dest.parent.exists()
    registry = _Registry()
    clone_slot(workspace_id, "launcher", str(dest), issued_at=ISSUED, registry=registry, watch=False)
    [(_, kwargs)] = registry.spawned
    assert dest.parent.is_dir() and not dest.exists() and kwargs["cwd"] == str(dest.parent)
