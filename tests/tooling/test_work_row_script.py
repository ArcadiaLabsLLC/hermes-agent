"""``scripts/work_row.py`` — a session's by-ID row op: commit by pathspec, push, never fetch or reset."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.gate

ROOT = Path(__file__).resolve().parents[2]
NOTE = "Harness_Brain/20 — Active Initiatives/q.md"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"
ROWS = "- **`RT-A` — first** · READY 2026-10-18\n- **`RT-B` — second** · READY 2026-10-18\n"


def _load():
    spec = importlib.util.spec_from_file_location("work_row_script", ROOT / "scripts" / "work_row.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


work_row = _load()


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


@pytest.fixture
def clones(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    for key in ("GIT_AUTHOR", "GIT_COMMITTER"):
        monkeypatch.setenv(f"{key}_NAME", "Session Lane")
        monkeypatch.setenv(f"{key}_EMAIL", "lane@test.invalid")
    origin = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    mine = tmp_path / "mine"
    git("clone", "-q", str(origin), str(mine), cwd=tmp_path)
    (mine / NOTE).parent.mkdir(parents=True)
    (mine / NOTE).write_text(HEAD + ROWS, encoding="utf-8", newline="\n")
    (mine / "README.md").write_text("seed\n", encoding="utf-8")
    git("add", "-A", cwd=mine)
    git("commit", "-q", "-m", "seed", cwd=mine)
    git("push", "-q", "-u", "origin", "main", cwd=mine)
    other = tmp_path / "other"
    git("clone", "-q", str(origin), str(other), cwd=tmp_path)
    return origin, mine, other


def test_claim_by_id_commits_by_pathspec_and_pushes(clones):
    origin, mine, _ = clones
    (mine / "README.md").write_text("staged, not this commit's\n", encoding="utf-8")
    git("add", "README.md", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 0
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "queue: claim RT-A r-lane"
    assert git("show", "--name-only", "--format=", "main", cwd=origin).strip() == NOTE
    assert "**TAKEN " in git("show", f"main:{NOTE}", cwd=origin)
    assert git("diff", "--cached", "--name-only", cwd=mine).strip() == "README.md"


def test_non_fast_forward_exits_3_and_touches_nothing_else(clones, capsys):
    origin, mine, other = clones
    (other / NOTE).write_text(HEAD + ROWS.replace("second", "renamed"), encoding="utf-8", newline="\n")
    git("commit", "-q", "-am", "other session", cwd=other)
    git("push", "-q", "origin", "main", cwd=other)
    tracking = git("rev-parse", "origin/main", cwd=mine)
    assert work_row.main(["claim", "RT-A", "--who", "r-lane", "--repo", str(mine)]) == 3
    assert "fetch, then re-run" in capsys.readouterr().err
    assert git("rev-parse", "origin/main", cwd=mine) == tracking
    assert git("log", "-1", "--format=%s", "main", cwd=origin).strip() == "other session"


def test_never_fetches_or_resets(clones):
    _, mine, _ = clones
    calls: list[list[str]] = []

    def fake(args, repo):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    for argv in (["claim", "RT-A"], ["set-status", "RT-A", "--status", "DEFERRED 2026-10-18: later"],
                 ["delete", "RT-B"], ["append", "RT-C", "--row", "- **`RT-C` — new** · READY 2026-10-18"]):
        assert work_row.main([*argv, "--who", "r-lane", "--repo", str(mine)], git=fake) == 0
    verbs = {call[0] for call in calls}
    assert verbs == {"add", "commit", "push"}
    assert not verbs & {"fetch", "reset", "stash", "pull", "merge", "rebase", "checkout"}
