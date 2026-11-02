"""``runtime.work.list`` reads every board it can: a brain hermes just created, and the boards beside a failing one.

RT-WORK-LIST-READS-CREATED-BRAIN: ``create_brain`` commits the slot's brain in hermes's own worktree and
pushes it; the operator's checkout never holds it, so the list must find it in that worktree.
RT-WORK-LIST-ONE-BOARD-REFUSAL: one board's sync refusal is that board's ``refused``, never the list's.
Both found live (launcher MC-WORKSPACE-TODO-ALL-PROJECTS, w1101d steps 4 and 5).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from agent_runtime.project_store import ProjectStore
from agent_runtime.work import store as work_store
from agent_runtime.workspace_projects import set_project_connection
from agent_runtime.workspace_slots import bind_project

T0 = "2026-11-02T10:00:00+00:00"
NOTE = "Launcher_Brain/20 — Active Initiatives/q.md"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _repo(tmp_path: Path, name: str, row_id: str | None) -> SimpleNamespace:
    """A bare origin and a clone of it; with ``row_id`` a brain holding that row, else only a README."""

    origin = tmp_path / f"{name}.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    clone = tmp_path / name
    git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    if row_id is None:
        (clone / "README.md").write_text("no brain here\n", encoding="utf-8")
    else:
        (clone / NOTE).parent.mkdir(parents=True)
        (clone / NOTE).write_text(HEAD + f"- **`{row_id}` — a row** · READY 2026-11-02\n", encoding="utf-8",
                                  newline="\n")
    git("add", "-A", cwd=clone)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed", cwd=clone)
    git("push", "-q", "origin", "main", cwd=clone)
    return SimpleNamespace(origin=origin, clone=clone, url=f"https://example.com/{name}.git")


def _project(workspace: str, project_id: str, repo: SimpleNamespace, *, revision: int) -> None:
    ProjectStore().declare(project_id, [{"name": "launcher", "repo": {"clone_url": repo.url, "default_branch": "main"}}],
                           issued_at=T0, machine="m", name=project_id.upper())
    bind_project(project_id, "launcher", str(repo.clone), issued_at=T0)
    set_project_connection(workspace, project_id, connected=True, expected_revision=revision)


def _rows(board: dict) -> list[str]:
    return [row["id"] for queue in board["queues"] for row in queue["rows"]]


def test_a_brain_create_brain_made_lists_at_once(tmp_path, workspace):
    """Mutation: drop the worktree arm (``worktree_brain`` returns ``board``) -> the board lists no queue."""
    repo = _repo(tmp_path, "bare", None)
    _project(workspace, "p1", repo, revision=0)
    scope = SimpleNamespace(workspace_id=workspace)
    made = work_store.create_brain(scope, {"request_id": "brain-1", "slot": "launcher", "project_id": "p1"}, "operator")
    assert made["receipt"]["pushed"] is True
    # The operator's checkout never holds the brain: it lives in hermes's worktree and at the origin's tip.
    assert not (repo.clone / "Work_Brain").exists()
    (board,) = work_store.list_work(scope, {})["boards"]
    assert (board["brain_dir"], board["readable"]) == ("Work_Brain/20 — Active Initiatives", True)
    assert [queue["note"] for queue in board["queues"]] == ["Work_Brain/20 — Active Initiatives/work-queue.md"]
    # A second create answers the brain it already made, writing nothing.
    again = work_store.create_brain(scope, {"request_id": "brain-2", "slot": "launcher", "project_id": "p1"}, "operator")
    assert again["receipt"] is None
