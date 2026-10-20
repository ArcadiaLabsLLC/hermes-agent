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
    """A base root shaped like a Developer Edition root: definitions, secrets, runtime state, borrowed code."""
    root = tmp_path / ".hermes"
    files = {
        "config.yaml": "model: x\n", "SOUL.md": "soul\n", "skills/s1/SKILL.md": "s\n",
        "skills/s1/token.txt": "password = fixture-not-real\n",
        "skills/s1/references/token-budget.md": "how to budget tokens\n", "skills/s1/credentials/key.txt": "SECRET",
        "skins/dark.yaml": "k\n", "machine_roots.json": "{}",
        "auth.json": "SECRET", ".env": "SECRET", "state.db": "x", "install_id": "id", "kanban.db": "x",
        "config.yaml.bak-1": "old\n", "memories/MEMORY.md": "m\n", "logs/agent.log": "l\n",
        "cron/jobs.json": "{}", "active_profile": "coder",
        "shared/skills/team/SKILL.md": "t\n", "shared/characters/golem/character.json": "{}",
        "installs/x/marker": "x", "venvs/v/marker": "x", "bin/hermes": "x", "builds/b/marker": "x",
        "tools/node/marker": "x", "runtimes/python/marker": "x",
        "profiles/coder/config.yaml": "p\n", "profiles/coder/profile.yaml": "display_name: C\n",
        "profiles/coder/auth.json": "SECRET", "profiles/coder/.env": "SECRET", "profiles/coder/state.db": "x",
        "profiles/coder/memories/MEMORY.md": "m\n", "profiles/coder/personas/neko.md": "prompt\n",
        "profiles/.deleted/x/config.yaml": "gone\n",
        "agent-runtime/agents/neko.json": "{}", "agent-runtime/realms/r.json": "{}",
        "agent-runtime/active_realm.json": "{}", "agent-runtime/prefabs/coder/p.json": "{}",
        "agent-runtime/persona_instances/personainst_neko.json": "{}", "agent-runtime/boards/b/board.json": "{}",
        "agent-runtime/sessions/s.json": "{}", "agent-runtime/realm_sync/r/remote": "https://u:pw@host",
        "agent-runtime/gateway/pairing.json": "SECRET", "agent-runtime/events.jsonl": "{}",
        # owner ruling 2026-10-19: pets, flow graphs and workspace slots seed; code and work state never do
        "profiles/coder/pets/fluff/pet.json": "{}", "agent-runtime/flow_graphs/runtime_personainst_neko.json": "{}",
        "agent-runtime/workspace_slots/ws_default.json": "{}", "profiles/coder/cron/jobs.json": "{}",
        "profiles/coder/hooks/h/hook.py": "x", "profiles/coder/plugins/p/plugin.py": "x",
        "profiles/coder/scripts/s.py": "x", "kanban/boards/b.json": "{}",
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


#: What a seed of the ``base`` fixture copies: config, SOUL, skills (the root's, each profile's and the
#: shared library), skins, the character library, persona definitions and prompts, world definitions.
SEEDED = {
    "namespace.json", "config.yaml", "SOUL.md", "skills/s1/SKILL.md", "skills/s1/references/token-budget.md",
    "skins/dark.yaml", "machine_roots.json", "shared/skills/team/SKILL.md", "shared/characters/golem/character.json",
    "profiles/coder/config.yaml", "profiles/coder/profile.yaml", "profiles/coder/personas/neko.md",
    "agent-runtime/agents/neko.json", "agent-runtime/realms/r.json", "agent-runtime/active_realm.json",
    "agent-runtime/prefabs/coder/p.json", "profiles/coder/pets/fluff/pet.json",
    "agent-runtime/flow_graphs/runtime_personainst_neko.json", "agent-runtime/workspace_slots/ws_default.json",
}
#: What ``--with-memories`` adds (the root's and each profile's memory).
MEMORY_FILES = {"memories/MEMORY.md", "profiles/coder/memories/MEMORY.md"}


def test_seed_copies_the_allowlist_and_never_a_secret(base: Path):
    out = admin.seed(QA, "base", _env(base))
    root = base.parent / "hermes-namespaces" / QA
    assert _files(root) == SEEDED
    skipped = {row["path"]: row["reason"] for row in out["skipped"]}
    # inside an allowlisted tree a secret-word FILE is judged by its value; a word-named directory never copies
    assert skipped["skills/s1/token.txt"] == "secret_value" and skipped["skills/s1/credentials"] == "never_seed"
    manifest = json.loads((root / "namespace.json").read_text(encoding="utf-8"))
    assert manifest["seeded_from"] == "base" and manifest["seeded_at"] and manifest["id"] == QA
    assert manifest["seeded"] == out["copied"] and manifest["skipped"] == out["skipped"]


def test_every_source_entry_is_copied_skipped_with_a_reason_or_borrowed(base: Path):
    """The plan is total: no entry of the source's root, store, shared libraries or profiles goes unaccounted."""
    out = admin.seed(QA, "base", _env(base))
    skipped = {row["path"]: row["reason"] for row in out["skipped"]}
    assert out["borrowed"] == ["installs", "venvs", "bin", "builds", "tools", "runtimes"]
    for secret in ("auth.json", ".env", "state.db", "install_id", "profiles/coder/auth.json",
                   "profiles/coder/.env", "profiles/coder/state.db",
                   "agent-runtime/persona_instances", "agent-runtime/sessions", "agent-runtime/realm_sync",
                   "agent-runtime/gateway", "logs"):
        assert skipped[secret] == "never_seed", secret
    for other in ("config.yaml.bak-1", "active_profile", "profiles/.deleted", "agent-runtime/events.jsonl"):
        assert skipped[other] == "not_allowlisted", other
    tops = {rel.split("/")[0] for rel in [*out["copied"], *skipped, *out["borrowed"]]}
    assert tops == {p.name for p in base.iterdir()}
    sections = {"profiles": base / "profiles", "agent-runtime": base / "agent-runtime", "shared": base / "shared"}
    for name, folder in sections.items():
        named = {rel.split("/")[1] for rel in [*out["copied"], *skipped] if rel.startswith(f"{name}/")}
        assert named == {p.name for p in folder.iterdir()}, name


def test_the_dry_run_names_the_owner_s_rulings_as_skip_reasons(base: Path):
    """Owner ruling 2026-10-19: code and work state never seed, memories only on opt-in — and the plan says so."""
    plan = admin.seed(QA, "base", _env(base), dry_run=True)
    skipped = {row["path"]: row["reason"] for row in plan["skipped"]}
    code, work, opt_in = ("owner ruled 2026-10-19: runs or schedules code", "owner ruled 2026-10-19: work state",
                          "opt-in: --with-memories, acct- namespaces only")
    assert {p: skipped[p] for p in ("cron", "profiles/coder/cron", "profiles/coder/hooks", "profiles/coder/plugins",
                                    "profiles/coder/scripts")} == dict.fromkeys(
        ("cron", "profiles/coder/cron", "profiles/coder/hooks", "profiles/coder/plugins", "profiles/coder/scripts"), code)
    assert {p: skipped[p] for p in ("kanban", "kanban.db", "agent-runtime/boards")} == dict.fromkeys(
        ("kanban", "kanban.db", "agent-runtime/boards"), work)
    assert skipped["memories"] == skipped["profiles/coder/memories"] == opt_in
    assert plan["with_memories"] is False


def test_memories_seed_only_with_the_flag_and_only_into_an_account_namespace(base: Path):
    env = _env(base)
    admin.seed(QA, "base", env)
    assert not MEMORY_FILES & _files(base.parent / "hermes-namespaces" / QA)
    assert _refused(lambda: admin.seed("qa-two", "base", env, with_memories=True)) == "namespace_memories_not_account"
    assert not (base.parent / "hermes-namespaces" / "qa-two").exists()
    out = admin.seed(ACCT, "base", env, with_memories=True)
    root = base.parent / "hermes-namespaces" / ACCT
    assert _files(root) == SEEDED | MEMORY_FILES
    assert {"memories", "profiles/coder/memories"} <= set(out["copied"])
    assert json.loads((root / "namespace.json").read_text(encoding="utf-8"))["with_memories"] is True


def test_a_dry_run_prints_the_real_plan_and_writes_nothing(base: Path):
    env = _env(base)
    before = _files(base.parent)
    plan = admin.seed(QA, "base", env, dry_run=True)
    assert _files(base.parent) == before and not (base.parent / "hermes-namespaces").exists()
    assert plan["dry_run"] is True and plan["copied"] and plan["skipped"]
    real = admin.seed(QA, "base", env)
    assert {k: plan[k] for k in ("copied", "skipped", "borrowed")} == {k: real[k] for k in ("copied", "skipped", "borrowed")}
    assert _refused(admin.seed, QA, "base", env) == "namespace_already_seeded"
    with pytest.raises(ns.NamespaceRefused):  # a dry run refuses exactly as the real seed would
        admin.seed(QA, "base", env, dry_run=True)


def test_the_allowlists_carry_no_never_seed_entry():
    allowlists = admin.HOME_SEED + admin.STORE_SEED + admin.ROOT_SEED + admin.SHARED_SEED
    assert admin.allowlist_violations(allowlists) == []
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

    planned = run("seed", QA, "--from", "base", "--dry-run")
    assert planned.returncode == 0, planned.stderr[-2000:]
    assert json.loads(planned.stdout)["dry_run"] is True and not (base.parent / "hermes-namespaces").exists()
    seeded = run("seed", QA, "--from", "base")
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    assert json.loads(seeded.stdout)["copied"]
    listed = json.loads(run("list").stdout)
    assert [row["id"] for row in listed["namespaces"]] == [QA]
    refused = run("delete", "base")
    assert refused.returncode == 2 and json.loads(refused.stdout)["reason"] == "namespace_reserved"
