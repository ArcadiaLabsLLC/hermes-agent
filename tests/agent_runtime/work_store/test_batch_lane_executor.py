"""``BatchLaneExecutor`` and ``GitLander`` (dispatcher plan §2.2 B5, §3.2, §3.3) over REAL git in tmp repos.

Each test builds a bare ``origin.git`` and its clone under ``tmp_path``; the persona turn is a fake (it records
the brief and the workdir, and the test's hand settles it), everything else — worktrees, branches, merges, the
fast-forward push into the tmp origin — is git. Nothing reaches a real remote.

Killing mutations (plan §6 B5), each red recorded in the B5 commit body:
* ``lane_git.worktree_beside`` roots the worktree in the clone → ``test_worktree_beside_clone`` red;
* ``render_lane_brief`` budgets the body without the report ask → ``test_brief_cap`` red;
* the lane executor pushes ``land/<batch>`` to main when the landing starts →
  ``test_landing_never_pushes_before_approve`` red;
* ``BatchDispatcher.land`` without ``_one_landing`` → ``test_one_landing_at_a_time_holds_the_machine`` red.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_runtime import chat_root_send_queue as send_queue
from agent_runtime import paths
from agent_runtime.batch.lane_executor import BatchLaneExecutor, render_lane_brief
from agent_runtime.batch.lane_git import Clone, LaneGit, Site
from agent_runtime.batch.lander import GitLander
from agent_runtime.batch.machine import BatchState, LaneState
from agent_runtime.batch.planner import Member
from agent_runtime.locks import batch_landing_lock
from agent_runtime.mission_chat_workdir import (
    RUN_WORKDIR_ARG, WORKDIR_SOURCE_RUN_OVERRIDE, MissionChatWorkdir, RunWorkdirRefused, with_run_override,
)
from agent_runtime.work_store.executor import Assignment, Outcome, Verdict
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.work_store.models import Brief
from agent_runtime.work_store.persona_turn import BRIEF_MAX_LINES, REPORT_INFO, PersonaTurnExecutor
from agent_runtime.work_store.reasons import Reason, WorkRefused

from batch_support import WS, FakeManifests, dispatcher, qrow
from contract_fakes import FakeExecutor, FakeSource

ROSTER = [Member("inst-a", "alice", "engineer")]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """``origin.git`` (bare) and ``clone`` on ``main`` with one commit."""

    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                       "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(key, value)
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    git(clone, "checkout", "-q", "-b", "main")
    (clone / "README.md").write_text("base\n", encoding="utf-8")
    git(clone, "add", "README.md")
    git(clone, "commit", "-q", "-m", "base")
    git(clone, "push", "-q", "origin", "main")
    return SimpleNamespace(origin=origin, clone=clone, tmp=tmp_path)


class FakeTurns(FakeExecutor):
    """The persona-turn executor's surface the lane executor uses; ``start_from`` records brief and workdir."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: dict[str, tuple[str, str]] = {}

    def start_from(self, a, origin, *, message=None, workdir=None):
        self.sent[a.request_id] = (message, workdir)
        return self.start(a)


def lanes_over(repo, rows, **kw):
    manifests = FakeManifests()
    turns = FakeTurns()
    executor = BatchLaneExecutor(inner=turns, manifests=manifests, workspaces=lambda: [WS],
                                 clone_of=lambda _ws, _slot: Clone(repo.clone))
    d = dispatcher(FakeSource(rows), manifests=manifests, executor=executor, roster=ROSTER,
                   lander=GitLander(clone_of=lambda _ws, _slot: Clone(repo.clone)), **kw)
    batch = d.start(WS, d.plan(WS).id)
    return d, turns, batch


def commit_in(worktree: Path, name: str, text: str) -> str:
    (worktree / name).write_text(text, encoding="utf-8")
    git(worktree, "add", name)
    git(worktree, "commit", "-q", "-m", f"edit {name}")
    return git(worktree, "rev-parse", "HEAD")


def worktree_of(turns, request_id) -> Path:
    return Path(turns.sent[request_id][1])


def test_worktree_beside_clone(repo):
    d, turns, batch = lanes_over(repo, [qrow("RT-A", assignee="inst-a")])
    lane = batch.lanes[0]
    assert lane.state is LaneState.RUNNING
    where = worktree_of(turns, f"{batch.id}:{lane.id}")
    assert where == repo.tmp / ".worktrees" / f"clone-{batch.id}-{lane.id}".lower()
    assert repo.clone not in where.parents
    assert git(where, "rev-parse", "--abbrev-ref", "HEAD") == f"q/{batch.id}/{lane.id}"
    assert git(where, "rev-parse", "HEAD") == git(repo.clone, "rev-parse", "origin/main")
    brief = turns.sent[f"{batch.id}:{lane.id}"][0]
    assert str(where) in brief and "Never push main" in brief
    assert (where.with_name(where.name + "-scratch") / "brief.md").read_text(encoding="utf-8").rstrip() == brief
    # A replayed start reuses the worktree (never removed, never re-cut).
    marker = commit_in(where, "a.txt", "a\n")
    d.executor.start(Assignment(lane.lane.rows, "inst-a", lane.lane.brief, f"{batch.id}:{lane.id}"))
    assert git(where, "rev-parse", "HEAD") == marker


def test_brief_cap(repo):
    site = Site("hermes", Clone(repo.clone), repo.tmp / ".worktrees" / "clone-b-l1", "q/B/L1", "origin/main")
    brief = Brief(title="lane L1", objective="\n".join(f"step {i}" for i in range(30)),
                  inputs=tuple(f"input {i}" for i in range(30)), constraints=("a", "b", "c", "d"),
                  acceptance="every row done")
    rows = tuple(RowRef("hermes", "q.md", f"RT-{i}") for i in range(12))
    text = render_lane_brief(Assignment(rows, "inst-a", brief, "B:L1"), [site], landing=False)
    lines = text.splitlines()
    assert len(lines) <= BRIEF_MAX_LINES
    assert lines[0].startswith("lane L1:") and lines[0].endswith("Never push main.")
    assert f"```{REPORT_INFO}" in lines and lines[-1] == "```"
    assert any(str(site.worktree) in line for line in lines) and any("git push -u origin q/B/L1" in line for line in lines)


def test_settle_reports_the_lanes_commits_and_a_sequenced_lane_is_cut_from_its_predecessor(repo):
    rows = [qrow("RT-A", heading="One", files=["pkg/shared.py"], assignee="inst-a"),
            qrow("RT-B", heading="Two", files=["pkg/shared.py"], assignee="inst-a")]
    d, turns, batch = lanes_over(repo, rows)
    first, second = batch.lanes
    assert second.lane.after == (first.id,) and second.state is LaneState.CLAIMED
    sha = commit_in(worktree_of(turns, f"{batch.id}:{first.id}"), "shared.txt", "one\n")
    turns.settle(f"{batch.id}:{first.id}", Outcome(Verdict.DONE, report="ok"))
    after = d.load(WS, batch.id)
    assert after.lane(first.id).commits == (sha,) and after.lane(second.id).state is LaneState.RUNNING
    later = worktree_of(turns, f"{batch.id}:{second.id}")
    assert git(later, "rev-parse", "HEAD") == sha and (later / "shared.txt").is_file()


def _land(repo):
    rows = [qrow("RT-A", heading="One", assignee="inst-a"), qrow("RT-B", heading="Two", assignee="inst-a")]
    d, turns, batch = lanes_over(repo, rows)
    shas = {}
    for lane, (name, text) in zip(batch.lanes, [("a.txt", "a\n"), ("b.txt", "b\n")]):
        shas[lane.id] = commit_in(worktree_of(turns, f"{batch.id}:{lane.id}"), name, text)
        turns.settle(f"{batch.id}:{lane.id}", Outcome(Verdict.DONE, report="ok"))
    assert d.load(WS, batch.id).state is BatchState.READY_TO_LAND
    return d, turns, batch, shas


def test_landing_never_pushes_before_approve(repo):
    d, turns, batch, shas = _land(repo)
    main_before = git(repo.origin, "rev-parse", "main")
    landing = d.land(WS, batch.id)
    assert landing.state is BatchState.LANDING and landing.landing.state is LaneState.RUNNING
    land = worktree_of(turns, f"{batch.id}:LAND:1")
    assert land.name == f"clone-{batch.id}-land".lower()
    assert git(land, "rev-parse", "--abbrev-ref", "HEAD") == f"land/{batch.id}"
    for sha in shas.values():
        git(land, "merge-base", "--is-ancestor", sha, "HEAD")
    assert len(git(land, "rev-list", "--merges", "origin/main..HEAD").splitlines()) == 2  # --no-ff
    assert "Merged --no-ff:" in turns.sent[f"{batch.id}:LAND:1"][0]
    assert git(repo.origin, "rev-parse", "main") == main_before
    turns.settle(f"{batch.id}:LAND:1", Outcome(Verdict.DONE, report="green: 4 passed"))
    waiting = d.load(WS, batch.id)
    assert waiting.state is BatchState.AWAITING_APPROVAL
    assert waiting.landing.commits == (git(land, "rev-parse", "HEAD"),)
    assert git(repo.origin, "rev-parse", "main") == main_before
    landed = d.approve(WS, batch.id)
    assert landed.state is BatchState.LANDED and landed.landing_sha == git(land, "rev-parse", "HEAD")
    assert git(repo.origin, "rev-parse", "main") == landed.landing_sha


def test_approve_refuses_a_moved_main_and_pushes_nothing(repo):
    d, turns, batch, _shas = _land(repo)
    d.land(WS, batch.id)
    turns.settle(f"{batch.id}:LAND:1", Outcome(Verdict.DONE, report="green"))
    other = repo.tmp / "other"
    subprocess.run(["git", "clone", "-q", str(repo.origin), str(other)], check=True, capture_output=True)
    moved = commit_in(other, "c.txt", "c\n")
    git(other, "push", "-q", "origin", "HEAD:main")
    with pytest.raises(WorkRefused) as refused:
        d.approve(WS, batch.id)
    assert refused.value.reason is Reason.PUSH_CONTENDED
    assert git(repo.origin, "rev-parse", "main") == moved
    assert d.load(WS, batch.id).state is BatchState.AWAITING_APPROVAL


def test_a_conflicting_lane_is_named_and_the_landing_tree_stays_clean(repo):
    rows = [qrow("RT-A", heading="One", assignee="inst-a"), qrow("RT-B", heading="Two", assignee="inst-a")]
    d, turns, batch = lanes_over(repo, rows)
    for lane, text in zip(batch.lanes, ["one\n", "two\n"]):
        commit_in(worktree_of(turns, f"{batch.id}:{lane.id}"), "README.md", text)
        turns.settle(f"{batch.id}:{lane.id}", Outcome(Verdict.DONE, report="ok"))
    d.land(WS, batch.id)
    land = worktree_of(turns, f"{batch.id}:LAND:1")
    brief = turns.sent[f"{batch.id}:LAND:1"][0]
    assert f"Conflicted, merge it by hand first: q/{batch.id}/{batch.lanes[1].id}" in brief
    assert git(land, "status", "--porcelain") == ""


def test_one_landing_at_a_time_holds_the_machine(repo):
    d, _turns, batch, _shas = _land(repo)
    with batch_landing_lock():
        with pytest.raises(WorkRefused) as refused:
            d.land(WS, batch.id)
    assert refused.value.reason is Reason.LANDING_IN_PROGRESS
    assert d.load(WS, batch.id).state is BatchState.READY_TO_LAND


def test_the_run_workdir_outranks_the_ladder_and_a_missing_one_refuses(tmp_path):
    ladder = MissionChatWorkdir(path=str(tmp_path), source="user_home")
    there = tmp_path / "lane"
    there.mkdir()
    assert with_run_override(ladder, None) is ladder
    won = with_run_override(ladder, str(there))
    assert won.path == str(there.resolve()) and won.source == WORKDIR_SOURCE_RUN_OVERRIDE
    with pytest.raises(RunWorkdirRefused) as refused:
        with_run_override(ladder, str(tmp_path / "gone"))
    assert refused.value.reason == "missing"


def test_a_lane_turn_whose_worktree_is_gone_is_refused_not_grounded_on_the_ladder(tmp_path, monkeypatch):
    """RT-BATCH-RUN-WORKDIR-FAILS-OPEN: the admit phase refuses with a typed reason before anything runs."""

    from hermes_cli.harness_parts.persona.chat_turn_commit import admit

    emitted = []
    monkeypatch.setattr(admit, "_mission_chat_emit", lambda _args, data: emitted.append(data))
    turn = SimpleNamespace(
        args=SimpleNamespace(**{RUN_WORKDIR_ARG: str(tmp_path / "gone")}), instance=SimpleNamespace(id="inst-a"),
        normalized_persona="neko", session_id="root-lane", client_message_id="cm-1",
    )
    assert admit._AdmitPhases._admit_run_workdir(turn) == 2
    assert emitted[0]["ok"] is False and emitted[0]["reason"] == "run_workdir_unavailable"
    assert emitted[0]["run_workdir_reason"] == "missing"
    (tmp_path / "here").mkdir()
    turn.args = SimpleNamespace(**{RUN_WORKDIR_ARG: str(tmp_path / "here")})
    assert admit._AdmitPhases._admit_run_workdir(turn) is None
    turn.args = SimpleNamespace()
    assert admit._AdmitPhases._admit_run_workdir(turn) is None and len(emitted) == 1


def test_the_persona_turn_carries_the_lane_brief_and_workdir(tmp_path):
    instances = SimpleNamespace(get=lambda _id: SimpleNamespace(id="inst-a", persona_id="neko",
                                                               runtime_root=str(paths.store_root())))
    turns = PersonaTurnExecutor(instances=instances, root_of=lambda store, **_: "root-lane", wake=lambda: None,
                                workdir_of=lambda _instance: None)
    a = Assignment((RowRef("hermes", "q.md", "RT-A"),), "inst-a", Brief(title="t", objective="o"), "BATCH-X:L1")
    run = turns.start_from(a, {"batch_lane": "L1"}, message="the lane brief", workdir=str(tmp_path))
    entry = send_queue.find("root-lane", run.client_message_id)
    assert entry.args["message"] == "the lane brief" and entry.args[RUN_WORKDIR_ARG] == str(tmp_path)


def test_lane_git_refuses_a_path_that_is_not_a_worktree(repo):
    site = Site("hermes", Clone(repo.clone), repo.tmp / ".worktrees" / "clone-b-l9", "q/B/L9", "origin/main")
    site.worktree.mkdir(parents=True)
    (site.worktree / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(WorkRefused) as refused:
        LaneGit().ensure(site)
    assert refused.value.reason is Reason.WORKTREE_FAILED
