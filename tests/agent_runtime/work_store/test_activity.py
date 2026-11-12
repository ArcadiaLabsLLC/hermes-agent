"""A workspace's task activity sidecar (RT-WORKSPACE-SUMMARY-ACTIVITY): the counting rule, the engine tick as
its one writer, and ``workspace_summary`` as its reader — with no board walk and no git on the snapshot path.
Killing mutations are named per test."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agent_runtime.events import EventLog
from agent_runtime.store import WorkspaceStore
from agent_runtime.work.store import Synced
from agent_runtime.work_store import activity
from agent_runtime.work_store.activity import count_tasks, read_activity, record_view
from agent_runtime.work_store.board import Board, board_rows
from agent_runtime.work_store.engine import WorkEngine
from agent_runtime.work_store.grammar import parse_note
from agent_runtime.work_store.reasons import Reason, WorkRefused

WS = "ws_activity_test"
BRAIN = "Repo_Brain/20 — Active Initiatives"
HEAD = "---\ntype: queue\nprogram: test\n---\n\n## Open\n\n"
D = "2026-11-12"
ROWS = (
    f"- **`TASK-SHIP` — ship it** · task: ship · READY {D} · **TAKEN {D} lane-a on box as me in tree**",
    f"- **`RT-SHIP-1` — a subtask of ship** · group: ship · READY {D} · **TAKEN {D} persona:inst-1**",
    f"- **`RT-SHIP-2` — a subtask asking the owner** · group: ship.ui · DECISION {D}: pick one · Recommend: A",
    f"- **`TASK-PLAN` — plan it** · task: plan · BLOCKED {D}: owner decision — `RT-PLAN-1` · Recommend: yes",
    f"- **`TASK-HELD` — owner question on a claimed task** · task: held · DECISION {D}: which · Recommend: B"
    f" · **TAKEN {D} lane-b on box as me in tree**",
    f"- **`WORK-AAAAAA` — a lone row an agent runs** · READY {D} · **TAKEN {D} persona:inst-2**",
    f"- **`WORK-BBBBBB` — a lone row waiting on the owner** · BLOCKED {D}: owner sitting — look at it",
    f"- **`WORK-CCCCCC` — a lone row waiting on a dependency** · BLOCKED {D}: hermes — `RT-X` first",
    f"- **`RT-ORPHAN` — a subtask whose task is not on these boards** · group: elsewhere · DECISION {D}: q · Recommend: A",
    f"- **`WORK-DDDDDD` — queued** · READY {D}",
)


class _Writer:
    def __init__(self, root: Path, committed_at: int | None = 1_762_900_000) -> None:
        self.worktree, self.committed_at, self.asked = root, committed_at, []

    def note_committed_at(self, note: str) -> int | None:
        self.asked.append(note)
        return self.committed_at


def _board(root: Path, slot: str, rows: tuple[str, ...]) -> Board:
    (root / BRAIN).mkdir(parents=True, exist_ok=True)
    (root / BRAIN / "q.md").write_text(HEAD + "".join(row + "\n" for row in rows), encoding="utf-8")
    return Board(WS, slot, root, BRAIN, "main", None, True, True, False, root)


def _events() -> list[dict]:
    return [event.payload for event in EventLog().tail(50) if event.type == "workspace.updated"
            and event.payload.get("change") == "task_activity"]


def test_the_counts_are_over_tasks_claimed_is_running_and_an_unclaimed_owner_wait_needs_you():
    """Mutations: count subtasks too -> tasks_running 4, red; drop the claimed-first rule -> the claimed DECISION
    task also needs you (4), red; count every BLOCKED row -> the dependency wait needs you (4), red; drop the
    orphan-subtask arm -> ``RT-ORPHAN`` is not counted (2), red."""
    rows = parse_note(HEAD + "\n".join(ROWS) + "\n", slot="repo", note="q.md")
    assert count_tasks(rows) == {"tasks_running": 3, "needs_you": 3}
    assert count_tasks([]) == {"tasks_running": 0, "needs_you": 0}


def test_the_engine_tick_writes_the_sidecar_and_the_snapshot_row_reads_it_without_touching_a_board(tmp_path, monkeypatch):
    """Mutations: drop the engine's ``record_view`` call -> the row stays unknown (None), red; make
    ``workspace_summary`` count from the board -> ``board_rows`` is called on the snapshot path, red; emit
    ``workspace.updated`` on a time-only change -> a second event, red; drop the event -> no event, red."""
    from agent_runtime.snapshot import workspace_summary

    workspace = WorkspaceStore().create(name="Activity", workspace_id=WS)
    unknown = workspace_summary(workspace)
    assert (unknown["tasks_running"], unknown["needs_you"], unknown["last_activity_at"]) == (None, None, None)
    board, writer = _board(tmp_path, "repo", ROWS), _Writer(tmp_path)
    engine = WorkEngine(executor=_NoRuns(), sync=lambda ws: Synced([board], {"repo": writer}, False),
                        workspaces=lambda: [WS], brief_of=lambda row, w: "", cap_for=lambda ws: 0)
    engine.tick()
    assert writer.asked == [BRAIN]
    monkeypatch.setattr("agent_runtime.work_store.board.board_rows", _never)
    monkeypatch.setattr(activity, "count_tasks", _never)
    row = workspace_summary(WorkspaceStore().get(WS))
    stamp = datetime.fromtimestamp(1_762_900_000, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    assert (row["tasks_running"], row["needs_you"], row["last_activity_at"]) == (3, 3, stamp)
    monkeypatch.undo()
    assert len(_events()) == 1 and _events()[0]["workspace_id"] == WS
    engine.tick()
    assert len(_events()) == 1, "an unchanged read writes nothing and appends nothing"
    writer.committed_at += 60
    engine.tick()
    assert read_activity(WS)["last_activity_at"] > stamp and len(_events()) == 1, "a time-only change rides the next build"
    _board(tmp_path, "repo", ROWS[:-1] + (ROWS[-1] + f" · **TAKEN {D} lane-c on box as me in tree**",))
    engine.tick()
    assert read_activity(WS)["tasks_running"] == 4 and len(_events()) == 2


def test_a_board_the_engine_could_not_read_leaves_the_counts_unknown_and_no_board_is_zero(tmp_path):
    """Mutations: record a partial read -> the counts of the one readable board are published as the
    workspace's, red; treat no board as unknown -> a workspace with no board says None instead of 0, red."""
    here, away = _board(tmp_path / "a", "here", ROWS), _board(tmp_path / "b", "away", ROWS)
    rows = {"here": board_rows(here)}
    view = Synced([here, away], {"here": _Writer(tmp_path / "a")}, True)
    assert record_view(WS, view, rows) is False
    refused = Synced([here], {"here": _Writer(tmp_path / "a")}, False, {"here": WorkRefused(Reason.INVALID, "x")})
    assert record_view(WS, refused, rows) is False
    assert read_activity(WS) == {"tasks_running": None, "needs_you": None, "last_activity_at": None}
    assert record_view(WS, Synced([], {}, False), {}) is True
    assert read_activity(WS) == {"tasks_running": 0, "needs_you": 0, "last_activity_at": None}
    assert record_view(WS, Synced([here], {"here": _Writer(tmp_path / "a", committed_at=None)}, False), rows) is True
    assert read_activity(WS) == {"tasks_running": 3, "needs_you": 3, "last_activity_at": None}


def _never(*_args, **_kwargs):
    raise AssertionError("the snapshot path walked a board")


class _NoRuns:
    kind = "persona_turn"

    def can_start(self, assignment):
        return Reason.INVALID

    def status(self, run_id):
        return None

    def on_settle(self, callback):
        self.callback = callback
