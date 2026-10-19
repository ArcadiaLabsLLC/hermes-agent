"""Builders the batch dispatcher's tests share (dispatcher plan §3, B2): rows with pointers, an
in-memory manifest store with the writer's replay-by-request-id, and a dispatcher over the fakes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from agent_runtime.batch.dispatcher import BatchDispatcher
from agent_runtime.batch.manifest import SETTINGS_NOTE, manifest_path
from agent_runtime.batch.planner import Budget, Member
from agent_runtime.work_store.grammar import Row, parse_row
from agent_runtime.work_store.models import GateReceipt

from contract_fakes import FakeExecutor, FakeSource

NOTE = "Harness_Brain/20 — Active Initiatives/runtime-queue.md"
WS = "ws-1"


def qrow(row_id: str, *, heading: str = "Fork-owned", files: Sequence[str] = (), extra: str = "",
         assignee: str | None = None, slot: str = "hermes", note: str = NOTE) -> Row:
    """A READY row in the ADR 0011 grammar, parsed as the board reads it."""

    segments = [f"- **`{row_id}` — title {row_id}{extra}**", *(f"`{f}`" for f in files)]
    segments += [f"assignee: persona:{assignee}"] if assignee else []
    segments += ["READY 2026-10-18"]
    row = parse_row(" · ".join(segments), slot=slot, note=note, line_no=1, heading=heading)
    assert row is not None and not row.defects, row
    return row


def gate(exit_code: int = 0, summary: str = "=== Summary: 3 files, 12 tests passed, 0 failed ===", *,
         slot: str = "hermes", sha: str = "f00dfeed") -> GateReceipt:
    """A code-run gate receipt as the lane executor's ``GateRunner`` returns it."""

    return GateReceipt(slot, "bash scripts/run_tests_bundled.sh tests", exit_code, summary, sha, 1.0)


class FakeManifests:
    """``ManifestStore`` in memory: a repeated request id is a replay (nothing appended twice)."""

    def __init__(self, settings: str | None = None) -> None:
        self.notes: dict[str, dict[str, str]] = {}
        self.files: dict[str, str] = {}
        self.request_ids: list[str] = []
        self.settings_text = settings

    def texts(self, workspace_id: str, *, fresh: bool = True) -> dict[str, str]:
        return dict(self.notes.get(workspace_id, {}))

    def settings(self, workspace_id: str) -> str | None:
        return self.settings_text

    def append(self, workspace_id: str, batch_id: str, lines: Sequence[str], request_id: str, *,
               files: Mapping[str, str] | None = None) -> None:
        if request_id in self.request_ids:
            return
        self.request_ids.append(request_id)
        notes = self.notes.setdefault(workspace_id, {})
        for path, text in (files or {}).items():
            if path == manifest_path(batch_id):
                notes[batch_id] = text
            else:
                self.files[path] = text
        notes[batch_id] = notes.get(batch_id, "") + "".join(line + "\n" for line in lines)


class FakeLander:
    def __init__(self) -> None:
        self.pushed: list[str] = []

    def push(self, batch: Any) -> str:
        self.pushed.append(batch.id)
        return "f00dfeed"


def dispatcher(source: FakeSource, *, manifests: FakeManifests | None = None, executor: FakeExecutor | None = None,
               machine: str = "m-1", roster: Sequence[Member] = (), budget: Budget | None = None,
               box_idle: bool = True, lander: Any = None, slot_roles: Mapping[str, str] | None = None,
               ) -> BatchDispatcher:
    manifests = manifests if manifests is not None else FakeManifests()
    executor = executor or FakeExecutor()
    built = BatchDispatcher(
        source_for=lambda _ws: source, manifests=manifests, executor=executor, machine=lambda: machine,
        roster=lambda _ws: list(roster), slot_roles=lambda _ws: dict(slot_roles or {}),
        budget_for=lambda _ws: budget or Budget(), box_idle=lambda: box_idle, lander=lander,
        workspaces=lambda: [WS], now=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))
    executor.on_settle(built.settled)
    return built


def settings(level: str) -> str:
    return f"---\ntype: batch_settings\nbatch_automation: {level}\n---\n# {SETTINGS_NOTE}\n"
