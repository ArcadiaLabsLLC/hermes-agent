"""``hermes harness realm sync remote set|clear`` — the VERB, through the real argparse tree.

RT-HARNESS-REALM-SET-BACKUP-REMOTE (seen 2026-11-12, w1112b-realmbak): a lane had to
hand-edit a realm's JSON to give a local realm a backup repository, and a ``file://``
URL there was read as a path. The verb adopts the remote through the same path a
``local:`` credential's ``git_url`` takes (``realm_sync.git._adopt_local_remote``).
Every remote here is a bare repository in ``tmp_path``; an ``https://`` URL is rewritten
to one by ``url.<dir>.insteadOf``, so no network is touched.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from agent_runtime import paths
from agent_runtime.realm_sync import publish_realm_sync
from agent_runtime.store import RealmStore, WorkspaceStore

HOST = "https://git.example.invalid/player/"


@pytest.fixture(autouse=True)
def hermetic_runtime_root(tmp_path, monkeypatch):
    root = tmp_path / "agent-runtime"
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(root))
    assert root.resolve() in paths.store_root().resolve().parents or paths.store_root().resolve() == root.resolve()
    return root


@pytest.fixture
def bare(tmp_path, monkeypatch) -> Path:
    host = tmp_path / "host"
    host.mkdir()
    repo = host / "backup.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(repo)], check=True, capture_output=True)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{host.as_posix()}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", HOST)
    return repo


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    from hermes_cli import harness

    root = argparse.ArgumentParser(prog="hermes")
    harness.build_parser(root.add_subparsers(dest="command"))
    args = root.parse_args(["harness", *argv, "--json"])
    code = args.func(args)
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else {}


def _origin(repo: Path) -> str:
    proc = subprocess.run(["git", "-C", str(repo), "config", "--get", "remote.origin.url"],
                          capture_output=True, text=True)
    return proc.stdout.strip()


def _own_repo(realm_id: str) -> Path:
    return paths.realm_sync_clone_dir(realm_id)


def test_set_adopts_a_file_url_and_a_publish_backs_up_into_it(bare, capsys):
    """*Killing mutation:* drop ``"file://"`` from ``git._looks_like_remote`` — the URL is
    refused as not a remote (and, hand-written into the realm, was read as a path)."""
    realm = RealmStore().create(name="Personal Realm")
    WorkspaceStore().create(name="Launcher", realm_id=realm.id, agent_ids=["dev"])
    url = bare.as_uri()

    code, answer = _run(["realm", "sync", "remote", "set", realm.id, url], capsys)

    assert code == 0, answer
    assert answer["kind"] == "realm_sync_remote" and answer["remote"] == url
    assert RealmStore().get(realm.id).sync_manifest_ref == url
    assert _origin(_own_repo(realm.id)) == url
    published = publish_realm_sync(realm.id)
    assert published["state"] == "published"
    on_backup = subprocess.run(["git", "-C", str(bare), "ls-tree", "-r", "--name-only", "main"],
                               capture_output=True, text=True, check=True).stdout.splitlines()
    assert any(p.startswith(f"realms/{paths.safe_path_token(realm.id)}/") for p in on_backup)


def test_set_takes_an_https_url_and_clear_undoes_it(bare, capsys):
    """*Killing mutation:* drop the ``remote remove origin`` in ``remote.clear_realm_backup_remote``
    — the realm's own clone keeps the origin after a clear."""
    realm = RealmStore().create(name="Personal Realm")
    url = HOST + "backup.git"

    code, answer = _run(["realm", "sync", "remote", "set", realm.id, url], capsys)
    assert code == 0, answer
    assert RealmStore().get(realm.id).sync_manifest_ref == url

    code, answer = _run(["realm", "sync", "remote", "clear", realm.id], capsys)

    assert code == 0, answer
    assert answer["remote"] is None
    assert RealmStore().get(realm.id).sync_manifest_ref is None
    assert _origin(_own_repo(realm.id)) == ""


def test_a_server_realm_is_refused_and_keeps_its_ref(bare, capsys):
    """*Killing mutation:* drop the ``server_id`` refusal in ``remote._server_less``."""
    realm = RealmStore().create(name="Team Realm", server_id="srv_1")

    code, answer = _run(["realm", "sync", "remote", "set", realm.id, bare.as_uri()], capsys)

    assert code != 0
    assert "realm_server_bound" in json.dumps(answer)
    assert RealmStore().get(realm.id).sync_manifest_ref is None


def test_a_path_is_not_a_remote(tmp_path, capsys):
    realm = RealmStore().create(name="Personal Realm")

    code, answer = _run(["realm", "sync", "remote", "set", realm.id, str(tmp_path / "somewhere")], capsys)

    assert code != 0
    assert "invalid_remote" in json.dumps(answer)
    assert RealmStore().get(realm.id).sync_manifest_ref is None
