"""scripts/ci/fork_blob_size.py: upstream's blob-size guard, with the phone wheels the fork commits exempt.

Row FH-THE-BLOB-SIZE-GUARD-ACCEPTS-THE-COMMITTED-MATCHER-WHEELS (owner RULED 2026-11-22, option (a)): the
committed matcher wheels pass through a fork-owned seam (the phone wheels lock's ``path`` pins), and
upstream's ``check_blob_size.py`` and ``.github/blob-size-allowlist.txt`` keep upstream's bytes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ci" / "fork_blob_size.py"
sys.path.insert(0, str(SCRIPT.parent))

import check_blob_size as upstream
import fork_blob_size as fork

LIMIT = 4096
DIST = "crates/project_files_match/dist"
ARM = f"{DIST}/eternia_project_files_match-1.0.0-py3-none-android_24_arm64_v8a.whl"
X86 = f"{DIST}/eternia_project_files_match-1.0.0-py3-none-android_24_x86_64.whl"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "GITHUB_STEP_SUMMARY"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return env


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, env=_env(), capture_output=True, text=True,
                          encoding="utf-8", stdin=subprocess.DEVNULL, timeout=60, check=False)
    assert proc.returncode == 0, (args, proc.stderr)
    return proc.stdout.strip()


def _wheel(seed: int) -> bytes:
    return bytes((i * 7 + seed) % 256 for i in range(LIMIT * 2))  # NUL bytes: git calls it binary


def _lock(*paths: str) -> bytes:
    targets = {f"t{i}": {"path": p, "sha256": "0" * 64} for i, p in enumerate(paths)}
    targets["remote"] = {"url": "https://example.invalid/w.whl", "sha256": "1" * 64}
    return json.dumps({"schema": 1, "wheels": {"eternia-project-files-match": {
        "version": "1.0.0", "targets": targets}}}).encode()


def _commit(repo: Path, files: dict[str, bytes]) -> str:
    for rel, data in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
        _git(repo, "add", "--", rel)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "step")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _commit(root, {"README": b"base\n"})
    return root


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--limit", str(LIMIT), *args],
                          env=_env(), capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)


def test_the_pinned_wheels_pass_where_upstreams_guard_alone_reds(repo: Path):
    """The seam's reason, read: the same commit reds under upstream's script and passes under the fork's."""
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, {ARM: _wheel(1), X86: _wheel(2), fork.PHONE_WHEELS_LOCK: _lock(ARM, X86)})
    assert upstream.main(["--repo", str(repo), "--limit", str(LIMIT), "--base", base, "--head", head]) == 1
    proc = _run(repo, "--base", base, "--head", head)
    assert proc.returncode == 0, proc.stdout


def test_a_committed_wheel_the_lock_does_not_pin_is_red(repo: Path):
    """A wheel dropped from the fork allowlist (its pin gone from the lock) is an offender, exit 1.
    KILLING MUTATION: exempt the crate's dist/ directory instead of the pinned paths -> exit 0.
    Recorded red 2026-11-22, w1118a-blob."""
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, {ARM: _wheel(1), X86: _wheel(2), fork.PHONE_WHEELS_LOCK: _lock(ARM)})
    proc = _run(repo, "--base", base, "--head", head)
    assert proc.returncode == 1
    assert f"::error file={X86}::" in proc.stdout and f"file={ARM}" not in proc.stdout
    assert fork.PHONE_WHEELS_LOCK in proc.stdout  # the fork's way out is named, not upstream's list alone


def test_a_big_blob_on_no_list_is_red_beside_the_exempt_wheels(repo: Path):
    """KILLING MUTATIONS: report no offender, or exempt the crate's dist/ directory -> the unlisted third
    wheel passes; drop the x86_64 pin in ``committed_wheel_paths`` -> it is flagged too. Recorded red
    2026-11-22, w1118a-blob."""
    base = _git(repo, "rev-parse", "HEAD")
    third = f"{DIST}/eternia_project_files_match-1.0.0-py3-none-ios_13_0_arm64_iphoneos.whl"
    head = _commit(repo, {ARM: _wheel(1), X86: _wheel(2), third: _wheel(3), "docs/shot.png": _wheel(4),
                          fork.PHONE_WHEELS_LOCK: _lock(ARM, X86)})
    proc = _run(repo, "--base", base, "--head", head)
    assert proc.returncode == 1
    flagged = {line.split("::")[1].removeprefix("error file=") for line in proc.stdout.splitlines()
               if line.startswith("::error")}
    assert flagged == {third, "docs/shot.png"}


def test_the_lists_are_read_from_the_judged_side(repo: Path):
    """A head that drops the pin is judged by its own lock, as upstream judges by the head's allowlist."""
    base = _git(repo, "rev-parse", "HEAD")
    pinned = _commit(repo, {ARM: _wheel(1), fork.PHONE_WHEELS_LOCK: _lock(ARM)})
    assert _run(repo, "--base", base, "--head", pinned).returncode == 0
    (repo / fork.PHONE_WHEELS_LOCK).write_bytes(_lock())  # the working tree unpins it
    _git(repo, "rm", "-q", "--cached", "--", ARM)
    assert _run(repo, "--base", base).returncode == 1  # untracked now, and no list names it


def test_an_unreadable_lock_is_a_usage_error_not_a_pass(repo: Path):
    base = _git(repo, "rev-parse", "HEAD")
    head = _commit(repo, {ARM: _wheel(1), fork.PHONE_WHEELS_LOCK: b"{not json"})
    proc = _run(repo, "--base", base, "--head", head)
    assert proc.returncode == 2 and "fork_blob_size:" in proc.stderr


def test_every_wheel_committed_under_the_crate_is_exempt_through_the_lock():
    """The real tree: each committed wheel under the crate's dist/ is a ``path`` pin of the real lock.
    KILLING MUTATION: drop the x86_64 pin in ``committed_wheel_paths`` -> red. Recorded red 2026-11-22,
    w1118a-blob."""
    committed = set(_git(REPO, "ls-files", "--", f"{DIST}/*.whl").splitlines())
    assert {ARM, X86} <= committed
    assert committed <= fork.fork_allowlist(REPO, "HEAD")
    assert committed <= fork.fork_allowlist(REPO, None)


def test_upstreams_guard_and_its_allowlist_name_no_fork_wheel():
    """The ruling: upstream's two files keep upstream's bytes; the exemption lives only in the fork's seam."""
    assert not {p for p in upstream.read_allowlist(REPO / upstream.ALLOWLIST) if p.startswith(f"{DIST}/")}
    assert "phone_wheels" not in (REPO / "scripts" / "ci" / "check_blob_size.py").read_text(encoding="utf-8")


def test_the_forks_ci_runs_the_fork_guard_on_the_judged_commits():
    """KILLING MUTATION: drop the ``blob-size`` job from fork-gates.yml (or point it at upstream's script)
    -> red. Recorded red 2026-11-22, w1118a-blob."""
    from agent_runtime import yaml_io

    workflow = yaml_io.load((REPO / ".github" / "workflows" / "fork-gates.yml").read_text(encoding="utf-8"))
    runs = [step.get("run", "") for step in workflow["jobs"]["blob-size"]["steps"]]
    assert any("python3 scripts/ci/fork_blob_size.py --base \"$BASE\" --head HEAD" in run for run in runs), runs
    assert not any("check_blob_size.py" in run for run in runs)
