"""scripts/rerere_train.sh replays a branch's merge resolutions into rerere without resetting.

Fork-owned (Harness_Brain/50 — Agent Handoffs/Merging upstream.md, Step 2b). A daily merge that
resolved a modify/delete conflict by deleting the file has no blob for that path; the trainer
used to die there (`git show` under `set -e`, 2026-10-14 at deleted `tools/tirith_security.py`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "rerere_train.sh"
_GIT_BASH = Path("C:/Program Files/Git/bin/bash.exe")


def _bash() -> str:
    if _GIT_BASH.is_file():
        return str(_GIT_BASH)
    found = shutil.which("bash")
    if found is None or "system32" in found.lower():  # WSL's launcher is not the repo's shell
        pytest.skip("no POSIX bash")
    return found


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL)
    return done.stdout


def _commit(repo: Path, message: str, **files: str | None) -> None:
    for name, text in files.items():
        path = repo / name
        if text is None:
            _git(repo, "rm", "-q", name)
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
            _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "core.autocrlf", "false")
    _commit(repo, "base", **{"f.txt": "one\n", "g.txt": "alpha\n"})
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "side", **{"f.txt": None, "g.txt": "side\n"})
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "main", **{"f.txt": "two\n", "g.txt": "main\n"})
    # The integration merge: g.txt resolved by hand, f.txt resolved by deleting it.
    subprocess.run(["git", "merge", "--no-ff", "--no-commit", "side"], cwd=repo,
                   capture_output=True, check=False, stdin=subprocess.DEVNULL)
    (repo / "g.txt").write_text("resolved\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "g.txt")
    _git(repo, "rm", "-q", "f.txt")
    _git(repo, "commit", "-q", "-m", "integrate side")
    _git(repo, "checkout", "-q", "--detach", "main~1")
    return repo


def _train(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_bash(), str(SCRIPT), "HEAD..main"], cwd=repo, capture_output=True,
                          text=True, check=False, timeout=120, stdin=subprocess.DEVNULL,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t",
                               "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"})


def test_a_resolution_that_deletes_a_conflicted_file_trains(repo: Path) -> None:
    done = _train(repo)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 merge(s) recorded" in done.stdout
    rr_cache = Path(_git(repo, "rev-parse", "--git-common-dir").strip())
    rr_cache = (repo / rr_cache if not rr_cache.is_absolute() else rr_cache) / "rr-cache"
    assert any(rr_cache.glob("*/postimage")), "g.txt's resolution was not recorded"
    assert _git(repo, "status", "--porcelain", "--untracked-files=no") == ""


def test_the_trainer_never_resets() -> None:
    code = [line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")]
    assert not [line for line in code if "reset" in line], "rerere_train.sh must not run a reset"
