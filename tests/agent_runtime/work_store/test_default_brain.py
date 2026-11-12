"""The default brain: a workspace with no repo brain still gets a board (plan §4, §6.1 W1), as a
MACHINE-LOCAL binding — never a declared slot (owner ruling 2026-10-18).

Real ``git`` in the test's own store root; the machine id is this test home's install id.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agent_runtime import paths, workspace_slots
from agent_runtime.work_store import board, default_brain
from agent_runtime.work_store.grammar import is_queue
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.workspace_slots import install_id, load_document
from work_store_support import ISSUED, LATER, bind_here, checkout, declare_slots, slot_decl


def _git(root, *args) -> str:
    # git prints the notes' bytes (UTF-8 em dashes, middle dots); the locale codec (cp1252 on Windows
    # without PYTHONUTF8) turned them into mojibake the row assertions never matched.
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def test_skeleton_writes_todo_and_queue_with_frontmatter(tmp_path):
    todo, queue = default_brain.skeleton(tmp_path)
    assert todo == tmp_path / "Work_Brain" / "TODO.md"
    assert queue == tmp_path / "Work_Brain" / "20 — Active Initiatives" / "work-queue.md"
    assert todo.read_text(encoding="utf-8").startswith("---\ntype: moc\n")
    assert "work-queue" in todo.read_text(encoding="utf-8") and "```dataview" in todo.read_text(encoding="utf-8")
    text = queue.read_text(encoding="utf-8")
    assert is_queue(text) and "program: work" in text and "tags: [queue, program/work]" in text
    queue.write_text(text + "- **`WORK-AAAAAA` — kept** · READY 2026-10-18\n", encoding="utf-8")
    default_brain.skeleton(tmp_path)  # an existing note is never overwritten
    assert "WORK-AAAAAA" in queue.read_text(encoding="utf-8")


def test_ensure_default_brain_inits_commits_and_records_a_machine_local_binding(workspace):
    made = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    root = paths.default_brain_dir(workspace)
    assert made.slot == "brain" and made.is_default and made.local and made.bound_here
    assert made.read_root == root == made.checkout and made.brain_dir == "Work_Brain/20 — Active Initiatives"
    assert made.clone_url is None and made.default_branch == "main"
    assert _git(root, "log", "--format=%an <%ae>|%s").strip() == (
        f"Eternia Harness <harness+{install_id()}@eternia.local>|work: default brain for {workspace}")
    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert _git(root, "remote").strip() == "" and _git(root, "status", "--porcelain") == ""
    assert "brain" not in (load_document(workspace).get("slots") or {})
    assert "brain" not in workspace_slots.show(workspace)["here"]
    record = json.loads(board.binding_path(workspace).read_text(encoding="utf-8"))
    assert record == {"slot": "brain", "path": str(root), "brain_dir": "Work_Brain/20 — Active Initiatives",
                      "default_branch": "main", "created_at": ISSUED, "machine": install_id(),
                      "remote_url": None}
    assert [b.slot for b in board.boards(workspace)] == ["brain"]
    assert all(board.has_brain_here(b) for b in board.boards(workspace))


def test_ensure_is_idempotent(workspace):
    first = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    head = _git(first.read_root, "rev-parse", "HEAD")
    again = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert again == first and _git(first.read_root, "rev-parse", "HEAD") == head
    assert json.loads(board.binding_path(workspace).read_text(encoding="utf-8"))["created_at"] == ISSUED


def test_a_workspace_with_a_brain_slot_still_gets_its_own(workspace, tmp_path):
    """RT-WORK-WORKSPACE-BRAIN-KEPT. Mutation: restore the early return of the repo board -> got.slot is hermes, red."""
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(workspace, hermes=checkout(tmp_path / "hermes"))
    got = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    assert got.slot == "brain" and got.is_default
    assert "brain" not in load_document(workspace)["slots"]
    assert (paths.default_brain_dir(workspace) / ".git").is_dir()
    assert [b.slot for b in board.boards(workspace)] == ["hermes", "brain"]


def test_a_server_bound_realm_builds_its_brain_without_the_publish_right(monkeypatch):
    from agent_runtime.machine_roots import machine_roots_cache_clear
    from agent_runtime.realm_sync.models import MembershipDecision, RealmMembershipProvider
    from agent_runtime.store import RealmStore, WorkspaceStore

    machine_roots_cache_clear()
    realm = RealmStore().create(name="Server realm")
    gated = WorkspaceStore().create(name="In realm", realm_id=realm.id).id
    monkeypatch.setattr(RealmMembershipProvider, "authorize",
                        lambda self, realm, action: MembershipDecision(False, "membership_denied", "no credential"))
    made = default_brain.ensure_default_brain(gated, issued_at=ISSUED)
    assert made.is_default and (paths.default_brain_dir(gated) / ".git").is_dir()
    assert "brain" not in (load_document(gated).get("slots") or {})


def test_the_binding_can_carry_a_remote(workspace):
    default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    record = json.loads(board.binding_path(workspace).read_text(encoding="utf-8"))
    board.binding_path(workspace).write_text(json.dumps({**record, "remote_url": "https://example.invalid/b.git"}),
                                             encoding="utf-8")
    listed = board.default_board(workspace)
    assert listed.clone_url == "https://example.invalid/b.git" and not listed.local


def test_a_server_less_realm_gets_its_brain(monkeypatch):
    from agent_runtime.machine_roots import machine_roots_cache_clear
    from agent_runtime.store import RealmStore, WorkspaceStore

    machine_roots_cache_clear()
    realm = RealmStore().create(name="Local realm")
    local = WorkspaceStore().create(name="In local realm", realm_id=realm.id).id
    assert default_brain.ensure_default_brain(local, issued_at=ISSUED).is_default


def test_identity_pairs_are_hermes_own():
    assert default_brain.IDENTITY_PAIRS("m-1") == ("user.name=Eternia Harness", "user.email=harness+m-1@eternia.local")


def test_every_writer_refuses_an_unidentified_machine_through_this_machine(monkeypatch):
    """RT-MACHINE-ID-REFUSAL-WRAPPER: ``work.store.writer_for`` reads ``this_machine``, the one owner of the
    machine-id → ``WorkRefused(MACHINE_UNIDENTIFIED)`` wrapper. Killing mutation: re-inline the wrapper in
    ``writer_for`` over ``workspace_slots.install_id`` (the commit identity is per namespace, RT-MACHINE-ID) — this test goes red (the patched door is bypassed)."""

    from agent_runtime.work import store as work_store

    def unidentified():
        raise workspace_slots.SlotRefused(workspace_slots.REASON_MACHINE_UNIDENTIFIED, "")

    monkeypatch.setattr(default_brain, "install_id", unidentified)
    with pytest.raises(WorkRefused) as refused:
        work_store.writer_for(None)  # refused before the board is read
    assert refused.value.reason is Reason.MACHINE_UNIDENTIFIED


# ── promotion: RT-WORK-DEFAULT-BRAIN-REMOTE (p10-work §2.5) ────────────────────────────────────────
#
# A local bare repository plays GitHub: ``https://github.example/octo/<name>.git`` is rewritten to it by
# a one-process ``url.<bare dir>.insteadOf`` (GIT_CONFIG_* env), and ``connected_github`` /
# ``create_private_repo`` are faked. Nothing reaches a network or a real account.

HOST = "https://github.example/octo/"
QUEUE_NOTE_PATH = "Work_Brain/20 — Active Initiatives/work-queue.md"


class FakeHost:
    def __init__(self, root, monkeypatch) -> None:
        from agent_runtime import git_host_account

        self.root, self.created, self.connected = root, [], True
        root.mkdir()
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{root.as_posix()}/.insteadOf")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", HOST)
        monkeypatch.setattr(git_host_account, "connected_github", self.account)
        monkeypatch.setattr(git_host_account, "create_private_repo", self.create)

    def account(self, timeout=10.0):
        from agent_runtime.git_host_account import GitHubAccount

        return GitHubAccount("octo", "test") if self.connected else None

    def bare(self, name: str):
        return self.root / f"{name}.git"

    def make(self, name: str) -> None:
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare(name))], check=True)

    def create(self, account, name):
        from agent_runtime.git_host_account import GitHostRefused

        if self.bare(name).exists():
            raise GitHostRefused(Reason.REMOTE_EXISTS, f"{HOST}{name}.git")
        self.make(name)
        self.created.append(name)
        return f"{HOST}{name}.git"


@pytest.fixture
def host(tmp_path, monkeypatch) -> FakeHost:
    return FakeHost(tmp_path / "host", monkeypatch)


def _record(ws) -> dict:
    return json.loads(board.binding_path(ws).read_text(encoding="utf-8"))


def _unbind_brain(ws) -> None:
    from agent_runtime.machine_roots import load_machine_roots, write_machine_roots

    current = load_machine_roots(refresh=True)
    roots = dict(current.roots)
    roots.pop("brain", None)
    scoped = {key: dict(fills) for key, fills in current.workspace_roots.items()}
    scoped.get(ws, {}).pop("brain", None)
    write_machine_roots(roots, workspace_roots=scoped, dry_run=False)


def _commit_row(repo, row_id: str, *, push: bool) -> None:
    note = repo / QUEUE_NOTE_PATH
    note.write_text(note.read_text(encoding="utf-8") + f"- **`{row_id}` — carried** · READY 2026-10-19\n",
                    encoding="utf-8", newline="\n")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", f"row {row_id}")
    if push:
        _git(repo, "push", "-q", "origin", "HEAD:main")


def _become_a_second_machine(ws, tmp_path) -> None:
    """Drop this machine's half: the binding, the brain directory, the root and Hermes's worktrees."""

    import shutil

    board.binding_path(ws).unlink()
    paths.default_brain_dir(ws).rename(tmp_path / "machine-one-brain")
    shutil.rmtree(paths.work_workspace_dir(ws) / "worktrees", ignore_errors=True)
    _unbind_brain(ws)


def test_promotion_creates_a_private_repo_pushes_and_declares_the_slot_in_a_no_realm_workspace(workspace, host):
    declare_slots(workspace, slot_decl("tools"))  # declared, not bound here: the brain stays needed, and it survives
    made = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    root = paths.default_brain_dir(workspace)
    name = default_brain.brain_repo_name(workspace)
    assert host.created == [name] and name.startswith("eternia-work-")
    record = _record(workspace)
    assert record["remote_url"] == f"{HOST}{name}.git" and record["remote_owner"] == "octo"
    assert record["declaration"] == {"state": "declared"} and record["promoted_at"] == LATER
    assert sorted(workspace_slots.live_slots(load_document(workspace))) == ["brain", "tools"]
    slot = workspace_slots.live_slots(load_document(workspace))["brain"]
    assert slot["repo"]["clone_url"] == record["remote_url"] and slot["context"]["brain_dir"] == default_brain.QUEUE_DIR
    assert workspace_slots.bound_path("brain", workspace_id=workspace) == root
    assert board.default_board(workspace) is None
    listed = [b for b in board.boards(workspace) if b.slot == "brain"]
    assert len(listed) == 1 and board.has_brain_here(listed[0]) and not listed[0].is_default
    assert made == listed[0]
    assert _git(host.bare(name), "rev-parse", "main") == _git(root, "rev-parse", "HEAD")
    assert _git(root, "rev-parse", "--abbrev-ref", "@{u}").strip() == "origin/main"
    assert default_brain.remote_state(workspace) == {"state": "remote", "clone_url": record["remote_url"]}


def test_promotion_in_a_server_bound_realm_stages_the_declaration(workspace, host, monkeypatch):
    from agent_runtime.work import service

    def denied(ws, credential=None):
        raise workspace_slots.SlotRefused(workspace_slots.REASON_REALM_PUBLISH_DENIED, "membership_denied")

    monkeypatch.setattr(workspace_slots, "require_publish_right", denied)
    default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    record = _record(workspace)
    assert "brain" not in (load_document(workspace).get("slots") or {})
    assert record["declaration"]["state"] == "pending"
    assert record["declaration"]["slot"]["repo"]["clone_url"] == record["remote_url"]
    listed = board.default_board(workspace)
    assert listed.is_default and not listed.local and listed.clone_url == record["remote_url"]
    state = service._default_brain_state(workspace)
    assert state["state"] == "remote_pending_declare" and state["slot"]["name"] == "brain"
    # The Launcher's credentialed declare carries the entry: the next ensure binds it here.
    declare_slots(workspace, record["declaration"]["slot"], issued_at=LATER)
    assert default_brain.ensure_default_brain(workspace, issued_at=LATER).slot == "brain"
    assert _record(workspace)["declaration"] == {"state": "declared"}
    assert workspace_slots.bound_path("brain", workspace_id=workspace) == paths.default_brain_dir(workspace)
    assert [b.slot for b in board.boards(workspace)] == ["brain"]


def test_not_connected_is_a_receipt_and_the_brain_stays_local(workspace, host, caplog):
    import logging

    host.connected = False
    made = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    assert made.is_default and made.local and host.created == []
    assert default_brain.remote_state(workspace) == {"state": "present", "reason": "needs_git_account"}
    caplog.set_level(logging.INFO, logger="agent_runtime.work_store.receipts")
    with pytest.raises(WorkRefused) as refused:
        default_brain.promote_default_brain(workspace, issued_at=LATER)
    assert refused.value.reason is Reason.NEEDS_GIT_ACCOUNT
    assert "work.brain_promote_refused" in caplog.text and "needs_git_account" in caplog.text
    assert "promote_refused" not in _record(workspace)  # nothing to back off from


def test_remote_exists_is_refused_never_adopted(workspace, host):
    host.make(default_brain.brain_repo_name(workspace))
    made = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    assert made.is_default and host.created == []
    root = paths.default_brain_dir(workspace)
    assert subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True,
                          check=False).returncode != 0
    assert _record(workspace)["promote_refused"]["reason"] == "remote_exists"
    state = default_brain.remote_state(workspace)
    assert state["state"] == "remote_refused" and state["reason"] == "remote_exists"
    assert state["retry_after"].startswith("2026-10-19T12:00:00")


def test_a_refusal_backs_off_for_a_day_and_the_manual_door_ignores_it(workspace, host, monkeypatch):
    import shutil

    name = default_brain.brain_repo_name(workspace)
    host.make(name)
    now = workspace_slots.stamp_epoch(ISSUED)
    monkeypatch.setattr(default_brain.time, "time", lambda: now + 3600)
    default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    shutil.rmtree(host.bare(name))
    default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert host.created == [] and not _record(workspace).get("remote_url")  # backing off
    promoted = default_brain.promote_default_brain(workspace, issued_at=LATER)
    assert promoted["outcome"] == "promoted" and host.created == [name]
    assert _record(workspace)["promote_refused"] is None
    monkeypatch.setattr(default_brain.time, "time", lambda: now + default_brain.PROMOTE_RETRY_S + 1)
    assert not default_brain._refused_recently({"promote_refused": {"reason": "x", "at": ISSUED}})


def test_second_machine_adopts_the_declared_remote_instead_of_creating_a_brain(workspace, host, tmp_path):
    default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    url = _record(workspace)["remote_url"]
    _commit_row(paths.default_brain_dir(workspace), "WORK-ONEAAA", push=True)
    _become_a_second_machine(workspace, tmp_path)
    made = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    root = paths.default_brain_dir(workspace)
    assert made.slot == "brain" and not made.is_default and workspace_slots.bound_path("brain", workspace_id=workspace) == root
    assert host.created == [default_brain.brain_repo_name(workspace)]  # no second repo
    assert _git(root, "config", "--get", "remote.origin.url").strip() == url
    assert "work: default brain" not in _git(root, "log", "-1", "--format=%s")
    assert len(_git(root, "rev-list", "HEAD").split()) == 2  # machine one's two commits, nothing new
    assert not board.binding_path(workspace).exists()
    assert "WORK-ONEAAA" in board.ids_in_brain(made)


def test_second_machine_with_a_local_brain_folds_its_rows_into_the_adopted_brain(workspace, host, tmp_path):
    """RT-WORK-ADOPTED-BRAIN-BESIDE-LOCAL: a machine that made its own local brain before the declaration synced
    in folds the local rows into the adopted ``brain`` once, in ONE commit, IDs kept; one ``brain`` board is
    listed after. Killing mutation: ``_adopt_declared_brain`` returning the declared board without
    ``_fold_local_brain`` — two ``brain`` boards, ``WORK-TWOAAA`` never reaches the remote."""
    from agent_runtime.work import store as work_store

    default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    name = default_brain.brain_repo_name(workspace)
    _become_a_second_machine(workspace, tmp_path)
    slots_file = paths.workspace_slots_path(workspace)
    declared = slots_file.read_text(encoding="utf-8")
    slots_file.unlink()  # this machine made its own local brain before the declaration synced in
    host.connected = False
    local = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    assert local.is_default and local.local
    _commit_row(local.checkout, "WORK-TWOAAA", push=False)
    _commit_row(local.checkout, "WORK-TWOBBB", push=False)
    slots_file.write_text(declared, encoding="utf-8")
    before = len(_git(host.bare(name), "rev-list", "main").split())
    made = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert made.slot == "brain" and not made.is_default
    assert made.checkout == paths.default_brain_dir(workspace).with_name("brain-remote")
    remote = _git(host.bare(name), "show", f"main:{QUEUE_NOTE_PATH}")
    assert "- **`WORK-TWOAAA` — carried** · READY 2026-10-19" in remote and "`WORK-TWOBBB`" in remote
    assert len(_git(host.bare(name), "rev-list", "main").split()) == before + 1  # one commit
    assert [b.is_default for b in board.boards(workspace)] == [False]
    record = _record(workspace)
    assert record["folded_into"] == record["remote_url"] and record["declaration"] == {"state": "declared"}
    work_store.synced(workspace)
    again = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert again.checkout == made.checkout and len(board.boards(workspace)) == 1
    assert len(_git(host.bare(name), "rev-list", "main").split()) == before + 1  # folded once


def test_a_fold_that_clashes_keeps_both_boards_and_backs_off(workspace, host, tmp_path):
    """An ID already in the adopted brain refuses the fold whole: both boards stay listed, no row lost."""

    made = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    name = default_brain.brain_repo_name(workspace)
    _commit_row(made.checkout, "WORK-SAMEAA", push=True)
    _become_a_second_machine(workspace, tmp_path)
    slots_file = paths.workspace_slots_path(workspace)
    declared = slots_file.read_text(encoding="utf-8")
    slots_file.unlink()
    host.connected = False
    local = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    _commit_row(local.checkout, "WORK-SAMEAA", push=False)
    slots_file.write_text(declared, encoding="utf-8")
    default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert [b.is_default for b in board.boards(workspace)] == [False, True]
    assert _record(workspace)["fold_refused"]["reason"] == "id_exists"
    assert "WORK-SAMEAA" in board.ids_in_brain(board.default_board(workspace))
    assert _git(host.bare(name), "show", f"main:{QUEUE_NOTE_PATH}").count("`WORK-SAMEAA`") == 1


def test_the_writer_pushes_to_the_promoted_brain(workspace, host):
    from agent_runtime.work import store as work_store
    from agent_runtime.work_store.grammar import Op, RowRef
    from agent_runtime.work_store.writer import OPERATOR, RowOp

    made = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    raw = "- **`WORK-PUSHAA` — pushed** · READY 2026-10-19"
    receipt = work_store.writer_for(made).apply(RowOp(RowRef("brain", QUEUE_NOTE_PATH, "WORK-PUSHAA"), Op.APPEND,
                                                      OPERATOR, "req-push-1", {"rows": [raw], "files": {}}))
    assert receipt.pushed
    assert "WORK-PUSHAA" in _git(host.bare(default_brain.brain_repo_name(workspace)), "show", f"main:{QUEUE_NOTE_PATH}")


def test_create_brain_promote_is_the_manual_door(workspace, host):
    from types import SimpleNamespace

    from agent_runtime.work import store as work_store

    host.connected = False
    default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    scope = SimpleNamespace(workspace_id=workspace)
    with pytest.raises(WorkRefused) as refused:
        work_store.create_brain(scope, {"request_id": "r-1", "promote": True}, "operator")
    assert refused.value.reason is Reason.NEEDS_GIT_ACCOUNT
    host.connected = True
    reply = work_store.create_brain(scope, {"request_id": "r-2", "promote": True}, "operator")
    assert reply["promotion"]["outcome"] == "promoted" and reply["promotion"]["declaration"] == {"state": "declared"}
    assert reply["board"]["slot"] == "brain" and reply["receipt"]["promote"] is True
    again = work_store.create_brain(scope, {"request_id": "r-3", "promote": True}, "operator")
    assert again["promotion"]["outcome"] == "already"


def test_two_workspaces_promoting_keep_their_own_brain(workspace, host):
    """RT-SLOT-ROOT-NAME-GLOBAL (plan work-slot-roots-per-workspace-2026-10-21 R4): each promotion binds slot
    ``brain`` for its own workspace. Killing mutation: ``bind`` writing the global ``roots.brain`` — the second
    promotion repoints the first workspace's board at the second workspace's brain."""

    from agent_runtime.store import WorkspaceStore

    other = WorkspaceStore().create(name="Second workspace").id
    default_brain.ensure_default_brain(workspace, issued_at=LATER)
    default_brain.ensure_default_brain(other, issued_at=LATER)
    assert len(host.created) == 2
    for ws in (workspace, other):
        assert _record(ws)["declaration"] == {"state": "declared"}
        assert workspace_slots.bound_path("brain", workspace_id=ws) == paths.default_brain_dir(ws)
        (declared,) = [b for b in board.declared_boards(ws) if b.slot == "brain"]
        assert declared.read_root == paths.default_brain_dir(ws) and board.has_brain_here(declared)
        assert board.default_board(ws) is None


def _leave_a_connected_realm(ws, host) -> tuple[str, object, str, str]:
    """The brain promoted to the team's repository (two repositories), its realm then left through
    ``make_realm_local``: ``(team url, team bare repo, brain HEAD, team tip)`` as they were before the leave."""
    from agent_runtime.realm_leave import make_realm_local
    from agent_runtime.realm_sync.revocation import RealmRevokedReason
    from agent_runtime.store import RealmStore, WorkspaceStore

    default_brain.ensure_default_brain(ws, issued_at=ISSUED)
    url = _record(ws)["remote_url"]
    team = host.bare(default_brain.brain_repo_name(ws))
    root = paths.default_brain_dir(ws)
    realm = RealmStore().create(name="Team", server_id="srv_team")
    item = WorkspaceStore().get(ws)
    item.realm_id = realm.id
    WorkspaceStore().save(item)
    realm = RealmStore().get(realm.id)
    realm.workspace_ids = [ws]
    RealmStore().save(realm)
    history, team_tip = _git(root, "rev-parse", "HEAD"), _git(team, "rev-parse", "main")
    assert make_realm_local(realm.id, RealmRevokedReason.MEMBERSHIP_LEFT)[1] is True
    return url, team, history, team_tip


def test_a_left_realms_promoted_brain_pushes_nowhere(workspace, host):
    """RT-LEFT-REALM-BRAIN-STILL-PUSHES-TO-THE-TEAM. A workspace brain promoted to the team's shared task repository
    kept that repository as its remote after the member left the server (``make_realm_local`` dropped only the
    realm's own sync address), so Work written in the local copy was pushed to the team. Through
    ``make_realm_local``, with two repositories (the brain, the team's): the brain loses the remote and keeps its
    history, the declared slot ``brain`` is tombstoned, the board is the local default board, and a Work write
    commits here and leaves the team's repository where it was.

    Mutation: skip the ``remote remove`` in ``detach_left_remote`` -> the brain still names the team's
    repository as ``origin``, red; drop ``_detach_brains`` from ``make_realm_local`` -> the same, red (both
    recorded in the commit)."""
    from agent_runtime.work import store as work_store
    from agent_runtime.work_store.grammar import Op, RowRef
    from agent_runtime.work_store.writer import OPERATOR, RowOp

    url, team, history, team_tip = _leave_a_connected_realm(workspace, host)
    root = paths.default_brain_dir(workspace)

    assert _git(root, "remote").strip() == ""
    assert _git(root, "rev-parse", "HEAD") == history
    record = _record(workspace)
    assert (record["remote_url"], record["declaration"]) == (None, None)
    assert record["left_remote"]["url"] == url
    assert "brain" not in workspace_slots.live_slots(load_document(workspace))
    [listed] = [b for b in board.boards(workspace) if b.slot == "brain"]
    assert listed.is_default and listed.local and listed.clone_url is None
    raw = "- **`WORK-LOCALA` — written in the local copy** · READY 2026-11-12"
    receipt = work_store.writer_for(listed).apply(RowOp(RowRef("brain", QUEUE_NOTE_PATH, "WORK-LOCALA"), Op.APPEND,
                                                        OPERATOR, "req-left-1", {"rows": [raw], "files": {}}))
    assert receipt.pushed is False
    assert "WORK-LOCALA" in _git(root, "show", f"main:{QUEUE_NOTE_PATH}")
    assert _git(team, "rev-parse", "main") == team_tip
    assert default_brain.detach_left_remote(workspace, at=LATER) is None  # a replay finds nothing to let go


def test_a_left_realms_brain_stays_local_until_the_member_promotes_it(workspace, host, tmp_path):
    """RT-LEFT-REALM-BRAIN-PROMOTED-AGAIN-BEFORE-ITS-REKEY (owner 2026-11-12: "yes stay local because its related
    to the team its irreelvant to you alone"). After a leave on a connected machine (two repositories), the next
    ``ensure_default_brain`` used to promote the copy's brain to a private ``eternia-work-<slug>``: refused
    ``remote_exists`` every day on the account that made the team's repository, a new repository on any other.
    Now neither: the brain stays local, nothing is created or refused. The manual door still promotes it and
    clears the hold, and the automatic path then leaves the promoted brain alone.

    Mutation: drop the ``left_remote`` hold in ``_auto_promote`` -> the first ensure records ``promote_refused``
    ``remote_exists`` (the team's account) and, with the team's repository gone from this account, the second
    creates a new repository: red (seen: ``promote_refused`` ``remote_exists``). Keep ``left_remote`` on a manual
    promote -> red (seen: the hold still set after the promotion)."""
    url, team, _, team_tip = _leave_a_connected_realm(workspace, host)
    name = default_brain.brain_repo_name(workspace)
    assert host.created == [name]

    made = default_brain.ensure_default_brain(workspace, issued_at=LATER)  # the account that made the team's repo
    assert made.is_default and made.local and made.clone_url is None
    record = _record(workspace)
    assert record["left_remote"]["url"] == url and not record.get("remote_url")
    assert not record.get("promote_refused")
    assert default_brain.remote_state(workspace) is None
    team.rename(tmp_path / "team-elsewhere.git")  # any other account: the name is free there
    default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert host.created == [name] and not _record(workspace).get("remote_url")

    promoted = default_brain.promote_default_brain(workspace, issued_at=LATER)  # the member asks
    assert promoted["outcome"] == "promoted" and host.created == [name, name]
    record = _record(workspace)
    assert record["remote_url"] == promoted["url"] and record["left_remote"] is None
    assert _git(tmp_path / "team-elsewhere.git", "rev-parse", "main") == team_tip  # the team's copy untouched
    assert default_brain.ensure_default_brain(workspace, issued_at=LATER).slot == "brain"
    assert host.created == [name, name]
