"""The account sandbox namespace ``acct-<16 hex>-dev`` (row RT-NAMESPACE-SANDBOX-KIND).

Launcher plan EDITION_SWITCH_NAMESPACE_STORE §2.1 and owner ruling Q4 (2026-10-20): the Developer
Edition may run an account in its sandbox instead of the account namespace; ``list`` reports it as
kind ``account-sandbox`` (``ACCOUNT_ID``'s fullmatch used to call it ``profile``), and the sandbox
seeds at most once, from its own account namespace — the sanctioned copy. Temp roots only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import namespace_admin as admin
from agent_runtime import namespace_seed as seeding
from hermes_cli import _namespace_bootstrap as ns

HEX = "0123456789abcdef"
ACCT, SANDBOX, OTHER, QA = f"acct-{HEX}", f"acct-{HEX}-dev", "acct-fedcba9876543210", "stagec-smoke"


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    base = tmp_path / ".hermes"
    (base / "profiles" / "base").mkdir(parents=True)
    out = {"HERMES_DEPENDENCY_ROOT": str(base), "HERMES_NAMESPACES_DIR": str(tmp_path / "hermes-namespaces")}
    for ns_id in (ACCT, OTHER):
        item = ns.layout(ns_id, out)
        ns.ensure_manifest(item)
        (item.root / "config.yaml").write_text("model: x\n", encoding="utf-8")
        (item.home() / "memories").mkdir(parents=True)
        (item.home() / "memories" / "MEMORY.md").write_text("m\n", encoding="utf-8")
    return out


def _refused(call) -> str:
    with pytest.raises(ns.NamespaceRefused) as caught:
        call()
    return caught.value.reason.value


def test_list_reports_the_sandbox_as_its_own_kind(env):
    for ns_id in (SANDBOX, QA):
        ns.ensure_manifest(ns.layout(ns_id, env))
    kinds = {row["id"]: row["kind"] for row in admin.list_namespaces(env)["namespaces"]}
    assert kinds == {ACCT: "account", OTHER: "account", SANDBOX: "account-sandbox", QA: "profile"}


def test_the_sandbox_seeds_once_and_only_from_its_own_account(env):
    assert _refused(lambda: seeding.seed(SANDBOX, "base", env)) == "namespace_seed_source"
    assert _refused(lambda: seeding.seed(SANDBOX, OTHER, env)) == "namespace_seed_source"
    out = seeding.seed(SANDBOX, ACCT, env, with_memories=True)
    assert out["ok"] is True and out["from"] == ACCT
    manifest = json.loads(ns.layout(SANDBOX, env).manifest_path.read_text(encoding="utf-8"))
    assert manifest["seeded_from"] == ACCT and manifest["with_memories"] is True
    assert _refused(lambda: seeding.seed(SANDBOX, ACCT, env)) == "namespace_already_seeded"


def test_a_profile_still_refuses_memories(env):
    assert _refused(lambda: seeding.seed(QA, ACCT, env, with_memories=True)) == "namespace_memories_not_account"
