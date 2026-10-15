"""The post-merge hook installs harness skills from the primary checkout only.

core.hooksPath is per-clone, so ``.githooks/post-merge`` also fires on a merge
inside a lane worktree; installing from there put a lane's unlanded skills in
front of the live serve (lane h-turn1-conn, 2026-10-06). The hook is run for
real, against a throwaway clone whose verifier only records that it ran.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".githooks" / "post-merge"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("sh") is None,
    reason="needs git and sh",
)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _run_hook(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(cwd / ".githooks" / "post-merge")],
        cwd=cwd, capture_output=True, text=True, timeout=60,
    )


@pytest.fixture
def clone(tmp_path: Path) -> tuple[Path, Path]:
    primary = tmp_path / "primary"
    (primary / ".githooks").mkdir(parents=True)
    (primary / "scripts").mkdir()
    shutil.copy2(HOOK, primary / ".githooks" / "post-merge")
    # The stand-in verifier records an install (a run without --check) in its tree.
    (primary / "scripts" / "verify_harness_skill_install.py").write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "if '--check' not in sys.argv:\n"
        "    Path(__file__).resolve().parents[1].joinpath('INSTALLED').write_text('ran')\n"
        "print('harness-skill-install: ok')\n",
        encoding="utf-8",
    )
    _git(primary, "init", "-q")
    _git(primary, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(primary, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    lane = tmp_path / "lane"
    _git(primary, "worktree", "add", "-q", str(lane), "-b", "lane/x")
    return primary, lane


def test_a_lane_worktree_merge_installs_nothing(clone):
    _primary, lane = clone
    result = _run_hook(lane)
    assert result.returncode == 0, result.stderr
    assert "linked worktree" in result.stdout
    assert not (lane / "INSTALLED").exists()


def test_the_primary_checkout_still_installs(clone):
    primary, _lane = clone
    result = _run_hook(primary)
    assert result.returncode == 0, result.stderr
    assert "harness-skill-install: ok" in result.stdout
    assert (primary / "INSTALLED").read_text() == "ran"
