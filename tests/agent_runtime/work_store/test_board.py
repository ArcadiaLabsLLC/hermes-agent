"""A workspace's boards: one per live slot, rows read from the bound checkout's brain (plan §2, §6.1)."""

from __future__ import annotations

from agent_runtime.work_store import board
from agent_runtime.work_store.grammar import Status
from work_store_support import bind_here, checkout, declare_slots, slot_decl

ROWS = (
    "- **`RT-A` — ready** · READY 2026-10-18\n"
    "- **`RT-B` — taken** · READY 2026-10-18 · **TAKEN 2026-10-18 persona:pi_1**\n"
    "- **`RT-C` — assigned** · assignee: persona:alice · BLOCKED 2026-10-18: owner sitting — the box\n"
)


def test_boards_one_per_live_bound_slot_with_brain_dir_discovered(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes"), slot_decl("launcher"))
    bind_here(workspace, hermes=checkout(tmp_path / "hermes", rows=ROWS), launcher=checkout(tmp_path / "launcher", brain="Launcher_Brain"))
    found = {b.slot: b for b in board.boards(workspace)}
    assert sorted(found) == ["hermes", "launcher"]
    assert found["hermes"].brain_dir == "Harness_Brain/20 — Active Initiatives"
    assert found["launcher"].brain_dir == "Launcher_Brain/20 — Active Initiatives"
    assert found["hermes"].bound_here and not found["hermes"].local and not found["hermes"].is_default
    assert [p.name for p in board.notes(found["hermes"])] == ["q.md"]  # the moc note is not a queue
    assert not board.needs_default_brain(list(found.values()))


def test_pinned_brain_dir_wins_over_discovery(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes", brain_dir="Pinned_Brain/20 — Active Initiatives"))
    root = checkout(tmp_path / "hermes", rows=ROWS)
    checkout(root, brain="Pinned_Brain", rows="- **`PIN-1` — pinned** · READY 2026-10-18\n")
    bind_here(workspace, hermes=root)
    (only,) = board.boards(workspace)
    assert only.brain_dir == "Pinned_Brain/20 — Active Initiatives"
    assert [r.ref.id for r in board.rows(workspace)] == ["PIN-1"]


def test_a_slot_without_a_brain_lists_as_no_brain(workspace, tmp_path):
    declare_slots(workspace, slot_decl("thirdparty"))
    bind_here(workspace, thirdparty=checkout(tmp_path / "thirdparty", brain=None))
    (only,) = board.boards(workspace)
    assert only.bound_here and only.brain_dir is None
    assert board.notes(only) == [] and board.rows(workspace) == []
    assert board.needs_default_brain([only])


def test_rows_keyed_slot_id_never_collide_across_repos(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes"), slot_decl("launcher"))
    bind_here(workspace, hermes=checkout(tmp_path / "hermes", rows=ROWS),
              launcher=checkout(tmp_path / "launcher", brain="Launcher_Brain", rows=ROWS))
    keys = [(r.ref.slot, r.ref.id) for r in board.rows(workspace)]
    assert len(keys) == len(set(keys)) == 6
    assert {r.ref.slot for r in board.rows(workspace) if r.ref.id == "RT-A"} == {"hermes", "launcher"}
    (row,) = board.rows(workspace, slot="hermes", assignee="alice")
    assert row.ref.id == "RT-C"
    assert row.ref.note == "Harness_Brain/20 — Active Initiatives/q.md" and row.heading == "Open"
    assert [r.ref.id for r in board.rows(workspace, status=Status.BLOCKED, slot="launcher")] == ["RT-C"]
    assert board.ids_in_brain(board.boards(workspace)[0]) == {"RT-A", "RT-B", "RT-C"}


def test_ready_excludes_taken(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes"))
    bind_here(workspace, hermes=checkout(tmp_path / "hermes", rows=ROWS))
    assert [r.ref.id for r in board.ready(workspace)] == ["RT-A"]


def test_unbound_slot_is_listed_not_read(workspace, tmp_path):
    declare_slots(workspace, slot_decl("hermes"))
    (only,) = board.boards(workspace)
    assert not only.bound_here and only.read_root is None and only.brain_dir is None
    assert board.rows(workspace) == [] and board.needs_default_brain([only])
    # W2 reads through hermes's own worktree: a read root makes the slot readable.
    worktree = checkout(tmp_path / "worktree", rows=ROWS)
    assert [r.ref.id for r in board.rows(workspace, read_roots={"hermes": worktree})] == ["RT-A", "RT-B", "RT-C"]
