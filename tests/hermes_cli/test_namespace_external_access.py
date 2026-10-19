"""Outside the launcher hermes reaches ONLY the signed-in account's namespace (row RT-NAMESPACE-EXTERNAL-ACCESS).

Owner ruling Q9 (2026-10-19): "it should only be able to use the namespace of the logged in
profile, and only if external use is allowed". The launcher writes ``<base>/namespace-active.json``
while an account is signed in AND external use is allowed, and deletes it otherwise. Temp roots only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli import _namespace_bootstrap as ns

ACTIVE = "acct-0123456789abcdef"
OTHER = "acct-fedcba9876543210"


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / ".hermes"
    root.mkdir()
    return root


def _activate(base: Path, ns_id: str = ACTIVE) -> None:
    (base / "namespace-active.json").write_text(json.dumps({"schema": 1, "namespace": ns_id}), encoding="utf-8")


def _external(base: Path, **extra: str) -> dict[str, str]:
    return {"HERMES_HOME": str(base), **extra}


def _refusal(argv, env) -> str:
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.resolve_cli(argv, env)
    return caught.value.reason.value


def test_with_no_record_a_named_namespace_is_refused(base: Path):
    assert _refusal(["hermes", "chat"], _external(base, HERMES_NAMESPACE=ACTIVE)) == "namespace_external_disabled"
    assert _refusal(["hermes", "--namespace", ACTIVE, "chat"], _external(base)) == "namespace_external_disabled"


def test_a_refused_external_process_exits_2_and_creates_nothing(base: Path):
    env = _external(base, HERMES_NAMESPACE=ACTIVE)
    with pytest.raises(SystemExit) as caught:
        ns.apply_cli_namespace(["hermes", "chat"], env)
    assert caught.value.code == 2
    assert not (base.parent / "hermes-namespaces").exists()


def test_only_the_active_namespace_is_reachable(base: Path):
    _activate(base)
    res = ns.resolve_cli(["hermes", "chat"], _external(base, HERMES_NAMESPACE=ACTIVE))
    assert res.namespace == ACTIVE and res.source == "env"
    assert _refusal(["hermes", "chat"], _external(base, HERMES_NAMESPACE=OTHER)) == "namespace_not_active"


def test_with_no_namespace_named_the_record_is_followed(base: Path):
    _activate(base)
    res = ns.resolve_cli(["hermes", "chat"], _external(base))
    assert res.namespace == ACTIVE and res.source == "active-file"
    assert res.layout.root == base.parent / "hermes-namespaces" / ACTIVE


def test_base_install_verbs_and_admin_never_follow_the_record(base: Path):
    _activate(base)
    assert ns.resolve_cli(["hermes", "--namespace", "base", "chat"], _external(base)).layout is None
    for verb in ("pm", "update"):
        assert ns.resolve_cli(["hermes", verb], _external(base)).source == "none"
    admin = ns.resolve_cli(["hermes", "namespace", "list"], _external(base, HERMES_NAMESPACE=OTHER))
    assert admin.source == "admin" and admin.layout is None


def test_with_no_record_and_no_namespace_the_base_is_unchanged(base: Path):
    env = _external(base)
    before = dict(env)
    assert ns.apply_cli_namespace(["hermes", "chat"], env).source == "none"
    assert env == before


def test_a_launcher_spawned_process_ignores_the_record(base: Path):
    _activate(base)
    launcher = _external(base, HERMES_LAUNCHER_SPAWNED="1")
    assert ns.resolve_cli(["hermes", "harness", "serve"], launcher).source == "none"
    named = ns.resolve_cli(["hermes", "harness", "serve"], {**launcher, "HERMES_NAMESPACE": OTHER})
    assert named.namespace == OTHER


@pytest.mark.parametrize(
    "content", ["{", json.dumps({"schema": 2, "namespace": ACTIVE}), json.dumps({"schema": 1, "namespace": "Bad"}),
                json.dumps({"schema": 1, "namespace": "base"}), json.dumps([ACTIVE])])
def test_a_malformed_record_refuses(base: Path, content: str):
    (base / "namespace-active.json").write_text(content, encoding="utf-8")
    assert _refusal(["hermes", "chat"], _external(base)) == "namespace_active_record_invalid"
