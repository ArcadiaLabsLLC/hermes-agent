"""``.githooks/post-merge`` repairs the operator's install only from the primary checkout.

``core.hooksPath`` is per-clone, so the hook also fires in a lane's linked worktree,
whose shell inherits the operator's ``HERMES_HOME``; there it must verify only
(``--check``), never copy a branch's skill packages into that home
(``docs/agent-runtime-harness/planned/isolated-worktree-hook-home-2026-10-07.md``).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".githooks" / "post-merge"
STUB = "import sys, pathlib\npathlib.Path(sys.argv[0]).with_name('argv.txt').write_text(' '.join(sys.argv[1:]) or '<repair>')\n"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _run_hook(cwd: Path) -> str:
    result = subprocess.run(["sh", str(HOOK)], cwd=cwd, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return (cwd / "scripts" / "argv.txt").read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh, as git runs its hooks")
@pytest.mark.timeout(120)
def test_the_primary_repairs_and_a_linked_worktree_only_checks(tmp_path):
    primary = tmp_path / "primary"
    (primary / "scripts").mkdir(parents=True)
    (primary / "scripts" / "verify_harness_skill_install.py").write_text(STUB, encoding="utf-8")
    _git(primary, "init", "-q")
    _git(primary, "add", "scripts/verify_harness_skill_install.py")
    _git(primary, "-c", "user.name=hook", "-c", "user.email=hook@example.invalid", "commit", "-q", "-m", "seed")
    worktree = tmp_path / "lane"
    _git(primary, "worktree", "add", "-q", "--detach", str(worktree))

    assert _run_hook(primary) == "<repair>"
    assert _run_hook(worktree) == "--check"
