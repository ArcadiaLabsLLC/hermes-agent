"""RT-BRAIN-PATHS-PLAIN-LIST slice 4: the brains' remote check against real git.

A bare origin two commits ahead of a clone: hermes's own brain (workspace / personal) is fast-forwarded when
clean and kept when dirty; a slot brain (the user's repo) is only counted; a brain with no upstream is null.
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


def test_a_slot_brain_is_only_counted(tmp_path):
    """Mutation: add ``slot`` to ``FAST_FORWARD_KINDS`` -> the user's repo moves, red."""
    brain = _behind_by_two(tmp_path, "app")
    before = _head(brain)
    assert check_brain(str(brain), "slot") == 2 and _head(brain) == before


def test_no_upstream_or_no_repo_is_null(tmp_path):
    lone = tmp_path / "lone"
    lone.mkdir()
    git("init", "-q", str(lone), cwd=tmp_path)
    assert check_brain(str(lone), "workspace") is None
    assert check_brain(str(tmp_path / "missing"), "workspace") is None


def _listing(entries: dict[str, str]) -> dict:
    """A list whose brains are ``{path: kind}`` (each with a brain folder)."""

    slots = [{"slot": f"s{i}", "path": p, "brain_dir": "Work_Brain"} for i, (p, k) in enumerate(entries.items())
             if k == "slot"]
    own = [p for p, k in entries.items() if k == "workspace"]
    return {"schema_version": 2, "personal": {"path": None, "brain_dir": None},
            "workspaces": {"ws": {"name": "W", "brain": {"path": own[0] if own else None,
                                                         "brain_dir": "Work_Brain" if own else None},
                                  "slots": slots}}}


def test_a_tick_is_bounded_round_robin_and_writes_the_counts(tmp_path, monkeypatch):
    """Mutations: drop the ``per_tick`` slice -> all three checked in one tick, red; drop the cursor advance ->
    the second tick re-checks the first brains, red."""
    paths_ = {str(tmp_path / f"b{i}"): "slot" for i in range(3)}
    monkeypatch.setattr(brain_remote, "read_brain_paths", lambda: _listing(paths_))
    monkeypatch.setattr(brain_remote, "check_brain", lambda path, kind: 7)
    written: list[dict] = []
    monkeypatch.setattr(brain_remote, "write_brain_paths", lambda behind: written.append(dict(behind)) or True)
    monkeypatch.setattr(brain_remote, "held_counts", dict)
    check = RemoteCheck(per_tick=2)
    first = check.tick()["checked"]
    second = check.tick()["checked"]
    assert len(first) == 2 and second[0] not in first and set(first) | set(second) == set(paths_)
    assert written[-1] == {path: 7 for path in paths_}


def test_one_checkout_bound_as_slot_and_own_is_never_fast_forwarded(tmp_path, monkeypatch):
    shared = str(tmp_path / "shared")
    listing = _listing({shared: "workspace"})
    listing["workspaces"]["ws"]["slots"] = [{"slot": "s", "path": shared, "brain_dir": "X_Brain"}]
    monkeypatch.setattr(brain_remote, "read_brain_paths", lambda: listing)
    assert RemoteCheck().due() == [(shared, "slot")]


def test_a_brain_already_in_flight_is_skipped(tmp_path, monkeypatch):
    path = str(tmp_path / "b")
    monkeypatch.setattr(brain_remote, "read_brain_paths", lambda: _listing({path: "slot"}))
    monkeypatch.setattr(brain_remote, "write_brain_paths", lambda behind: False)
    monkeypatch.setattr(brain_remote, "held_counts", dict)
    check = RemoteCheck()
    check._inflight.add(path)
    assert check.tick()["checked"] == []


def test_the_measured_count_reaches_the_written_list(tmp_path):
    """End to end on the isolated home: a workspace slot behind its upstream lists ``behind: 2``."""
    from agent_runtime.store import WorkspaceStore
    from agent_runtime.workspace_slots import bind, declare

    brain = _behind_by_two(tmp_path, "app")
    WorkspaceStore().create(name="R", workspace_id="ws-r")
    declare("ws-r", [{"name": "app", "repo": {"clone_url": "https://example.com/a.git"}}],
            issued_at="2026-11-02T22:00:00+00:00", machine="m")
    bind("ws-r", "app", str(brain), issued_at="2026-11-02T22:00:00+00:00")
    RemoteCheck().tick()
    listed = json.loads(brain_paths.brain_paths_path().read_text(encoding="utf-8"))
    assert listed["workspaces"]["ws-r"]["slots"][0]["behind"] == 2


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
    monkeypatch.setattr(brain_remote, "held_counts", dict)
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


# ── RT-SLOT-BRAIN-MAKE-REMOTE: a remote-less Project checkout gets a private repository on the person's ask ──


class _FakeGitHub:
    """``connected_github`` / ``create_private_repo`` faked; a local bare repository plays the created one
    (``url.<dir>.insteadOf``). Nothing reaches ``gh``, a network or a real account."""

    HOST = "https://github.example/octo/"

    def __init__(self, root: Path, monkeypatch) -> None:
        from agent_runtime import git_host_account

        self.root, self.created, self.refuse = root, [], None
        root.mkdir()
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{root.as_posix()}/.insteadOf")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", self.HOST)
        monkeypatch.setattr(git_host_account, "connected_github",
                            lambda *a, **k: git_host_account.GitHubAccount("octo", "test"))
        monkeypatch.setattr(git_host_account, "create_private_repo", self.create)

    def create(self, account, name):
        from agent_runtime.git_host_account import GitHostRefused

        if self.refuse is not None:
            raise GitHostRefused(self.refuse, name)
        git("init", "-q", "--bare", "-b", "main", str(self.root / f"{name}.git"), cwd=self.root)
        self.created.append(name)
        return f"{self.HOST}{name}.git"


def _project(tmp_path: Path, name: str = "My App") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    git("init", "-q", "-b", "main", str(repo), cwd=tmp_path)
    (repo / "a.md").write_text("a\n", encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "main work", cwd=repo)
    git("checkout", "-q", "-b", "feature", cwd=repo)
    (repo / "b.md").write_text("b\n", encoding="utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "feature work", cwd=repo)
    return repo


def test_a_remote_less_checkout_gets_a_private_repo_with_only_its_current_branch(tmp_path, monkeypatch):
    """RULED 2026-11-12: push the CURRENT branch only. Mutation: ``push --all`` in place of the current branch
    (``adopt_remote`` with ``branch=current``) -> ``main`` reaches the host, red."""
    from agent_runtime.brain_remote import make_checkout_remote

    hub = _FakeGitHub(tmp_path / "host", monkeypatch)
    repo = _project(tmp_path)
    made = make_checkout_remote(repo)
    bare = hub.root / "my-app.git"
    assert hub.created == ["my-app"] and made == {"url": f"{hub.HOST}my-app.git", "repo_name": "my-app",
                                                    "branch": "feature", "git_account": "octo"}
    assert git("for-each-ref", "--format=%(refname)", "refs/heads", cwd=bare).split() == ["refs/heads/feature"]
    assert git("rev-parse", "feature", cwd=bare) == git("rev-parse", "HEAD", cwd=repo)
    assert git("rev-parse", "--abbrev-ref", "@{u}", cwd=repo).strip() == "origin/feature"


@pytest.mark.parametrize("case, reason", [
    ("remote", Reason.REMOTE_EXISTS), ("dirty", Reason.WORKTREE_DIRTY), ("detached", Reason.INVALID),
    ("refused", Reason.REMOTE_EXISTS), ("plain", Reason.NOT_A_REPO),
])
def test_making_a_remote_is_refused_and_leaves_the_checkout_as_it_was(tmp_path, monkeypatch, case, reason):
    """A refused creation adds no ``origin``. Mutation: add ``origin`` (``git remote add``) before
    ``create_private_repo`` in ``make_checkout_remote`` -> the ``refused`` case leaves a remote, red."""
    from agent_runtime.brain_remote import make_checkout_remote

    hub = _FakeGitHub(tmp_path / "host", monkeypatch)
    repo = _project(tmp_path) if case != "plain" else tmp_path / "plain"
    if case == "plain":
        repo.mkdir()
    elif case == "remote":
        git("remote", "add", "upstream", "https://example.invalid/x.git", cwd=repo)
    elif case == "dirty":
        (repo / "a.md").write_text("edited\n", encoding="utf-8")
    elif case == "detached":
        git("checkout", "-q", "--detach", cwd=repo)
    elif case == "refused":
        hub.refuse = Reason.REMOTE_EXISTS
    before = git("remote", cwd=repo) if case != "plain" else ""
    with pytest.raises(WorkRefused) as refused:
        make_checkout_remote(repo)
    assert refused.value.reason is reason
    assert hub.created == []
    assert case == "plain" or git("remote", cwd=repo) == before


def test_create_brain_promote_on_a_slot_is_the_door(tmp_path, monkeypatch):
    """``runtime.work.create_brain {slot, promote: true}`` reaches ``make_checkout_remote`` for the bound slot's
    checkout. Mutation: drop the ``promote`` arm in ``store.create_brain`` -> no repository is made, red."""
    from types import SimpleNamespace

    from agent_runtime.work import store

    hub = _FakeGitHub(tmp_path / "host", monkeypatch)
    repo = _project(tmp_path)
    board = SimpleNamespace(slot="app", bound_here=True, checkout=repo)
    monkeypatch.setattr(store.boards_store, "boards", lambda ws: [board])
    monkeypatch.setattr(store.boards_store, "pick", lambda boards, slot: boards[0] if slot == "app" else None)
    scope = SimpleNamespace(workspace_id="ws_app")
    answer = store.create_brain(scope, {"slot": "app", "promote": True, "request_id": "r1"}, "operator")
    assert answer["slot"] == "app" and answer["remote"]["branch"] == "feature" and hub.created == ["my-app"]


# ── RT-SLOT-BRAIN-OFFER-NAMES-REPO-AND-BRANCH: the offer says what the press would make, before it is pressed ──


@pytest.mark.parametrize("case, expected", [
    ("offered", {"state": "present", "reason": "remote_offered", "git_account": "octo", "repo_name": "my-app",
                 "branch": "feature"}),
    ("no_account", {"state": "present", "reason": "needs_git_account", "repo_name": "my-app", "branch": "feature"}),
    ("remote", {"state": "remote", "clone_url": "https://example.invalid/mine.git"}),
    ("dirty", {"state": "present", "reason": "worktree_dirty"}),
    ("detached", {"state": "present", "reason": "invalid_request"}),
    ("plain", {"state": "present", "reason": "not_a_repo"}),
])
def test_a_project_checkouts_offer_names_repo_branch_and_account_before_any_press(tmp_path, monkeypatch, case,
                                                                                   expected):
    """Each state the press would meet, read without pressing: nothing is created. Mutations (2026-11-12): drop
    ``branch`` from the offer -> ``offered`` / ``no_account`` red; answer every ``remote_exists`` as ``present``
    -> ``remote`` red."""
    from agent_runtime import git_host_account
    from agent_runtime.brain_remote import checkout_remote_state

    hub = _FakeGitHub(tmp_path / "host", monkeypatch)
    repo = _project(tmp_path) if case != "plain" else tmp_path / "plain"
    if case == "plain":
        repo.mkdir()
    elif case == "no_account":
        monkeypatch.setattr(git_host_account, "connected_github", lambda *a, **k: None)
    elif case == "remote":
        git("remote", "add", "origin", "https://example.invalid/mine.git", cwd=repo)
    elif case == "dirty":
        (repo / "a.md").write_text("edited\n", encoding="utf-8")
    elif case == "detached":
        git("checkout", "-q", "--detach", cwd=repo)
    assert checkout_remote_state(repo) == expected
    assert hub.created == []
    assert case in ("plain", "remote") or git("remote", cwd=repo) == ""


def test_capabilities_carry_each_bound_project_checkouts_offer(tmp_path, monkeypatch):
    """``capabilities.slot_brains.<ws>.<slot>``: the bound Project checkouts only — not the workspace's own
    default brain, not a slot bound on another machine. Mutation: drop the ``slot_brains`` key from
    ``_work_capabilities`` -> red."""
    from types import SimpleNamespace

    from agent_runtime.work import service
    from agent_runtime.work_store import board as boards_store

    _FakeGitHub(tmp_path / "host", monkeypatch)
    repo = _project(tmp_path)
    found = [SimpleNamespace(slot="app", is_default=False, bound_here=True, checkout=repo),
             SimpleNamespace(slot="elsewhere", is_default=False, bound_here=False, checkout=None),
             SimpleNamespace(slot="boards", is_default=True, bound_here=True, checkout=tmp_path)]
    monkeypatch.setattr(boards_store, "boards", lambda ws: found if ws == "ws_app" else [])
    monkeypatch.setattr(service, "workspace_ids", lambda: ["ws_app"])
    monkeypatch.setattr(service, "_default_brain_state", lambda ws: {"state": "present"})
    monkeypatch.setattr(service, "_personal_board_state", lambda *, observe: {"state": "present"})
    monkeypatch.setattr(service, "scopes", lambda install: [])
    caps = service._work_capabilities("inst-1")
    assert caps["slot_brains"] == {"ws_app": {"app": {
        "state": "present", "reason": "remote_offered", "git_account": "octo", "repo_name": "my-app",
        "branch": "feature"}}}
