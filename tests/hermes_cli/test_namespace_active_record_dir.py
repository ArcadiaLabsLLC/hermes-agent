"""``namespace-active.json`` schema 2 names the shared namespaces dir (row RT-NAMESPACE-ACTIVE-RECORD-DIR).

Launcher plan EDITION_SWITCH_NAMESPACE_STORE §2.1: the launcher hands both editions one shared folder
outside both installs, so ``<base parent>/hermes-namespaces`` no longer holds anything. Outside the
launcher, with ``HERMES_NAMESPACES_DIR`` unset, the record's ``namespaces_dir`` IS the namespaces dir —
for the CLI's resolution and for ``hermes namespace list | probe`` alike. Schema 1 is still read
(the base-sibling default). Temp roots only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import namespace_admin as admin
from hermes_cli import _namespace_bootstrap as ns

ACCT = "acct-0123456789abcdef"


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "install" / ".hermes"
    root.mkdir(parents=True)
    return root


def _record(base: Path, **extra: object) -> None:
    (base / ns.ACTIVE_RECORD_NAME).write_text(json.dumps({"namespace": ACCT, **extra}), encoding="utf-8")


def test_outside_the_launcher_the_records_dir_is_the_namespaces_dir(base: Path, tmp_path: Path):
    shared = tmp_path / "AppData" / "Eternia" / "hermes-namespaces"
    _record(base, schema=2, namespaces_dir=str(shared))
    env = {"HERMES_DEPENDENCY_ROOT": str(base)}
    res = ns.resolve_cli(["hermes", "chat"], env)
    assert res.source == "active-file" and res.layout.root == shared / ACCT
    assert ns.env_updates(res, env)["HERMES_NAMESPACES_DIR"] == str(shared)  # every child agrees
    assert ns.probe(env, ACCT)["namespaces_dir"] == str(shared)
    (shared / ACCT).mkdir(parents=True)
    (shared / ACCT / ns.MANIFEST_NAME).write_text(json.dumps({"schema": 1, "id": ACCT}), encoding="utf-8")
    assert [row["id"] for row in admin.list_namespaces(env)["namespaces"]] == [ACCT]


def test_schema_one_keeps_the_base_sibling_default(base: Path):
    _record(base, schema=1)
    res = ns.resolve_cli(["hermes", "chat"], {"HERMES_DEPENDENCY_ROOT": str(base)})
    assert res.layout.root == base.parent / ns.DIRNAME / ACCT


def test_the_env_and_the_launcher_outrank_the_record(base: Path, tmp_path: Path):
    _record(base, schema=2, namespaces_dir=str(tmp_path / "recorded"))
    env = {"HERMES_DEPENDENCY_ROOT": str(base), "HERMES_NAMESPACES_DIR": str(tmp_path / "explicit")}
    assert ns.namespaces_dir(env, base) == tmp_path / "explicit"
    spawned = {"HERMES_DEPENDENCY_ROOT": str(base), "HERMES_LAUNCHER_SPAWNED": "1"}
    assert ns.namespaces_dir(spawned, base) == base.parent / ns.DIRNAME


@pytest.mark.parametrize("folder", [None, "relative/dir", 7])
def test_a_schema_two_record_without_an_absolute_dir_refuses(base: Path, folder: object):
    _record(base, schema=2, **({} if folder is None else {"namespaces_dir": folder}))
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.resolve_cli(["hermes", "chat"], {"HERMES_DEPENDENCY_ROOT": str(base)})
    assert caught.value.reason is ns.Reason.ACTIVE_RECORD_INVALID


def test_the_records_dir_is_still_fenced_from_the_base_root(base: Path):
    _record(base, schema=2, namespaces_dir=str(base / "inside"))
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.resolve_cli(["hermes", "chat"], {"HERMES_DEPENDENCY_ROOT": str(base)})
    assert caught.value.reason is ns.Reason.CONTAINMENT
