"""Namespace resolution (``hermes_cli/_namespace_bootstrap.py``) — rows RT-NAMESPACE-ROOT / -ID-CHARSET.

Every test builds its own base root under ``tmp_path`` and passes an explicit environment; nothing
here reads or writes the operator's live Hermes root.
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


@pytest.fixture(autouse=True)
def _long_paths(monkeypatch):
    """The path budget has its own file; here a long ``tmp_path`` must not decide a resolution."""
    monkeypatch.setattr(ns, "long_paths_enabled", lambda: True)


@pytest.fixture
def base(tmp_path: Path) -> Path:
    root = tmp_path / "install" / ".hermes"
    root.mkdir(parents=True)
    return root


def _env(base: Path, **extra: str) -> dict[str, str]:
    return {"HERMES_HOME": str(base), "LOCALAPPDATA": str(base.parent / "appdata"), **extra}


def _launcher(base: Path, **extra: str) -> dict[str, str]:
    return _env(base, HERMES_LAUNCHER_SPAWNED="1", **extra)


# -- the resolution table ------------------------------------------------------------------------------


def test_a_namespace_is_a_sibling_root_of_the_base_and_homes_the_process_inside_it(base: Path):
    env = _launcher(base, HERMES_NAMESPACE="stagec-smoke")
    res = ns.resolve_cli(["hermes", "harness", "serve"], env)
    root = base.parent / "hermes-namespaces" / "stagec-smoke"
    assert res.layout is not None and res.layout.root == root and res.source == "env"
    assert not ns.is_inside(root, base) and not ns.is_inside(base, root)
    updates = ns.env_updates(res, env)
    assert updates["HERMES_HOME"] == str(root / "profiles" / "base")  # the base-root HOME names the install
    assert updates["HERMES_HEAD_HOME"] == str(root / "profiles" / "base")
    assert updates["HERMES_AGENT_RUNTIME_ROOT"] == str(root / "agent-runtime")
    assert updates["HERMES_NAMESPACE"] == "stagec-smoke"


def test_a_namespace_borrows_the_base_install_and_is_fenced(base: Path):
    env = _launcher(base, HERMES_NAMESPACE="qa")
    updates = ns.env_updates(ns.resolve_cli(["hermes"], env), env)
    assert updates["HERMES_DEPENDENCY_ROOT"] == str(base)  # pm reads the base's venv; never syncs its own
    assert updates["HERMES_REGISTRY_WRITE_FENCE"] == "1"
    assert updates["HERMES_DISABLE_LAZY_INSTALLS"] == "1"
    # setdefault: an operator's own value wins
    env["HERMES_REGISTRY_WRITE_FENCE"] = "0"
    assert "HERMES_REGISTRY_WRITE_FENCE" not in ns.env_updates(ns.resolve_cli(["hermes"], env), env)


def test_the_namespaces_dir_override_and_the_dependency_root_name_the_base(base: Path, tmp_path: Path):
    elsewhere = tmp_path / "ns-dir"
    home = tmp_path / "ns-dir" / "qa" / "profiles" / "work"
    env = {"HERMES_DEPENDENCY_ROOT": str(base), "HERMES_NAMESPACES_DIR": str(elsewhere),
           "HERMES_HOME": str(home), "HERMES_NAMESPACE": "qa", "HERMES_LAUNCHER_SPAWNED": "1"}
    res = ns.resolve_cli(["hermes"], env)
    assert res.layout.root == elsewhere / "qa" and res.layout.base_root == base
    assert "HERMES_HOME" not in ns.env_updates(res, env)  # an explicit home inside the namespace is kept


@pytest.mark.parametrize(
    "key, where",
    [
        ("HERMES_HOME", lambda base: base / "profiles" / "coder"),  # the base root
        ("HERMES_HEAD_HOME", lambda base: base.parent / "hermes-namespaces" / "other" / "profiles" / "base"),
        ("HERMES_AGENT_RUNTIME_ROOT", lambda base: base.parent / "elsewhere" / "agent-runtime"),
    ],
)
def test_an_explicit_path_outside_the_namespace_refuses(base: Path, key, where):
    env = _launcher(base, HERMES_NAMESPACE="qa", HERMES_DEPENDENCY_ROOT=str(base), **{key: str(where(base))})
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.resolve_cli(["hermes"], env)
    assert caught.value.reason is ns.Reason.HOME_ESCAPE


def test_the_namespaces_dir_may_not_sit_inside_the_base(base: Path):
    env = _launcher(base, HERMES_NAMESPACE="qa", HERMES_NAMESPACES_DIR=str(base / "hermes-namespaces"))
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.resolve_cli(["hermes"], env)
    assert caught.value.reason is ns.Reason.CONTAINMENT


def test_base_is_reserved_and_names_the_base_root(base: Path):
    env = _launcher(base, HERMES_NAMESPACE="base")
    res = ns.resolve_cli(["hermes", "chat"], env)
    assert res.layout is None and res.namespace == ""
    assert ns.env_updates(res, env) == {"HERMES_NAMESPACE": "base", "HERMES_NAMESPACE_SOURCE": "env"}
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.layout("base", env)
    assert caught.value.reason is ns.Reason.RESERVED


def test_unset_in_a_launcher_spawned_serve_changes_nothing(base: Path):
    env = _launcher(base)
    before = dict(env)
    argv = ["hermes", "harness", "serve", "--ndjson"]
    res = ns.apply_cli_namespace(argv, env)
    assert res.layout is None and res.source == "none"
    assert env == before and argv == ["hermes", "harness", "serve", "--ndjson"]
    assert not (base.parent / "hermes-namespaces").exists()


def test_the_flag_is_stripped_anywhere_before_the_separator_and_must_agree_with_the_env(base: Path):
    env = _launcher(base)
    argv = ["hermes", "harness", "serve", "--namespace", "qa", "--ndjson", "--", "--namespace", "x"]
    res = ns.apply_cli_namespace(argv, env)
    assert res.source == "argv" and env["HERMES_NAMESPACE"] == "qa"
    assert argv == ["hermes", "harness", "serve", "--ndjson", "--", "--namespace", "x"]
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.resolve_cli(["hermes", "--namespace=qa"], _launcher(base, HERMES_NAMESPACE="other"))
    assert caught.value.reason is ns.Reason.ARGV_ENV_MISMATCH


def test_the_manifest_is_written_once_on_first_resolve(base: Path):
    env = _launcher(base, HERMES_NAMESPACE="qa")
    ns.apply_cli_namespace(["hermes"], env)
    manifest = base.parent / "hermes-namespaces" / "qa" / "namespace.json"
    first = json.loads(manifest.read_text(encoding="utf-8"))
    assert first["schema"] == 1 and first["id"] == "qa" and first["created_at"]
    ns.apply_cli_namespace(["hermes"], _launcher(base, HERMES_NAMESPACE="qa"))
    assert json.loads(manifest.read_text(encoding="utf-8")) == first


# -- RT-NAMESPACE-ID-CHARSET -----------------------------------------------------------------------------


@pytest.mark.parametrize("good", ["qa", "stagec-smoke", "acct-0123456789abcdef", "a", "x" * 48, "0-bob"])
def test_valid_ids(good):
    assert ns.validate_id(good) == good


@pytest.mark.parametrize(
    "bad", ["", "Bob", "-x", "a/b", "a\\b", "..", ".", "a.b", "x" * 49, " qa", "qa ", "nul", "com1", "a_b", "é"])
def test_malformed_ids_refuse(bad):
    with pytest.raises(ns.NamespaceRefused) as caught:
        ns.validate_id(bad)
    assert caught.value.reason is ns.Reason.INVALID_ID


def test_a_malformed_id_refuses_to_start_and_never_falls_back_to_the_base(base: Path):
    env = _launcher(base, HERMES_NAMESPACE="../escape")
    before = dict(env)
    argv = ["hermes", "chat"]
    with pytest.raises(SystemExit) as caught:
        ns.apply_cli_namespace(argv, env)
    assert caught.value.code == 2
    assert env == before  # HERMES_HOME still names the base, but the process is not running
    assert sorted(p.name for p in base.parent.iterdir()) == [".hermes"]


def test_the_real_entry_point_refuses_a_malformed_id_with_exit_2(base: Path):
    env = {**os.environ, **_launcher(base, HERMES_NAMESPACE="Not-Valid")}
    proc = subprocess.run([sys.executable, "-m", "hermes_cli.main", "status"], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 2, proc.stderr[-2000:]
    line = json.loads(proc.stderr.strip().splitlines()[-1])
    assert line["reason"] == "namespace_invalid_id"


# -- hermes namespace probe ------------------------------------------------------------------------------


def _probe(base: Path, *args: str, **extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_NAMESPACE")}
    env.update(_env(base, **extra))
    return subprocess.run([sys.executable, "-m", "hermes_cli.main", "namespace", *args], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)


def test_probe_exits_0_with_json_and_writes_nothing(base: Path):
    proc = _probe(base, "probe", "acct-0123456789abcdef")
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout)
    assert out["schema"] == 1
    assert out["namespaces_dir"] == str(base.parent / "hermes-namespaces")
    assert out["root"] == str(base.parent / "hermes-namespaces" / "acct-0123456789abcdef")
    # a real child reads the real registry: a long tmp_path on a box without long paths is the budget's refusal
    assert out["refusal"] is None or (not out["long_paths"] and out["refusal"]["reason"] == "namespace_root_too_long")
    assert not (base.parent / "hermes-namespaces").exists()


def test_probe_reports_a_refusal_and_an_unknown_verb_exits_non_zero(base: Path):
    out = json.loads(_probe(base, "probe", "Bad").stdout)
    assert out["refusal"]["reason"] == "namespace_invalid_id"
    assert _probe(base, "no-such-verb").returncode != 0
