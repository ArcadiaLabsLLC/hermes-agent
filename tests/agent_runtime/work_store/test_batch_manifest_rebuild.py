"""Nothing hidden (dispatcher plan §3.4): a batch is rebuilt from its manifest note and its rows' claim
marks alone, the manifest lives in the workspace's default brain, written through the W2 writer.

Killing mutation (plan §6 B2): ``BatchDispatcher._run`` stops appending the lane's ``RUNNING`` line →
``test_rebuild_from_manifest_and_rows`` red (the rebuilt lane reads ``CLAIMED`` and a second dispatcher
would start it again).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_runtime import paths
from agent_runtime.batch.board_source import BoardSource
from agent_runtime.batch.dispatcher import BatchDispatcher
from agent_runtime.batch.machine import BatchState, LaneState
from agent_runtime.batch.manifest import (
    BATCHES_DIR, BrainManifestStore, entry_line, fold, held_refs, manifest_path, parse,
)
from agent_runtime.batch.planner import Member
from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.machine_roots import machine_roots_cache_clear
from agent_runtime.store import WorkspaceStore
from agent_runtime.work import service
from agent_runtime.work.store import synced
from agent_runtime.work_store.board import Board
from agent_runtime.work_store.engine import WorkEngine
from agent_runtime.work_store.executor import Outcome, RunStatus, Verdict
from agent_runtime.work_store.grammar import RowRef
from agent_runtime.workspace_slots import machine_id
from tests.agent_runtime.persona_instance_mint import mint_free_floating

from batch_support import WS, FakeManifests, dispatcher, qrow
from contract_fakes import FakeExecutor, FakeSource

ROSTER = [Member("inst-a", "alice", "engineer")]


def test_line_round_trip_escapes_a_backtick():
    line = entry_line("2026-10-18T12:00:00+00:00", "lane L1", "CLAIMED", {"note": "a `code` span", "rows": []})
    assert line.count("`") == 2
    (entry,) = parse(line)
    assert (entry.subject, entry.word, entry.data["note"]) == ("lane L1", "CLAIMED", "a `code` span")


def test_rebuild_from_manifest_and_rows():
    source, manifests = FakeSource([qrow("RT-A", assignee="inst-a"), qrow("RT-B", heading="Seams", assignee="inst-a")]), \
        FakeManifests()
    first = dispatcher(source, manifests=manifests, roster=ROSTER)
    batch = first.start(WS, first.plan(WS).id)
    first.executor.settle(f"{batch.id}:L1", Outcome(Verdict.DONE))
    before = first.load(WS, batch.id)

    later = FakeExecutor()
    rebuilt = dispatcher(source, manifests=manifests, executor=later, roster=ROSTER)
    after = rebuilt.load(WS, batch.id)
    assert after == before
    assert [(lane.id, lane.state) for lane in after.lanes] == [("L1", LaneState.REPORTED), ("L2", LaneState.RUNNING)]
    assert after.lanes[1].run_id == f"run-{batch.id}:L2"
    rebuilt.tick()
    assert later.runs == {}, "a rebuilt dispatcher never starts a lane the manifest says is running"
    marks = rebuilt.status(WS, batch.id)["batches"][0]["marks"]
    assert marks == {"hermes/RT-A": "gone", "hermes/RT-B": "persona:inst-a"}
    assert fold(manifests.notes[WS][batch.id]) == before


def _view_over(root: Path, text: str, batch_id: str) -> SimpleNamespace:
    brain = root / "Harness_Brain"
    (brain / BATCHES_DIR).mkdir(parents=True)
    (brain / manifest_path(batch_id)).write_text(text, encoding="utf-8")
    (brain / "20 — Active Initiatives").mkdir(parents=True)
    board = Board(WS, "hermes", root, "Harness_Brain/20 — Active Initiatives", "main", None, False, True, False, root)
    return SimpleNamespace(boards=[board], read_roots={"hermes": root})


def test_held_refs_names_the_rows_of_live_lanes_only(tmp_path):
    source, manifests = FakeSource([qrow("RT-A", assignee="inst-a"), qrow("RT-B", heading="Seams", assignee="inst-a")]), \
        FakeManifests()
    d = dispatcher(source, manifests=manifests, roster=ROSTER)
    batch = d.start(WS, d.plan(WS).id)
    d.executor.settle(f"{batch.id}:L1", Outcome(Verdict.DONE))
    view = _view_over(tmp_path, manifests.notes[WS][batch.id], batch.id)
    assert held_refs(WS, view) == {batch.lanes[1].rows[0]}


def test_the_engine_skips_a_row_a_batch_lane_holds(tmp_path):
    queue = tmp_path / "Harness_Brain" / "20 — Active Initiatives"
    queue.mkdir(parents=True)
    (queue / "q.md").write_text("---\ntype: queue\n---\n\n## Open\n\n"
                                "- **`RT-A` — a** · READY 2026-10-18 · **TAKEN 2026-10-18 persona:inst-a**\n",
                                encoding="utf-8")
    board = Board("ws-e", "hermes", tmp_path, "Harness_Brain/20 — Active Initiatives", "main", None, False, True, False,
                  tmp_path)
    view = SimpleNamespace(boards=[board], writers={"hermes": SimpleNamespace(worktree=tmp_path)},
                           read_roots={"hermes": tmp_path})
    ref = RowRef("hermes", "Harness_Brain/20 — Active Initiatives/q.md", "RT-A")
    for held, started in ((set(), 1), ({ref}, 0)):
        executor = FakeExecutor()
        engine = WorkEngine(executor=executor, sync=lambda _ws: view, workspaces=lambda: ["ws-e"],
                            held=lambda _ws, _view, held=held: held)
        engine.tick()
        assert len(executor.runs) == started
        for path in paths.work_runs_dir("ws-e").glob("*.json"):
            path.unlink()


def test_the_manifest_lives_in_the_default_brain_through_the_writer():
    machine_roots_cache_clear()
    ws = WorkspaceStore().create(name="Desk").id
    surface = paths.office_surface_path(ws)
    surface.parent.mkdir(parents=True, exist_ok=True)
    surface.write_text("{}", encoding="utf-8")
    ensure_install_identity(paths.store_root())
    caps = service.execute("capabilities", {}, STDIO_OWNER)
    assert caps["default_brain"][ws]["state"] == "created"
    owner = next(row["owner"] for row in caps["owners"] if row["workspace_id"] == ws)
    alice = mint_free_floating("alice")
    for i, title in enumerate(("Review", "Ship")):
        service.execute("start", {"install_id": caps["install_id"], "owner": owner, "request_id": f"r{i}",
                                  "title": title, "assignee": f"persona:{alice.id}"}, STDIO_OWNER)
    executor, manifests = FakeExecutor(), BrainManifestStore()
    d = BatchDispatcher(source_for=BoardSource, manifests=manifests, executor=executor, machine=machine_id,
                        roster=lambda _ws: [Member(alice.id, alice.persona_id, alice.role)],
                        workspaces=lambda: [ws])
    executor.on_settle(d.settled)
    batch = d.start(ws, d.plan(ws).id)
    assert [lane.state for lane in batch.lanes] == [LaneState.RUNNING]
    view = synced(ws)
    brain = view.read_roots["brain"] / "Work_Brain"
    text = (brain / manifest_path(batch.id)).read_text(encoding="utf-8")
    assert text.startswith("---\ntype: batch\n") and f"owner_machine: {machine_id()}" in text
    assert (brain / BATCHES_DIR / batch.id / "L1.md").is_file()
    rows = [row for board in view.boards for row in BoardSource(ws).rows(ws, slot=board.slot)]
    assert {row.taken.who for row in rows} == {f"persona:{alice.id}"}
    assert held_refs(ws, view) == {row.ref for row in rows}
    manifests.append(ws, batch.id, ["- replayed line"], f"{batch.id}:L1:running")
    assert "replayed line" not in (synced(ws).read_roots["brain"] / "Work_Brain" / manifest_path(batch.id)).read_text(
        encoding="utf-8"), "a repeated request id is a replay"
    executor.statuses[batch.lanes[0].run_id] = RunStatus.RUNNING
    executor.settle(f"{batch.id}:L1", Outcome(Verdict.DONE))
    assert BoardSource(ws).rows(ws) == []
    landed = d.load(ws, batch.id)
    assert landed.state is BatchState.READY_TO_LAND and landed.lanes[0].done_rows == 2
    lines = [entry.word for entry in parse((synced(ws).read_roots["brain"] / "Work_Brain" /
                                            manifest_path(batch.id)).read_text(encoding="utf-8"))]
    assert lines == ["STARTED", "CLAIMED", "RUNNING", "REPORTED", "READY_TO_LAND"]
