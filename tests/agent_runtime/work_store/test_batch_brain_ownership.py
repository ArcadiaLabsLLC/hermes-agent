"""Real Git: retained workspace brains and existing repo batches share one dispatcher."""
from dataclasses import replace

import pytest

from agent_runtime.batch.board_source import BoardSource
from agent_runtime.batch.dispatcher import BatchDispatcher
from agent_runtime.batch.machine import LaneState
from agent_runtime.batch.manifest import BrainManifestStore, held_refs, manifest_path
from agent_runtime.batch.planner import Member
from agent_runtime.work.store import synced
from agent_runtime.work_store.default_brain import ensure_default_brain
from agent_runtime.work_store.grammar import Op, RowRef
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.writer import RowOp, Writer
from agent_runtime.workspace_slots import machine_id
from tests.agent_runtime.persona_instance_mint import mint_free_floating
from batch_support import WS, FakeManifests, dispatcher, qrow
from contract_fakes import FakeExecutor, FakeSource
from test_writer import repo


def test_start_reads_own_brain_and_preserves_existing_repo_manifests(repo):
    """Mutation: read only the first repo brain -> start raises batch_missing."""
    own = ensure_default_brain(repo.ws, issued_at="2026-11-03T12:00:00+00:00")
    alice = mint_free_floating("alice")
    old_store = FakeManifests()
    old = dispatcher(FakeSource([qrow("RT-LEGACY", assignee="inst-a")]), manifests=old_store,
                     roster=[Member("inst-a", "alice", "worker")])
    legacy = old.start(WS, old.plan(WS).id)
    legacy_text = old_store.notes[WS][legacy.id]
    writer = Writer(repo.board, machine_id=machine_id())
    relative = manifest_path(legacy.id)
    writer.apply(RowOp(RowRef(repo.board.slot, f"Harness_Brain/{relative}", legacy.id), Op.APPEND,
                       "operator", "legacy-manifest", {"files": {relative: legacy_text}}))

    executor, manifests = FakeExecutor(), BrainManifestStore()
    d = BatchDispatcher(source_for=BoardSource, manifests=manifests, executor=executor, machine=machine_id,
                        roster=lambda _ws: [Member(alice.id, alice.persona_id, alice.role)],
                        workspaces=lambda: [repo.ws])
    executor.on_settle(d.settled)
    planned = d.plan(repo.ws)
    started = d.start(repo.ws, planned.id, personas={lane: alice.id for lane in planned.asks})
    assert any(lane.state is LaneState.RUNNING for lane in started.lanes)
    assert {legacy.id, started.id} <= manifests.texts(repo.ws).keys()
    view = synced(repo.ws)
    own_root = view.read_roots[own.key] / "Work_Brain"
    assert (own_root / manifest_path(started.id)).is_file()
    assert not (own_root / relative).exists()
    expected = {ref for lane in started.lanes for ref in lane.rows} | {legacy.lanes[0].rows[0]}
    assert expected <= held_refs(repo.ws, view)

    # Appending an older batch stays in its original brain, without migration
    # or hiding its claims when the workspace now also has its own brain.
    manifests.append(repo.ws, legacy.id, ["- legacy continuation"], "legacy-continue")
    assert "legacy continuation" in manifests.texts(repo.ws)[legacy.id]
    assert not (own_root / relative).exists()
    assert "legacy continuation" in (writer.worktree / "Harness_Brain" / relative).read_text(encoding="utf-8")

    # Duplicate identities across brains cannot silently redirect a write.
    duplicate = Writer(replace(own, read_root=view.read_roots[own.key]), machine_id=machine_id())
    duplicate.apply(RowOp(RowRef(own.slot, f"Work_Brain/{relative}", legacy.id), Op.APPEND,
                          "operator", "duplicate-manifest", {"files": {relative: legacy_text}}))
    with pytest.raises(WorkRefused) as refused:
        manifests.append(repo.ws, legacy.id, ["- ambiguous"], "ambiguous-manifest")
    assert refused.value.reason is Reason.CONFLICT
