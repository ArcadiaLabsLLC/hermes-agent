"""RT-BRAIN-PATHS-PLAIN-LIST slice 4: the brains' remote check against real git.

A bare origin two commits ahead of a clone: hermes's own brain (workspace / personal) is fast-forwarded when
clean and kept when dirty; a Project brain (the user's repo) is only counted; a brain with no upstream is null.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

from agent_runtime import brain_paths, brain_remote
import pytest

from agent_runtime.brain_remote import RemoteCheck, check_brain, pull_checkout
from agent_runtime.work_store.reasons import Reason, WorkRefused

ID = ("-c", "user.name=t", "-c", "user.email=t@t.invalid")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *ID, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def _behind_by_two(tmp_path: Path, name: str) -> Path:
    origin = tmp_path / f"{name}.git"
    git("init", "-q", "--bare", "-b", "main", str(origin), cwd=tmp_path)
    seed = tmp_path / f"{name}-seed"
    git("clone", "-q", str(origin), str(seed), cwd=tmp_path)
    (seed / "Work_Brain" / "20 — Active Initiatives").mkdir(parents=True)
    (seed / "Work_Brain" / "20 — Active Initiatives" / "q.md").write_text("---\ntype: queue\n---\n", encoding="utf-8")
    (seed / "Work_Brain" / "TODO.md").write_text("# TODO\n", encoding="utf-8")
    git("add", "-A", cwd=seed)
    git("commit", "-q", "-m", "one", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    brain = tmp_path / name
    git("clone", "-q", str(origin), str(brain), cwd=tmp_path)
    for n in (2, 3):
        (seed / "Work_Brain" / f"n{n}.md").write_text(f"{n}\n", encoding="utf-8")
        git("add", "-A", cwd=seed)
        git("commit", "-q", "-m", f"c{n}", cwd=seed)
    git("push", "-q", "origin", "main", cwd=seed)
    return brain


def _head(repo: Path) -> str:
    return git("rev-parse", "HEAD", cwd=repo).strip()


def test_hermes_own_brain_fast_forwards_when_clean(tmp_path):
    """Mutation: drop the ``merge --ff-only`` arm in ``check_brain`` -> behind stays 2, red."""
    brain = _behind_by_two(tmp_path, "ws")
    before = _head(brain)
    assert check_brain(str(brain), "workspace") == 0
    assert _head(brain) != before and (brain / "Work_Brain" / "n3.md").is_file()


def test_a_dirty_workspace_brain_is_counted_not_moved(tmp_path):
    """Mutation: drop the ``_clean`` gate -> the merge runs over a dirty tree, HEAD moves, red."""
    brain = _behind_by_two(tmp_path, "ws")
    (brain / "Work_Brain" / "TODO.md").write_text("# edited, uncommitted\n", encoding="utf-8")
    before = _head(brain)
    assert check_brain(str(brain), "personal") == 2 and _head(brain) == before


def test_a_project_brain_is_only_counted(tmp_path):
    """Mutation: add ``project`` to ``FAST_FORWARD_KINDS`` -> the user's repo moves, red."""
    brain = _behind_by_two(tmp_path, "app")
    before = _head(brain)
    assert check_brain(str(brain), "project") == 2 and _head(brain) == before


def test_no_upstream_or_no_repo_is_null(tmp_path):
    lone = tmp_path / "lone"
    lone.mkdir()
    git("init", "-q", str(lone), cwd=tmp_path)
    assert check_brain(str(lone), "workspace") is None
    assert check_brain(str(tmp_path / "missing"), "workspace") is None


def _listing(entries: dict[str, str]) -> dict:
    """A list whose brains are ``{path: kind}`` (each with a brain folder)."""

    slots = [{"slot": f"s{i}", "path": p, "brain_dir": "Work_Brain"} for i, (p, k) in enumerate(entries.items())
             if k == "project"]
    own = [p for p, k in entries.items() if k == "workspace"]
    return {"schema_version": 1, "personal": {"path": None, "brain_dir": None},
            "workspaces": {"ws": {"name": "W", "brain": {"path": own[0] if own else None,
                                                         "brain_dir": "Work_Brain" if own else None},
                                  "projects": [{"project_id": "p", "name": "P", "slots": slots}]}}}


def test_a_tick_is_bounded_round_robin_and_writes_the_counts(tmp_path, monkeypatch):
    """Mutations: drop the ``per_tick`` slice -> all three checked in one tick, red; drop the cursor advance ->
    the second tick re-checks the first brains, red."""
    paths_ = {str(tmp_path / f"b{i}"): "project" for i in range(3)}
    monkeypatch.setattr(brain_remote, "read_brain_paths", lambda: _listing(paths_))
    monkeypatch.setattr(brain_remote, "check_brain", lambda path, kind: 7)
    written: list[dict] = []
    monkeypatch.setattr(brain_remote, "write_brain_paths", lambda behind: written.append(dict(behind)) or True)
    monkeypatch.setattr(brain_remote, "held_counts", lambda: {})
    check = RemoteCheck(per_tick=2)
    first = check.tick()["checked"]
    second = check.tick()["checked"]
    assert len(first) == 2 and second[0] not in first and set(first) | set(second) == set(paths_)
    assert written[-1] == {path: 7 for path in paths_}


def test_one_checkout_bound_as_project_and_own_is_never_fast_forwarded(tmp_path, monkeypatch):
    shared = str(tmp_path / "shared")
    listing = _listing({shared: "workspace"})
    listing["workspaces"]["ws"]["projects"][0]["slots"] = [{"slot": "s", "path": shared, "brain_dir": "X_Brain"}]
    monkeypatch.setattr(brain_remote, "read_brain_paths", lambda: listing)
    assert RemoteCheck().due() == [(shared, "project")]


def test_a_brain_already_in_flight_is_skipped(tmp_path, monkeypatch):
    path = str(tmp_path / "b")
    monkeypatch.setattr(brain_remote, "read_brain_paths", lambda: _listing({path: "project"}))
    monkeypatch.setattr(brain_remote, "write_brain_paths", lambda behind: False)
    monkeypatch.setattr(brain_remote, "held_counts", lambda: {})
    check = RemoteCheck()
    check._inflight.add(path)
    assert check.tick()["checked"] == []


def test_the_measured_count_reaches_the_written_list(tmp_path):
    """End to end on the isolated home: a Project slot behind its upstream lists ``behind: 2``."""
    from agent_runtime.project_store import ProjectStore
    from agent_runtime.store import WorkspaceStore
    from agent_runtime.workspace_projects import set_project_connection
    from agent_runtime.workspace_slots import bind_project

    brain = _behind_by_two(tmp_path, "app")
    WorkspaceStore().create(name="R", workspace_id="ws-r")
    ProjectStore().declare("proj-r", [{"name": "app", "repo": {"clone_url": "https://example.com/a.git"}}],
                           issued_at="2026-11-02T22:00:00+00:00", machine="m", name="R")
    bind_project("proj-r", "app", str(brain), issued_at="2026-11-02T22:00:00+00:00")
    set_project_connection("ws-r", "proj-r", connected=True, expected_revision=0)
    RemoteCheck().tick()
    listed = json.loads(brain_paths.brain_paths_path().read_text(encoding="utf-8"))
    assert listed["workspaces"]["ws-r"]["projects"][0]["slots"][0]["behind"] == 2


def test_the_ticker_ticks_until_stopped(monkeypatch):
    ticks: list[int] = []
    stop = threading.Event()

    class _Check:
        def tick(self):
            ticks.append(1)
            if len(ticks) >= 2:
                stop.set()

    from hermes_cli.harness_parts.serve.queued_turns import start_brain_remote_ticker

    thread = start_brain_remote_ticker(stop_event=stop, interval_s=0.01, check=_Check())
    thread.join(timeout=5)
    assert not thread.is_alive() and len(ticks) >= 2


# ── runtime.work.pull's git half (RT-WORK-PULL-PROJECT-CHECKOUT) ──────────────────


def test_pull_fast_forwards_a_clean_project_checkout_and_writes_its_count(tmp_path, monkeypatch):
    """Mutation: drop the ``merge --ff-only`` in ``pull_checkout`` -> pulled 0 / behind 2, red."""
    brain = _behind_by_two(tmp_path, "app")
    written: list[dict] = []
    monkeypatch.setattr(brain_remote, "write_brain_paths", lambda behind: written.append(dict(behind)) or True)
    monkeypatch.setattr(brain_remote, "held_counts", lambda: {})
    answer = pull_checkout(brain)
    assert answer["pulled"] == 2 and answer["behind"] == 0 and answer["head"] == _head(brain)
    assert (brain / "Work_Brain" / "n3.md").is_file() and written == [{str(brain): 0}]
    assert pull_checkout(brain)["pulled"] == 0


def test_pull_refuses_dirty_diverged_and_upstreamless_checkouts(tmp_path, monkeypatch):
    """Mutations: drop the ``_clean`` gate -> the dirty checkout's merge runs (git refuses or moves), the
    reason is not worktree_dirty, red; drop the ``_ahead`` gate -> the diverged ff fails as worktree_dirty, red."""
    monkeypatch.setattr(brain_remote, "write_brain_paths", lambda behind: True)
    dirty = _behind_by_two(tmp_path, "dirty")
    (dirty / "Work_Brain" / "TODO.md").write_text("# edited\n", encoding="utf-8")
    diverged = _behind_by_two(tmp_path, "div")
    (diverged / "local.md").write_text("mine\n", encoding="utf-8")
    git("add", "-A", cwd=diverged)
    git("commit", "-q", "-m", "mine", cwd=diverged)
    lone = tmp_path / "lone"
    lone.mkdir()
    git("init", "-q", str(lone), cwd=tmp_path)
    for path, reason in ((dirty, Reason.WORKTREE_DIRTY), (diverged, Reason.REMOTE_DIVERGED),
                         (lone, Reason.REMOTE_MISSING), (tmp_path / "plain", Reason.NOT_A_REPO)):
        before = _head(path) if (path / ".git").exists() and path is not lone else None
        with pytest.raises(WorkRefused) as refused:
            pull_checkout(path)
        assert refused.value.reason is reason, path
        assert before is None or _head(path) == before
