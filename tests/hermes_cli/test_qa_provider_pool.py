"""The QA provider pool (``hermes_cli/_namespace_bootstrap.py::qa_provider_pool_home``) — row
RT-QA-SHARED-PROVIDER-POOL, owner ruling 2026-11-06: every QA lane runs its own namespace, and every
QA namespace in one QA folder shares ONE provider credential pool.

Every test builds its own install and QA folder under ``tmp_path`` with fake tokens; nothing here
reads or writes the operator's live Hermes root or a real QA sandbox.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hermes_cli import _namespace_bootstrap as ns

REPO = Path(__file__).resolve().parents[2]
POOL = "stagec-smoke"
LANE = "stagec-smoke-lane-0123456789"


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "install" / ".hermes"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """A QA folder holding the pool namespace (a manifest, as hermes writes on first resolve)."""
    path = tmp_path / "qa-sandbox" / "hermes-namespaces"
    (path / POOL / "profiles" / "base").mkdir(parents=True)
    (path / POOL / "namespace.json").write_text(json.dumps({"schema": 1, "id": POOL}), encoding="utf-8")
    return path


def _env(base: Path, folder: Path, namespace: str = LANE, **extra: str) -> dict[str, str]:
    return {"HERMES_HOME": str(base), "HERMES_NAMESPACES_DIR": str(folder), "HERMES_NAMESPACE": namespace,
            "HERMES_LAUNCHER_SPAWNED": "1", "HERMES_QA_PROVIDER_POOL": POOL, **extra}


def _updates(env: dict[str, str]) -> dict[str, str]:
    return ns.env_updates(ns.resolve_cli(["hermes", "harness", "serve"], env), env)


def test_a_qa_lane_binds_the_pools_head_home(base: Path, folder: Path):
    updates = _updates(_env(base, folder))
    assert updates["HERMES_AUTH_HOME"] == str(folder / POOL / "profiles" / "base")
    # The lane's own data stays its own: only the provider store is shared.
    assert updates["HERMES_HOME"] == str(folder / LANE / "profiles" / "base")


def test_the_pool_replaces_an_inherited_shared_auth_home(base: Path, folder: Path, tmp_path: Path):
    inherited = tmp_path / "owner" / ".hermes" / "profiles" / "base"
    updates = _updates(_env(base, folder, HERMES_AUTH_HOME=str(inherited)))
    assert updates["HERMES_AUTH_HOME"] == str(folder / POOL / "profiles" / "base")


def test_the_pool_namespace_itself_and_an_unset_pool_bind_nothing(base: Path, folder: Path):
    assert "HERMES_AUTH_HOME" not in _updates(_env(base, folder, namespace=POOL))
    env = _env(base, folder)
    del env["HERMES_QA_PROVIDER_POOL"]
    assert "HERMES_AUTH_HOME" not in _updates(env)


@pytest.mark.parametrize("has_credentials", [False, True])
def test_first_lane_initializes_the_pool_without_reseeding_credentials(base: Path, tmp_path: Path,
                                                                     has_credentials: bool):
    folder = tmp_path / "fresh-qa" / "hermes-namespaces"
    auth = folder / POOL / "profiles" / "base" / "auth.json"
    original_auth = b'{"version": 1, "providers": {"example": {"token": "fake"}}}'
    if has_credentials:
        auth.parent.mkdir(parents=True)
        auth.write_bytes(original_auth)
    env = _env(base, folder)

    ns.apply_cli_namespace(["hermes", "harness", "serve"], env)

    assert env["HERMES_AUTH_HOME"] == str(auth.parent)
    manifest = folder / POOL / "namespace.json"
    original_manifest = manifest.read_bytes()
    record = json.loads(original_manifest)
    assert record["id"] == POOL
    assert record["origin"] == ns.ORIGIN_LAUNCHER_PROFILE
    assert record["epoch"]
    assert auth.exists() is has_credentials
    if has_credentials:
        assert auth.read_bytes() == original_auth
    # Another lane uses the same pool; it neither replaces its manifest nor seeds auth.
    second = _updates(_env(base, folder, namespace="stagec-smoke-lane-abcdefabcd"))
    assert second["HERMES_AUTH_HOME"] == str(auth.parent)
    assert manifest.read_bytes() == original_manifest
    if has_credentials:
        assert auth.read_bytes() == original_auth


@pytest.mark.parametrize("namespace, pool", [("qa", POOL), (LANE, "qa-pool")])
def test_a_non_qa_namespace_may_not_join_the_pool(base: Path, folder: Path, namespace: str, pool: str):
    (folder / pool).mkdir(exist_ok=True)
    (folder / pool / "namespace.json").write_text("{}", encoding="utf-8")
    env = _env(base, folder, namespace=namespace, HERMES_QA_PROVIDER_POOL=pool)
    with pytest.raises(ns.NamespaceRefused) as caught:
        _updates(env)
    assert caught.value.reason is ns.Reason.QA_POOL_REFUSED


def test_a_folder_holding_an_account_namespace_is_the_owners_no_pool(base: Path, folder: Path):
    (folder / "acct-0123456789abcdef").mkdir()
    manifest = folder / POOL / "namespace.json"
    manifest.unlink()
    with pytest.raises(ns.NamespaceRefused) as caught:
        _updates(_env(base, folder))
    assert caught.value.reason is ns.Reason.QA_POOL_REFUSED
    assert "owner" in caught.value.detail
    assert not manifest.exists()


def test_the_pool_is_a_launcher_hand_off(base: Path, folder: Path):
    item = ns.layout(LANE, _env(base, folder))
    env = _env(base, folder)
    del env["HERMES_LAUNCHER_SPAWNED"]
    manifest = folder / POOL / "namespace.json"
    manifest.unlink()
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.qa_provider_pool_home(item, env)
    assert caught.value.reason is ns.Reason.QA_POOL_REFUSED
    assert not manifest.exists()


def test_a_pool_id_is_an_id_never_a_path(base: Path, folder: Path):
    with pytest.raises(ns.NamespaceRefused) as caught:
        _updates(_env(base, folder, HERMES_QA_PROVIDER_POOL=str(base)))
    assert caught.value.reason is ns.Reason.INVALID_ID


def test_a_refused_pool_stops_the_process_with_exit_2(base: Path, folder: Path):
    (folder / "acct-0123456789abcdef").mkdir()
    env = _env(base, folder)
    with pytest.raises(SystemExit) as caught:
        ns.apply_cli_namespace(["hermes", "harness", "serve"], env)
    assert caught.value.code == 2
    assert "HERMES_AUTH_HOME" not in env


# -- end to end: the lane reads the pool's sign-in, and a refresh is single-writer across lanes ---------


@pytest.mark.parametrize("manifest_present", [False, True])
def test_a_lane_reads_the_sign_in_the_pool_holds(base: Path, folder: Path, monkeypatch,
                                              manifest_present: bool):
    pool_home = folder / POOL / "profiles" / "base"
    (pool_home / "auth.json").write_text(json.dumps({"version": 1, "credential_pool": {"openai-codex": [{
        "id": "qa-codex", "label": "qa", "auth_type": "oauth", "priority": 0, "source": "device_code",
        "access_token": "fake-access", "refresh_token": "fake-refresh",
        "base_url": "https://chatgpt.com/backend-api/codex"}]}}), encoding="utf-8")
    if not manifest_present:
        (folder / POOL / "namespace.json").unlink()
    env = _env(base, folder)
    ns.apply_cli_namespace(["hermes", "harness", "serve"], env)
    for key in ("HERMES_HOME", "HERMES_AUTH_HOME"):
        monkeypatch.setenv(key, env[key])
    from agent.credential_pool import load_pool
    from hermes_cli.auth import _auth_file_path

    assert _auth_file_path() == pool_home / "auth.json"
    entry = load_pool("openai-codex").select()
    assert entry is not None and entry.id == "qa-codex"
    assert not (folder / LANE / "profiles" / "base" / "auth.json").exists()


_HOLD_LOCK = """
import sys
from hermes_cli import _namespace_bootstrap as ns
ns.long_paths_enabled = lambda: True
ns.apply_cli_namespace(["hermes", "version"])
from hermes_cli.auth import _auth_store_lock
try:
    with _auth_store_lock(timeout_seconds=1.0):
        print("acquired")
except TimeoutError:
    print("waited")
"""


def test_two_lanes_take_one_auth_lock(base: Path, folder: Path, monkeypatch):
    """Lane A holds the pool's lock; a process of lane B, in its own namespace, must wait for it.

    The child only resolves its namespace and takes the auth lock (no backend); its root is tmp_path."""
    env_a = _env(base, folder)
    ns.apply_cli_namespace(["hermes", "harness", "serve"], env_a)
    for key in ("HERMES_HOME", "HERMES_AUTH_HOME"):
        monkeypatch.setenv(key, env_a[key])
    from hermes_cli.auth import _auth_store_lock

    child = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
    child.update(_env(base, folder, namespace="stagec-smoke-lane-abcdefabcd"), PYTHONPATH=str(REPO))
    with _auth_store_lock():
        held = subprocess.run([sys.executable, "-c", _HOLD_LOCK], env=child, cwd=str(REPO),
                              capture_output=True, text=True, timeout=120, check=False)
    assert held.stdout.strip().splitlines()[-1:] == ["waited"], held.stderr[-2000:]
    free = subprocess.run([sys.executable, "-c", _HOLD_LOCK], env=child, cwd=str(REPO),
                          capture_output=True, text=True, timeout=120, check=False)
    assert free.stdout.strip().splitlines()[-1:] == ["acquired"], free.stderr[-2000:]


# -- a lane moved out of the pool's folder names that folder (RT-QA-POOL-FOLLOWS-MOVED-NAMESPACE) -------


@pytest.fixture
def moved(tmp_path: Path) -> Path:
    """The folder a QA lane namespace was moved to (Eternia's agent-data-folder Move): no pool in it."""
    path = tmp_path / "moved-elsewhere" / "hermes-namespaces"
    (path / LANE / "profiles" / "base").mkdir(parents=True)
    return path


def test_a_moved_lane_binds_the_pool_in_the_folder_it_names(base: Path, folder: Path, moved: Path):
    updates = _updates(_env(base, moved, HERMES_QA_PROVIDER_POOL_DIR=str(folder)))
    assert updates["HERMES_AUTH_HOME"] == str(folder / POOL / "profiles" / "base")
    # The lane's own data stays in the folder it was moved to; nothing is created beside it.
    assert updates["HERMES_HOME"] == str(moved / LANE / "profiles" / "base")
    assert not (moved / POOL).exists()


def test_a_moved_lane_without_the_pool_folder_binds_its_own_folder(base: Path, moved: Path):
    updates = _updates(_env(base, moved))
    assert updates["HERMES_AUTH_HOME"] == str(moved / POOL / "profiles" / "base")


def test_a_named_pool_folder_holding_an_account_namespace_is_the_owners(base: Path, folder: Path, moved: Path):
    (folder / "acct-0123456789abcdef").mkdir()
    manifest = folder / POOL / "namespace.json"
    manifest.unlink()
    with pytest.raises(ns.NamespaceRefused) as caught:
        _updates(_env(base, moved, HERMES_QA_PROVIDER_POOL_DIR=str(folder)))
    assert caught.value.reason is ns.Reason.QA_POOL_REFUSED
    assert "owner" in caught.value.detail
    assert not manifest.exists()


@pytest.mark.parametrize("which", ["relative", "base", "inside-base"])
def test_a_pool_folder_must_be_absolute_and_clear_of_the_base_root(base: Path, moved: Path, which: str):
    value = {"relative": "qa-sandbox/hermes-namespaces", "base": str(base),
             "inside-base": str(base / "hermes-namespaces")}[which]
    with pytest.raises(ns.NamespaceRefused) as caught:
        _updates(_env(base, moved, HERMES_QA_PROVIDER_POOL_DIR=value))
    assert caught.value.reason is ns.Reason.QA_POOL_REFUSED


def test_a_named_pool_folder_is_qa_only_and_a_launcher_hand_off(base: Path, folder: Path, moved: Path):
    manifest = folder / POOL / "namespace.json"
    manifest.unlink()
    env = _env(base, moved, namespace="qa", HERMES_QA_PROVIDER_POOL_DIR=str(folder))
    with pytest.raises(ns.NamespaceRefused) as caught:
        _updates(env)
    assert caught.value.reason is ns.Reason.QA_POOL_REFUSED
    env = _env(base, moved, HERMES_QA_PROVIDER_POOL_DIR=str(folder))
    del env["HERMES_LAUNCHER_SPAWNED"]
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.qa_provider_pool_home(ns.layout(LANE, env), env)
    assert caught.value.reason is ns.Reason.QA_POOL_REFUSED
    assert not manifest.exists()
