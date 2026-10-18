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
    bind_here(hermes=checkout(tmp_path / "hermes"))
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


def test_promote_default_brain_is_not_built_and_the_binding_can_carry_a_remote(workspace):
    default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    with pytest.raises(WorkRefused) as refused:
        default_brain.promote_default_brain(workspace, remote_url="https://example.invalid/brain.git")
    assert refused.value.reason is Reason.NOT_BUILT and "RT-WORK-DEFAULT-BRAIN-REMOTE" in refused.value.detail
    record = json.loads(board.binding_path(workspace).read_text(encoding="utf-8"))
    board.binding_path(workspace).write_text(json.dumps({**record, "remote_url": "https://example.invalid/b.git"}),
                                             encoding="utf-8")
    assert board.default_board(workspace).clone_url == "https://example.invalid/b.git"


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
