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
from agent_runtime.workspace_slots import load_document, machine_id
from work_store_support import ISSUED, LATER, bind_here, checkout, declare_slots, slot_decl


def _git(root, *args) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout


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
        f"Eternia Harness <harness+{machine_id()}@eternia.local>|work: default brain for {workspace}")
    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert _git(root, "remote").strip() == "" and _git(root, "status", "--porcelain") == ""
    assert "brain" not in (load_document(workspace).get("slots") or {})
    assert "brain" not in workspace_slots.show(workspace)["here"]
    record = json.loads(board.binding_path(workspace).read_text(encoding="utf-8"))
    assert record == {"slot": "brain", "path": str(root), "brain_dir": "Work_Brain/20 — Active Initiatives",
                      "default_branch": "main", "created_at": ISSUED, "machine": machine_id(),
                      "remote_url": None, "retired_into": None}
    assert [b.slot for b in board.boards(workspace)] == ["brain"]
    assert not board.needs_default_brain(board.boards(workspace))


def test_ensure_is_idempotent(workspace):
    first = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    head = _git(first.read_root, "rev-parse", "HEAD")
    again = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert again == first and _git(first.read_root, "rev-parse", "HEAD") == head
    assert json.loads(board.binding_path(workspace).read_text(encoding="utf-8"))["created_at"] == ISSUED


def test_a_workspace_with_a_brain_slot_gets_none(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(workspace, hermes=checkout(tmp_path / "hermes"))
    got = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    assert got.slot == "hermes"
    assert "brain" not in load_document(workspace)["slots"]
    assert not paths.default_brain_dir(workspace).exists()


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
    ``writer_for`` over ``workspace_slots.machine_id`` — this test goes red (the patched door is bypassed)."""

    from agent_runtime.work import store as work_store

    def unidentified():
        raise workspace_slots.SlotRefused(workspace_slots.REASON_MACHINE_UNIDENTIFIED, "")

    monkeypatch.setattr(default_brain, "machine_id", unidentified)
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


def test_second_machine_with_a_local_brain_moves_its_rows_in(workspace, host, tmp_path):
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
    slots_file.write_text(declared, encoding="utf-8")
    made = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert made.slot == "brain" and made.checkout == paths.default_brain_dir(workspace).with_name("brain-remote")
    work_store.synced(workspace)
    assert _record(workspace)["retired_into"] == "brain" and _record(workspace)["moved"] == ["WORK-TWOAAA"]
    assert "WORK-TWOAAA" in _git(host.bare(name), "show", f"main:{QUEUE_NOTE_PATH}")
    assert [b.slot for b in board.boards(workspace)] == ["brain"]


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
