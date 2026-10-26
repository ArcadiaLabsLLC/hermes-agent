"""RT-VAULT-COMMIT-HOME-MAINTENANCE: a vault-only commit sweeps no bytecode and
runs no home maintenance.

Live 2026-10-25 22:07:21: after a fast-forward of three vault-only commits the
next CLI cleared 195 ``__pycache__`` directories and logged ``home
maintenance: code changed … running steps`` — both keyed on the COMMIT, while
the serve's identity is the code tree that excludes ``Harness_Brain/``.

Real git repositories, real sweep, real ``run_boot_bootstrap``; each arm has a
positive control (a ``.py`` commit still sweeps / still runs the steps).

Named sabotage: drop the ``_code_tree_unchanged`` early return in
``_bytecode_sweep`` (the vault arm sweeps); drop the
``carry_identity_if_code_unchanged`` seam in ``boot_bootstrap`` (the vault arm
runs the steps).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_runtime.build_identity import code_tree_unchanged
from hermes_cli import _bytecode_sweep as sweep
from hermes_cli import boot_bootstrap
from hermes_cli import main as hermes_main
from hermes_cli import post_update


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """Commits ``a`` (code), ``vault`` (Harness_Brain only), ``code`` (a .py change)."""

    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "a")
    a = _git(root, "rev-parse", "HEAD")
    (root / "Harness_Brain").mkdir()
    (root / "Harness_Brain" / "TODO.md").write_text("- row\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "vault")
    vault = _git(root, "rev-parse", "HEAD")
    (root / "pkg" / "mod.py").write_text("X = 2\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "code")
    code = _git(root, "rev-parse", "HEAD")
    return root, {"a": a, "vault": vault, "code": code}


def _checkout(root: Path, sha: str) -> None:
    _git(root, "checkout", "-q", "-B", "main", sha)


def test_the_code_tree_comparison_follows_the_serve_rule(repo):
    root, c = repo
    assert code_tree_unchanged(root, c["a"], c["vault"]) is True
    assert code_tree_unchanged(root, c["vault"], c["code"]) is False
    assert code_tree_unchanged(root, "--output=x", c["code"]) is False
    assert code_tree_unchanged(root, "", c["code"]) is False


@pytest.mark.parametrize(("head", "swept"), [("vault", False), ("code", True)])
def test_the_bytecode_sweep_keys_on_the_code_tree(repo, monkeypatch, head, swept):
    root, c = repo
    _checkout(root, c[head])
    cache = root / "pkg" / "__pycache__"
    cache.mkdir()
    (cache / "mod.cpython-314.pyc").write_bytes(b"stale")
    monkeypatch.setattr(hermes_main, "PROJECT_ROOT", root)
    (root / sweep._BYTECODE_FINGERPRINT_FILE).write_text(f"git:refs/heads/main:{c['a']}", encoding="utf-8")

    sweep._sweep_stale_bytecode_if_checkout_changed()

    assert cache.exists() is (not swept)
    stamp = (root / sweep._BYTECODE_FINGERPRINT_FILE).read_text(encoding="utf-8")
    assert stamp == f"git:refs/heads/main:{c[head]}"


@pytest.mark.parametrize(
    ("head", "prior_ok", "runs"),
    [("vault", True, False), ("code", True, True), ("vault", False, True)],
)
def test_home_maintenance_keys_on_the_code_tree(repo, tmp_path, monkeypatch, head, prior_ok, runs):
    root, c = repo
    _checkout(root, c[head])
    record = tmp_path / "state" / "bootstrap" / "default.json"
    record.parent.mkdir(parents=True)
    record.write_text(
        json.dumps({"schemaVersion": 1, "identity": c["a"], "results": {"step": {"ok": prior_ok}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(boot_bootstrap, "record_path", lambda _root: record)
    calls: list[int] = []

    def _steps(_steps_list):
        calls.append(1)
        return {"step": {"ok": True}}

    monkeypatch.setattr(post_update, "run_steps", _steps)

    boot_bootstrap.run_boot_bootstrap(root)

    assert bool(calls) is runs
    stored = json.loads(record.read_text(encoding="utf-8"))
    assert stored["identity"] == c[head]
    if not runs:
        assert stored["carriedFrom"] == c["a"]
