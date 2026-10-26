"""RT-NAMESPACE-ORIGIN: ``namespace.json`` records ``origin: account | launcher-profile`` (naming map ruling 2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import namespace_admin as admin
from agent_runtime import namespace_seed as seeding
from hermes_cli import _namespace_bootstrap as ns

QA = "stagec-smoke"
ACCT = "acct-0123456789abcdef"


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    (tmp_path / ".hermes").mkdir()
    return {"HERMES_DEPENDENCY_ROOT": str(tmp_path / ".hermes")}


def _manifest(env, ns_id) -> dict:
    return json.loads(ns.layout(ns_id, env).manifest_path.read_text(encoding="utf-8"))


def test_the_origin_the_launcher_hands_in_is_recorded_at_creation(env):
    ns.ensure_manifest(ns.layout(QA, env), ns.requested_origin({ns.ORIGIN_ENV: "account"}))
    assert _manifest(env, QA)["origin"] == "account"  # the launcher's word beats the id form


def test_with_no_origin_handed_in_the_id_form_decides(env):
    ns.ensure_manifest(ns.layout(QA, env))
    ns.ensure_manifest(ns.layout(ACCT, env))
    assert _manifest(env, QA)["origin"] == "launcher-profile"
    assert _manifest(env, ACCT)["origin"] == "account"


def test_an_old_manifest_gets_its_origin_once_and_a_recorded_one_is_never_rewritten(env):
    item = ns.layout(QA, env)
    item.root.mkdir(parents=True)
    item.manifest_path.write_text(json.dumps({"schema": 1, "id": QA, "created_at": "t"}), encoding="utf-8")
    ns.ensure_manifest(item, "account")
    assert _manifest(env, QA)["origin"] == "account"
    assert _manifest(env, QA)["created_at"] == "t"
    ns.ensure_manifest(item, "launcher-profile")
    assert _manifest(env, QA)["origin"] == "account"


def test_an_unknown_origin_word_refuses():
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.requested_origin({ns.ORIGIN_ENV: "guest"})
    assert caught.value.reason is ns.Reason.INVALID_ORIGIN
    assert ns.requested_origin({}) is None


def test_list_reset_and_delete_report_the_recorded_origin(env):
    ns.ensure_manifest(ns.layout(QA, env), "account")
    assert {r["id"]: r["origin"] for r in admin.list_namespaces(env)["namespaces"]} == {QA: "account"}
    admin.reset(QA, env)
    assert _manifest(env, QA)["origin"] == "account"  # a reset keeps what kind of namespace it is
    assert admin.delete(QA, env)["origin"] == "account"


def test_memories_seed_into_a_namespace_whose_recorded_origin_is_account(env):
    base = Path(env["HERMES_DEPENDENCY_ROOT"])
    (base / "memories").mkdir()
    (base / "memories" / "MEMORY.md").write_text("m\n", encoding="utf-8")
    ns.ensure_manifest(ns.layout(QA, env), "account")
    assert seeding.seed(QA, "base", env, with_memories=True, dry_run=True)["ok"] is True
    ns.ensure_manifest(ns.layout("stagec-smoke-2", env), "launcher-profile")
    with pytest.raises(ns.NamespaceRefused) as caught:
        seeding.seed("stagec-smoke-2", "base", env, with_memories=True, dry_run=True)
    assert caught.value.reason is ns.Reason.MEMORIES_NOT_ACCOUNT
