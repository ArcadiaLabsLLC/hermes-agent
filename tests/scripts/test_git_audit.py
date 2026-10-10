"""The opt-in git receipt names every test that runs git against the checkout (design sweep D3.16).

Plan: ``docs/agent-runtime-harness/planned/design-sweep-d3-2026-10-10.md`` § D3.16
stage 2. A throwaway session with ``HERMES_TEST_GIT_AUDIT=1`` runs git three
ways — in the checkout, with ``-C <checkout>``, and in a ``tmp_path`` repo —
and the receipt must carry exactly the first two.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests._downstream import git_audit

_REPO_ROOT = Path(__file__).resolve().parents[2]

_THROWAWAY = '''
import subprocess

CHECKOUT = {checkout!r}


def test_git_in_the_checkout():
    subprocess.run(["git", "rev-parse", "--git-dir"], cwd=CHECKOUT, capture_output=True)


def test_git_dash_c_the_checkout():
    subprocess.run(["git", "-C", CHECKOUT, "rev-parse", "HEAD"], capture_output=True)


def test_git_in_a_temp_repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], cwd=tmp_path, capture_output=True)
'''


def _session(tmp_path: Path, audit: bool) -> tuple[subprocess.CompletedProcess, Path]:
    root = tmp_path / "session"
    root.mkdir()
    (root / "test_throwaway_git.py").write_text(_THROWAWAY.format(checkout=str(_REPO_ROOT)), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != git_audit.GIT_AUDIT_ENV}
    if audit:
        env[git_audit.GIT_AUDIT_ENV] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(_REPO_ROOT), env.get("PYTHONPATH", "")])
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "tests._downstream.git_audit", "-p", "no:cacheprovider",
         "-o", "addopts=", "--rootdir", str(root), "-q", str(root / "test_throwaway_git.py")],
        cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    return proc, root / git_audit.RECEIPT


def test_the_receipt_names_each_git_run_against_the_checkout_and_no_other(tmp_path):
    proc, receipt = _session(tmp_path, audit=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [json.loads(line) for line in receipt.read_text(encoding="utf-8").splitlines()]

    assert [line["nodeid"].split("::")[1] for line in lines] == [
        "test_git_in_the_checkout",
        "test_git_dash_c_the_checkout",
    ]
    assert lines[0]["file"] == "test_throwaway_git.py"
    assert lines[1]["argv"][1:3] == ["-C", str(_REPO_ROOT)]


def test_off_by_default_nothing_is_recorded(tmp_path):
    proc, receipt = _session(tmp_path, audit=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not receipt.exists()


def test_the_git_directory_follows_cwd_then_each_dash_c(tmp_path):
    assert git_audit.git_directory(["python", "-c", "pass"], tmp_path) is None
    assert git_audit.git_directory(["git", "status"], tmp_path) == tmp_path
    assert git_audit.git_directory(["C:/Git/cmd/git.exe", "-C", "sub", "diff"], tmp_path) == tmp_path / "sub"
    assert git_audit.in_checkout(_REPO_ROOT / "scripts") and not git_audit.in_checkout(tmp_path)
    # Windows audits the command line, not the list
    assert git_audit._argv(r'"C:\Program Files\Git\cmd\git.exe" -C X:\repo status') == [
        r"C:\Program Files\Git\cmd\git.exe", "-C", r"X:\repo", "status",
    ]
