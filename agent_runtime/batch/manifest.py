"""The batch manifest — a batch IS this note plus its rows' claim marks (dispatcher plan §3.4).

Where: ``<brain>/50 — Agent Handoffs/batches/<BATCH-id>.md`` in the workspace's DEFAULT BRAIN (owner
ruling 2026-10-18 on ``RT-DISPATCH-B2-BATCH``): the board ``default_brain.ensure_default_brain`` returns —
the first repo brain bound here once one is, else the machine-local default brain (which normalizes
into a repo brain when one is bound). Lane briefs sit beside it, ``batches/<BATCH-id>/<lane>.md``; the
workspace's ``batch_automation`` is the frontmatter of ``batches/settings.md`` (absent: ``off``).

Shape: frontmatter ``type: batch`` (``batch``, ``workspace_id``, ``owner_machine``, ``created_at``), then
ONE line per lane per state, appended, never rewritten::

    - <utc> · batch · STARTED · `{"plan": {…}}`
    - <utc> · lane L1 · CLAIMED · `{"rows": [[slot, note, id], …], "persona": "…"}`

Every line goes through the W2 writer as an ``append`` op whose ``appends`` payload is read at the tip
(a lost race replays onto the newer tip), keyed by a request id derived from the batch, the lane and
the state, so a repeat is a replay. :func:`fold` rebuilds a :class:`machine.Batch` from the text alone —
no SQLite, no in-memory truth.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from ..work_store.board import Board, has_brain_here
from ..work_store.executor import Verdict
from ..work_store.grammar import Op, RowRef
from .machine import LIVE, Automation, Batch, BatchState, LaneRecord, LaneState
from .planner import Plan

__layer__ = "lanes"  # imports work_store.executor.Verdict (a lanes module); RT-BATCH-LAYER-TYPES
__all__ = [
    "BATCHES_DIR",
    "DISPATCHER",
    "SETTINGS_NOTE",
    "BrainManifestStore",
    "Entry",
    "ManifestStore",
    "automation_of",
    "brief_path",
    "entry_line",
    "fold",
    "head",
    "held_refs",
    "manifest_board",
    "manifest_path",
    "parse",
]

BATCHES_DIR = "50 — Agent Handoffs/batches"
SETTINGS_NOTE = "settings.md"
#: The ``who`` of every manifest commit the dispatcher writes.
DISPATCHER = "dispatcher"
BATCH_SUBJECT = "batch"
LANE_PREFIX = "lane "
STOP_REQUESTED = "STOP_REQUESTED"
_LINE = re.compile(r"^- (\S+) · (batch|lane [A-Za-z0-9_-]+) · ([A-Z_]+) · `(.*)`\s*$")
_FRONT = re.compile(r"^([a-z_]+):\s*(.*)$")


def manifest_path(batch_id: str) -> str:
    """The manifest's path under the brain root."""

    return f"{BATCHES_DIR}/{batch_id}.md"


def brief_path(batch_id: str, lane_id: str) -> str:
    return f"{BATCHES_DIR}/{batch_id}/{lane_id}.md"


def _brain_root(brain_dir: str | None) -> str:
    brain = PurePosixPath(brain_dir or "")
    return (brain.parent if str(brain.parent) != "." else brain).as_posix()


# ── the text ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Entry:
    at: str
    subject: str
    word: str
    data: Mapping[str, Any]


def entry_line(at: str, subject: str, word: str, data: Mapping[str, Any]) -> str:
    """One manifest line; the data is one JSON code span (a backtick inside is escaped)."""

    payload = json.dumps(dict(data), sort_keys=True, separators=(",", ":"), ensure_ascii=False).replace("`", "\\u0060")
    return f"- {at} · {subject} · {word} · `{payload}`"


def head(plan: Plan, *, owner_machine: str, created_at: str) -> str:
    return "\n".join([
        "---", "type: batch", f"batch: {plan.id}", f"workspace_id: {plan.workspace_id}",
        f"owner_machine: {owner_machine}", f"created_at: {created_at}", "---", "", f"# {plan.id}", "",
        "The batch manifest (dispatcher plan §3.4): one line per lane per state, appended by the dispatcher",
        f"through the Work writer. Lane briefs: `{BATCHES_DIR}/{plan.id}/<lane>.md`.", "", ""])


def frontmatter(text: str) -> dict[str, str]:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = _FRONT.match(line.strip())
        if match:
            out[match.group(1)] = match.group(2).strip()
    return out


def parse(text: str) -> list[Entry]:
    """Every manifest line, in order; a line that does not parse is skipped (never fatal)."""

    out = []
    for line in text.split("\n"):
        match = _LINE.match(line.rstrip("\r"))
        if match is None:
            continue
        try:
            data = json.loads(match.group(4))
        except ValueError:
            continue
        out.append(Entry(match.group(1), match.group(2), match.group(3), data if isinstance(data, dict) else {}))
    return out


def automation_of(text: str | None) -> Automation:
    """``batch_automation`` from the settings note's frontmatter; absent or unknown reads ``off``."""

    value = frontmatter(text or "").get("batch_automation", "")
    return Automation(value) if value in Automation._value2member_map_ else Automation.OFF


# ── the fold ───────────────────────────────────────────────────────────────


def _rows(raw: Iterable[Any]) -> tuple[RowRef, ...]:
    return tuple(RowRef(*map(str, item)) for item in raw or () if len(item) == 3)


#: How each lane-line key lands on the record (absent keys leave the record as it was).
_LANE_KEYS: dict[str, Callable[[Any], tuple[str, Any]]] = {
    "rows": lambda v: ("rows", _rows(v)),
    "persona": lambda v: ("persona", v or None),
    "run_id": lambda v: ("run_id", str(v or "")),
    "verdict": lambda v: ("verdict", Verdict(v) if v else None),
    "tool_calls": lambda v: ("tool_calls", v if isinstance(v, int) else None),
    "commits": lambda v: ("commits", tuple(map(str, v or ()))),
    "done_rows": lambda v: ("done_rows", int(v or 0)),
}


class _Fold:
    """The batch as its lines so far; one method per kind of line."""

    def __init__(self, front: Mapping[str, str]) -> None:
        self.front = front
        self.plan: Plan | None = None
        self.state = BatchState.PLANNED
        self.lanes: dict[str, LaneRecord] = {}
        self.landing: LaneRecord | None = None
        self.attempt = 0
        self.gate = ""
        self.sha = ""

    def batch_line(self, entry: Entry) -> None:
        if entry.word not in BatchState._value2member_map_:
            return
        self.state = BatchState(entry.word)
        if self.state is BatchState.STARTED and self.plan is None and isinstance(entry.data.get("plan"), dict):
            self.plan = Plan.from_wire(entry.data["plan"])
            self.lanes = {lane.id: LaneRecord(lane, persona=lane.persona) for lane in self.plan.lanes}
            self.landing = LaneRecord(self.plan.landing, persona=self.plan.landing.persona)
        if self.state is BatchState.LANDING and self.landing is not None:
            self.attempt += 1
            self.landing = LaneRecord(self.landing.lane, persona=entry.data.get("persona") or self.landing.persona)
        self.gate = str(entry.data.get("gate", self.gate) or "")
        self.sha = str(entry.data.get("landing_sha", self.sha) or "")

    def lane_line(self, entry: Entry) -> None:
        lane_id = entry.subject[len(LANE_PREFIX):]
        record = self.lanes.get(lane_id) or (self.landing if self.landing and self.landing.id == lane_id else None)
        if record is None:
            return
        if entry.word == STOP_REQUESTED:
            record = replace(record, stop_requested=True)
        elif entry.word in LaneState._value2member_map_:
            fields = dict(_LANE_KEYS[key](value) for key, value in entry.data.items() if key in _LANE_KEYS)
            record = replace(record, state=LaneState(entry.word), **fields)
        if self.landing is not None and record.id == self.landing.id:
            self.landing = record
        else:
            self.lanes[lane_id] = record

    def batch(self) -> Batch | None:
        if self.plan is None or self.landing is None:
            return None
        return Batch(self.plan.id, self.plan.workspace_id, self.front.get("owner_machine", ""), self.state,
                     tuple(self.lanes[lane.id] for lane in self.plan.lanes), self.landing, self.plan.budget,
                     self.attempt, self.gate, self.sha)


def fold(text: str) -> Batch | None:
    """The batch a manifest note describes, or None when it carries no ``STARTED`` line."""

    acc = _Fold(frontmatter(text))
    for entry in parse(text):
        (acc.batch_line if entry.subject == BATCH_SUBJECT else acc.lane_line)(entry)
    return acc.batch()


def _held_by(batch: Batch) -> set[RowRef]:
    if batch.state not in LIVE:
        return set()
    held: set[RowRef] = set()
    for lane in batch.lanes:
        if lane.state is LaneState.PLANNED:
            held.update(lane.lane.rows)
        elif lane.state in (LaneState.CLAIMED, LaneState.RUNNING):
            held.update(lane.rows)
    return held


# ── where the manifests live ───────────────────────────────────────────────


def manifest_board(boards: Sequence[Board]) -> Board | None:
    """The default brain among ``boards`` WITHOUT creating it: the first repo brain bound here, else
    the machine-local default brain's board (what ``ensure_default_brain`` would return)."""

    repo = next((b for b in boards if not b.is_default and has_brain_here(b)), None)
    return repo or next((b for b in boards if b.is_default), None)


def read_texts(root: Path | None, brain_dir: str | None) -> dict[str, str]:
    """``{batch_id: manifest text}`` under ``root`` (a worktree of the manifest board)."""

    if root is None:
        return {}
    directory = root / _brain_root(brain_dir) / BATCHES_DIR
    if not directory.is_dir():
        return {}
    return {path.stem: path.read_bytes().decode("utf-8") for path in sorted(directory.glob("BATCH-*.md"))}


def held_refs(workspace_id: str, view: Any) -> set[RowRef]:
    """The rows a live batch's lanes hold (planned or claimed), read from an already-synced ``view``
    (``work.store.Synced``) — the W3 engine's ``held`` hook: it never starts a per-row run for them."""

    board = manifest_board(view.boards)
    if board is None:
        return set()
    texts = read_texts(view.read_roots.get(board.slot), board.brain_dir)
    return {ref for text in texts.values() if (batch := fold(text)) is not None for ref in _held_by(batch)}


class ManifestStore(Protocol):
    def texts(self, workspace_id: str, *, fresh: bool = True) -> dict[str, str]:
        """``{batch_id: text}`` of every manifest; ``fresh`` fetches first, else reads the worktree as is."""

    def settings(self, workspace_id: str) -> str | None:
        """The text of ``batches/settings.md``, or None."""

    def append(self, workspace_id: str, batch_id: str, lines: Sequence[str], request_id: str, *,
               files: Mapping[str, str] | None = None) -> None:
        """Append ``lines`` to the manifest (and write ``files``, brain-root relative) in ONE commit."""


class BrainManifestStore:
    """The manifests in the workspace's default brain, written only through the W2 writer."""

    def __init__(self, *, writer_of: Callable[[Board], Any] | None = None, now: Callable[[], datetime] | None = None):
        self._writer_of = writer_of
        self._now = now or (lambda: datetime.now(UTC))

    def _writer(self, board: Board) -> Any:
        if self._writer_of is None:
            from ..work.store import writer_for

            self._writer_of = writer_for
        return self._writer_of(board)

    def _read_root(self, workspace_id: str, fresh: bool) -> tuple[Path | None, Board | None]:
        from ..work_store.board import boards

        board = manifest_board(boards(workspace_id))
        if board is None:
            return None, None
        writer = self._writer(board)
        if fresh:
            writer.sync(stale_ok=True)
        return (writer.worktree if (writer.worktree / ".git").exists() else None), board

    def texts(self, workspace_id: str, *, fresh: bool = True) -> dict[str, str]:
        root, board = self._read_root(workspace_id, fresh)
        return read_texts(root, board.brain_dir if board else None)

    def settings(self, workspace_id: str) -> str | None:
        root, board = self._read_root(workspace_id, False)
        path = root / _brain_root(board.brain_dir) / BATCHES_DIR / SETTINGS_NOTE if root and board else None
        return path.read_bytes().decode("utf-8") if path is not None and path.is_file() else None

    def append(self, workspace_id: str, batch_id: str, lines: Sequence[str], request_id: str, *,
               files: Mapping[str, str] | None = None) -> None:
        from ..work_store.default_brain import ensure_default_brain
        from ..work_store.writer import RowOp

        board = ensure_default_brain(workspace_id, issued_at=self._now().isoformat(timespec="seconds"))
        writer = self._writer(board)
        relative = manifest_path(batch_id)
        payload = {"appends": {relative: "".join(line + "\n" for line in lines)}, "files": dict(files or {})}
        ref = RowRef(board.slot, f"{_brain_root(board.brain_dir)}/{relative}", batch_id)
        writer.apply(RowOp(ref, Op.APPEND, DISPATCHER, request_id, payload))
