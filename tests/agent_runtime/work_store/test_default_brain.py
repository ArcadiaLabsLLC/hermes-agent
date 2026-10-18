"""The default brain: a workspace with no repo brain still gets a board (plan §4, §6.1 W1).

Real ``git`` in the test's own store root; the machine id is this test home's install id.
"""

from __future__ import annotations

import subprocess

import pytest

from agent_runtime import paths, workspace_slots
from agent_runtime.work_store import board, default_brain
from agent_runtime.work_store.grammar import is_queue
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.workspace_slots import declare_local_slot, live_slots, load_document, machine_id
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


def test_ensure_default_brain_inits_commits_declares_and_binds(workspace):
    made = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    root = paths.default_brain_dir(workspace)
    assert made.slot == "brain" and made.is_default and made.local and made.bound_here
    assert made.read_root == root and made.brain_dir == "Work_Brain/20 — Active Initiatives"
    assert made.clone_url is None and made.default_branch == "main"
    assert _git(root, "log", "--format=%an <%ae>|%s").strip() == (
        f"Eternia Harness <harness+{machine_id()}@eternia.local>|work: default brain for {workspace}")
    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert _git(root, "remote").strip() == "" and _git(root, "status", "--porcelain") == ""
    slot = live_slots(load_document(workspace))["brain"]
    assert slot["repo"] == {"clone_url": None, "default_branch": "main", "local": True}
    assert slot["context"]["role"] == "brain" and slot["declared_by_machine"] == machine_id()
    here = workspace_slots.show(workspace)["here"]["brain"]
    assert here["bound_here"] and here["path"] == str(root)
    report = load_document(workspace)["machines"][machine_id()]["slots"]["brain"]
    assert report["checkout"] == "local" and report["status"] == "ready"
    assert not board.needs_default_brain(board.boards(workspace))


def test_ensure_is_idempotent(workspace):
    first = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    head = _git(first.read_root, "rev-parse", "HEAD")
    again = default_brain.ensure_default_brain(workspace, issued_at=LATER)
    assert again == first and _git(first.read_root, "rev-parse", "HEAD") == head
    assert load_document(workspace)["slots"]["brain"]["issued_at"] == ISSUED


def test_a_workspace_with_a_brain_slot_gets_none(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(hermes=checkout(tmp_path / "hermes"))
    got = default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    assert got.slot == "hermes"
    assert "brain" not in load_document(workspace)["slots"]
    assert not paths.default_brain_dir(workspace).exists()


def test_declare_local_slot_keeps_the_other_slots(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes"), slot_decl("launcher"))
    before = load_document(workspace)
    target = tmp_path / "local"
    target.mkdir()
    declare_local_slot(workspace, "brain", path=str(target), issued_at=LATER, machine="m1")
    after = load_document(workspace)
    assert sorted(live_slots(after)) == ["brain", "hermes", "launcher"]
    assert {k: after["slots"][k] for k in ("hermes", "launcher")} == {k: before["slots"][k] for k in ("hermes", "launcher")}
    # The document's declare stamp is untouched: an operator declare stamped between the two is not stale.
    assert after["issued_at"] == before["issued_at"] == ISSUED
    with pytest.raises(workspace_slots.SlotRefused) as bad:
        declare_local_slot(workspace, "no-dash", path=str(target), issued_at=LATER, machine="m1")
    assert bad.value.reason == "invalid_slot_name"


def test_server_bound_realm_without_credential_refuses_needs_publish_right(monkeypatch):
    from agent_runtime.machine_roots import machine_roots_cache_clear
    from agent_runtime.realm_sync.models import MembershipDecision, RealmMembershipProvider
    from agent_runtime.store import RealmStore, WorkspaceStore

    machine_roots_cache_clear()
    realm = RealmStore().create(name="Server realm")
    gated = WorkspaceStore().create(name="In realm", realm_id=realm.id).id
    monkeypatch.setattr(RealmMembershipProvider, "authorize",
                        lambda self, realm, action: MembershipDecision(False, "membership_denied", "no credential"))
    with pytest.raises(WorkRefused) as refused:
        default_brain.ensure_default_brain(gated, issued_at=ISSUED)
    assert refused.value.reason is Reason.NEEDS_PUBLISH_RIGHT
    assert "brain" not in load_document(gated)["slots"]
    assert not paths.default_brain_dir(gated).exists()


def test_a_server_less_realm_gets_its_brain(monkeypatch):
    from agent_runtime.machine_roots import machine_roots_cache_clear
    from agent_runtime.store import RealmStore, WorkspaceStore

    machine_roots_cache_clear()
    realm = RealmStore().create(name="Local realm")
    local = WorkspaceStore().create(name="In local realm", realm_id=realm.id).id
    assert default_brain.ensure_default_brain(local, issued_at=ISSUED).is_default


def test_git_switched_off_refuses_git_unavailable(workspace, monkeypatch):
    from agent_runtime import loop_tool_lifecycles

    monkeypatch.setattr(loop_tool_lifecycles, "shipped", lambda module: module != "agent_runtime.git_cmd")
    with pytest.raises(WorkRefused) as refused:
        default_brain.ensure_default_brain(workspace, issued_at=ISSUED)
    assert refused.value.reason is Reason.GIT_UNAVAILABLE


def test_identity_pairs_are_hermes_own():
    assert default_brain.IDENTITY_PAIRS("m-1") == ("user.name=Eternia Harness", "user.email=harness+m-1@eternia.local")
