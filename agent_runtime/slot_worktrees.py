"""Development workspaces: the git worktrees cut from a repo slot's folder, recorded against it
(row ``RT-WORKTREE-RECORDED-ON-SLOT``).

Plan ``docs/agent-runtime-harness/planned/naming-and-address-map-2026-10-25.md`` ruling 5: a git worktree an
agent cuts is a development workspace — a machine-level checkout of a repo slot — and the harness records
each one against that slot's folder, so an audit lists it without reading terminal commands.

How it is seen, not guessed: a turn OBSERVES each repo slot its realm workspace binds on this machine, at its
start and at its end (``git worktree list --porcelain`` on the slot folder). A worktree first seen at a turn's
END was cut during that turn and records ``created_by_turn`` = the turn's address
(:mod:`agent_runtime.address`); one first seen at a START was cut outside any turn (by the operator) and
records ``created_by_turn: null``. A recorded worktree that is gone records ``removed_at`` and the turn that
saw it gone. Two turns running at once on one slot share the window, so ``created_by_turn`` names the turn
whose end FIRST saw the worktree — the honest bound of what one observation can say.

The ledger is ``paths.slot_worktrees_path(owner, slot)``: machine-local like the slot fill, never synced. The
owner is the Project that declares the slot (``<project>/<slot>``, plan project-slots-and-shared-chats §3), or
the workspace for a slot its own document still declares. No command text is read and nothing is ever written
into the slot's repository.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from . import paths
from .locks import slot_worktrees_lock

__layer__ = "stores"

LEDGER_SCHEMA = 1
GIT_TIMEOUT_SECONDS = 10
PHASE_START, PHASE_END = "start", "end"

Runner = Callable[[Path], str | None]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _git_worktrees(repo: Path) -> str | None:
    from .git_cmd import run_git

    try:
        done = run_git(["worktree", "list", "--porcelain"], repo=repo, timeout=GIT_TIMEOUT_SECONDS,
                       stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_porcelain(text: str) -> dict[str, dict[str, Any]]:
    """``{worktree path: {head, branch}}`` for every LINKED worktree (the slot's own checkout is the first block)."""

    blocks: list[dict[str, Any]] = []
    for line in text.splitlines():
        if line.startswith("worktree "):
            blocks.append({"path": line[len("worktree "):].strip()})
        elif blocks and line.startswith("HEAD "):
            blocks[-1]["head"] = line[len("HEAD "):].strip()
        elif blocks and line.startswith("branch "):
            blocks[-1]["branch"] = line[len("branch "):].strip().removeprefix("refs/heads/")
    return {block["path"]: {"head": block.get("head"), "branch": block.get("branch")} for block in blocks[1:]}


def load_ledger(workspace_id: str, slot: str) -> dict[str, Any]:
    try:
        record = json.loads(paths.slot_worktrees_path(workspace_id, slot).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    if not isinstance(record, dict) or record.get("schema") != LEDGER_SCHEMA:
        record = {"schema": LEDGER_SCHEMA, "workspace_id": workspace_id, "slot": slot, "worktrees": {}}
    record.setdefault("worktrees", {})
    return record


def observe(workspace_id: str, slot: str, repo: Path, *, phase: str, turn: str | None,
            run: Runner = _git_worktrees, now: str | None = None) -> dict[str, list[str]]:
    """Diff the slot's worktrees against its ledger and record what appeared and what left."""

    listing = run(repo)
    if listing is None:
        return {"created": [], "removed": []}  # unreadable now: nothing is inferred from silence
    seen = parse_porcelain(listing)
    stamp = now or _now()
    target = paths.slot_worktrees_path(workspace_id, slot)
    target.parent.mkdir(parents=True, exist_ok=True)
    with slot_worktrees_lock(workspace_id, slot):
        ledger = load_ledger(workspace_id, slot)
        rows: dict[str, Any] = ledger["worktrees"]
        created, removed = [], []
        for path, facts in sorted(seen.items()):
            row = rows.get(path)
            if row is None or row.get("removed_at"):
                rows[path] = {**facts, "first_seen_at": stamp, "first_seen_phase": phase,
                              "created_by_turn": turn if phase == PHASE_END else None,
                              "removed_at": None, "removed_seen_by_turn": None}
                created.append(path)
            else:
                row.update({key: value for key, value in facts.items() if value})
        for path, row in sorted(rows.items()):
            if path not in seen and not row.get("removed_at"):
                row["removed_at"], row["removed_seen_by_turn"] = stamp, turn
                removed.append(path)
        ledger["slot_folder"] = str(repo)
        if created or removed or not target.is_file():
            atomic_json_write(target, ledger, indent=2, sort_keys=True)
    return {"created": created, "removed": removed}


def observe_bound_slots(workspace_id: str | None, *, phase: str, turn: str | None,
                        run: Runner = _git_worktrees) -> dict[str, dict[str, list[str]]]:
    """Observe every live slot the realm workspace binds on this machine. Never raises."""

    if not workspace_id:
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    try:
        from .workspace_slots import bound_path, slot_key, slots_of_workspace

        owned: Iterable[tuple[str | None, str]] = slots_of_workspace(workspace_id)
        for project_id, name in owned:
            folder = (bound_path(name, project_id=project_id) if project_id
                      else bound_path(name, workspace_id=workspace_id))
            if folder is not None and folder.is_dir():
                out[slot_key(project_id, name)] = observe(project_id or workspace_id, name, folder, phase=phase,
                                                          turn=turn, run=run)
    except Exception:  # an audit aid: a failed observation never touches the turn
        return out
    return out


class TurnObservation:
    """One turn's two observations, each on a daemon thread so the turn never waits on git."""

    def __init__(self, workspace_id: str | None, turn: str | None, run: Runner = _git_worktrees) -> None:
        import threading

        self.workspace_id, self.turn, self._run = workspace_id, turn, run
        self.start_changes: dict[str, dict[str, list[str]]] = {}
        self.end_changes: dict[str, dict[str, list[str]]] = {}
        self._start = threading.Thread(target=self._observe_start, name="slot-worktrees-start", daemon=True)
        self._end: threading.Thread | None = None
        if workspace_id:
            self._start.start()

    def _observe_start(self) -> None:
        self.start_changes = observe_bound_slots(self.workspace_id, phase=PHASE_START, turn=self.turn, run=self._run)

    def _observe_end(self) -> None:
        if self._start.is_alive() or self._start.ident is not None:
            self._start.join(timeout=GIT_TIMEOUT_SECONDS * 2)
        self.end_changes = observe_bound_slots(self.workspace_id, phase=PHASE_END, turn=self.turn, run=self._run)

    def finish(self) -> None:
        import threading

        if not self.workspace_id or self._end is not None:
            return
        self._end = threading.Thread(target=self._observe_end, name="slot-worktrees-end", daemon=True)
        self._end.start()

    def join(self, timeout: float | None = None) -> None:
        """Tests: wait for both observations."""
        if self._start.ident is not None:
            self._start.join(timeout)
        if self._end is not None:
            self._end.join(timeout)


def start_turn_observation(workspace_id: str | None, *, persona_instance_id: str | None, chat_id: str | None,
                           turn_id: str | None) -> TurnObservation:
    from .address import turn_address

    address = turn_address(persona_instance_id=persona_instance_id, chat_id=chat_id, turn_id=turn_id)
    return TurnObservation(workspace_id, str(address) if address is not None else None)
