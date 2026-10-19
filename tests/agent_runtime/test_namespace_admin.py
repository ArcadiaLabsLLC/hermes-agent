"""``hermes namespace list | seed | reset | delete`` (row RT-NAMESPACE-CLI). Temp roots only."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_runtime import namespace_admin as admin
from agent_runtime.file_locks import try_lock_exclusive, unlock
from agent_runtime.serve_registry import register_serve_instance
from agent_runtime.serve_socket.owner_lock import socket_lock_path
from hermes_cli import _namespace_bootstrap as ns

REPO = Path(__file__).resolve().parents[2]
QA = "stagec-smoke"
ACCT = "acct-0123456789abcdef"
_REAL_LONG_PATHS = ns.long_paths_enabled  # the CLI child reads the real registry


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """A base root holding every kind of entry a seed must copy or refuse."""
    root = tmp_path / ".hermes"
    files = {
        "config.yaml": "model: x\n", "SOUL.md": "soul\n", "skills/s1/SKILL.md": "s\n",
        "skills/s1/token.txt": "SECRET\n", "skins/dark.yaml": "k\n", "machine_roots.json": "{}",
        "auth.json": "SECRET", ".env": "SECRET", "state.db": "x", "install_id": "id",
        "profiles/coder/config.yaml": "p\n", "profiles/coder/auth.json": "SECRET", "profiles/coder/.env": "SECRET",
        "profiles/.deleted/x/config.yaml": "gone\n",
        "agent-runtime/agents/neko.json": "{}", "agent-runtime/realms/r.json": "{}",
        "agent-runtime/active_realm.json": "{}", "agent-runtime/persona_instances/personainst_neko.json": "{}",
        "agent-runtime/sessions/s.json": "{}", "agent-runtime/realm_sync/r/remote": "https://u:pw@host",
        "agent-runtime/gateway/pairing.json": "SECRET",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    return root


def _env(base: Path, **extra: str) -> dict[str, str]:
    return {"HERMES_DEPENDENCY_ROOT": str(base), **extra}


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _refused(fn, *args) -> str:
    with pytest.raises(ns.NamespaceRefused) as caught:
        fn(*args)
    return caught.value.reason.value


def test_seed_copies_the_allowlist_and_never_a_secret(base: Path):
    out = admin.seed(QA, "base", _env(base))
    root = base.parent / "hermes-namespaces" / QA
    assert _files(root) == {
        "namespace.json", "config.yaml", "SOUL.md", "skills/s1/SKILL.md", "skins/dark.yaml", "machine_roots.json",
        "profiles/coder/config.yaml", "agent-runtime/agents/neko.json", "agent-runtime/realms/r.json",
        "agent-runtime/active_realm.json",
    }
    assert "skills/s1/token.txt" in out["skipped"]  # a never-seed name inside an allowlisted tree is accounted
    manifest = json.loads((root / "namespace.json").read_text(encoding="utf-8"))
    assert manifest["seeded_from"] == "base" and manifest["seeded_at"] and manifest["id"] == QA


def test_the_allowlists_carry_no_never_seed_entry():
    assert admin.allowlist_violations(admin.HOME_SEED + admin.STORE_SEED + admin.ROOT_SEED) == []
    assert admin.allowlist_violations(("auth.json", ".env.local", "state.db", "persona_instances", "a/b", "..")) == [
        "auth.json", ".env.local", "state.db", "persona_instances", "a/b", ".."]


def test_a_namespace_is_seeded_at_most_once_and_only_at_creation(base: Path):
    env = _env(base)
    admin.seed(QA, "base", env)
    assert _refused(admin.seed, QA, "base", env) == "namespace_already_seeded"
    used = ns.layout(ACCT, env)
    ns.ensure_manifest(used)
    (used.root / "profiles" / "base").mkdir(parents=True)
    assert _refused(admin.seed, ACCT, "base", env) == "namespace_not_fresh"
    admin.reset(QA, env)  # a reseed is an explicit operator act: reset, then seed
    assert admin.seed(QA, "base", env)["ok"] is True


def test_a_seed_source_is_named_never_discovered(base: Path):
    env = _env(base)
    assert _refused(admin.seed, QA, ACCT, env) == "namespace_not_found"
    admin.seed(ACCT, "base", env)
    assert admin.seed(QA, ACCT, env)["from"] == ACCT
    assert _refused(admin.seed, ACCT, ACCT, env) == "namespace_seed_source"


def _hold_lock(item) -> object:
    lock = socket_lock_path(item.store_root)
    lock.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock, "a+b")
    try_lock_exclusive(handle)
    return handle


@pytest.mark.parametrize("verb", [admin.reset, admin.delete])
def test_reset_and_delete_are_refused_while_a_serve_holds_the_namespace(base: Path, verb):
    env = _env(base)
    admin.seed(QA, "base", env)
    item = ns.layout(QA, env)
    handle = _hold_lock(item)
    try:
        assert _refused(verb, QA, env) == "namespace_busy"
    finally:
        unlock(handle)
        handle.close()
    register_serve_instance(item.store_root, pid=os.getpid(), argv=["hermes", "harness", "serve"])
    assert _refused(verb, QA, env) == "namespace_busy"  # a live registered serve without the socket lane
    assert (item.root / "config.yaml").is_file()  # nothing was removed


def test_delete_refuses_base_and_this_process_s_own_namespace(base: Path):
    env = _env(base)
    admin.seed(QA, "base", env)
    assert _refused(admin.delete, "base", env) == "namespace_reserved"
    assert _refused(admin.delete, QA, {**env, "HERMES_NAMESPACE": QA}) == "namespace_in_use_by_this_process"
    assert _refused(admin.delete, "nothing-here", env) == "namespace_not_found"


def test_reset_empties_and_delete_removes(base: Path):
    env = _env(base)
    admin.seed(QA, "base", env)
    root = base.parent / "hermes-namespaces" / QA
    admin.reset(QA, env)
    assert _files(root) == {"namespace.json"}
    assert "seeded_at" not in json.loads((root / "namespace.json").read_text(encoding="utf-8"))
    admin.delete(QA, env)
    assert not root.exists()
    assert (base / "auth.json").is_file()  # the base root is never touched


def test_list_reports_each_namespace_and_skips_what_is_not_one(base: Path):
    env = _env(base)
    admin.seed(ACCT, "base", env)
    ns.ensure_manifest(ns.layout(QA, env))
    (base.parent / "hermes-namespaces" / "Not_An_Id").mkdir()
    (base.parent / "hermes-namespaces" / "no-manifest").mkdir()
    rows = {row["id"]: row for row in admin.list_namespaces(env)["namespaces"]}
    assert set(rows) == {ACCT, QA}
    assert rows[ACCT]["kind"] == "account" and rows[QA]["kind"] == "profile"
    assert rows[ACCT]["size_bytes"] > rows[QA]["size_bytes"] > 0
    assert rows[ACCT]["seeded_from"] == "base" and rows[ACCT]["busy"] is None and rows[ACCT]["last_serve_at"] is None


def test_the_cli_prints_json_and_exits_2_on_a_refusal(base: Path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_NAMESPACE")}
    env.update(_env(base, HERMES_NAMESPACES_DIR=str(base.parent / "hermes-namespaces")))
    if len(str(base.parent / "hermes-namespaces" / QA)) > ns.ROOT_BUDGET and not _REAL_LONG_PATHS():
        pytest.skip("tmp_path is over the namespace path budget and this box has no long paths")

    def run(*args):
        return subprocess.run([sys.executable, "-m", "hermes_cli.main", "namespace", *args], cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=180, check=False)

    seeded = run("seed", QA, "--from", "base")
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    assert json.loads(seeded.stdout)["copied"]
    listed = json.loads(run("list").stdout)
    assert [row["id"] for row in listed["namespaces"]] == [QA]
    refused = run("delete", "base")
    assert refused.returncode == 2 and json.loads(refused.stdout)["reason"] == "namespace_reserved"
