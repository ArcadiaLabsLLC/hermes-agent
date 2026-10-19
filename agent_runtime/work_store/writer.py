"""The Work writer — one row operation per commit, in hermes's own worktree, pushed fast-forward (plan §5).

Every write is a :class:`RowOp` found by ID and applied as ONE line edit (``grammar.apply``); no
textual merge, ``rebase``, ``pull`` or ``stash`` ever runs. The worktree lives under
``paths.work_worktree_dir(ws, slot)`` on branch ``work/<machine_id>``, cut ``--no-checkout`` with a
non-cone sparse checkout of the brain folder, so the operator's checkout (its index and its tree)
is never touched. Steps, in the §5 table's numbering:

0. preconditions — the slot is bound here with a ``.git`` and the board has a brain (whether git is
   shipped at all is the lanes caller's check: ``agent_runtime/work/service.py``);
1. ``worktree prune`` then, when absent, ``worktree add --no-checkout`` + ``sparse-checkout set``;
2. ``remote get-url origin`` + ``fetch origin <branch>`` (refs only; skipped for a local slot);
3. ``reset --hard <tip>`` then ``status --porcelain`` must be empty (``clean -fdq`` once);
4. idempotency — a commit at the tip whose body carries ``request_id: <rid>`` replays its receipt;
5. read the note at the tip, check the op's precondition (the ``_PRECONDITIONS`` table);
6. the one-line edit, written temp + ``os.replace``;
7. ``add`` + ``commit`` under hermes's identity as ``-c`` pairs (never ``git config``);
8. ``push origin work/<machine>:<branch>`` (fast-forward only); a local slot moves its branch with a
   compare-and-swap ``update-ref``. A non-fast-forward replays from step 2;
9. the replay budget (8) exhausted → ``push_contended``, the tips seen in the detail.

A local slot (the default brain) has no remote: steps 2 and 8 become a local tip and a CAS.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .. import paths
from . import receipts
from .board import Board, ids_in_brain
from .default_brain import IDENTITY_PAIRS
from .grammar import Op, Row, RowRef, apply as apply_line, find, parse_note, row_defects
from .models import OPERATOR
from .reasons import Reason, WorkRefused

__layer__ = "stores"
__all__ = ["REPLAY_BUDGET", "Receipt", "RowOp", "Writer", "OPERATOR"]

REPLAY_BUDGET = 8
REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_NON_FAST_FORWARD = ("! [rejected]", "fetch first", "non-fast-forward", "[remote rejected] (cannot lock ref")
_CREDENTIAL = re.compile(r"://[^/@\s]+@")


@dataclass(frozen=True)
class RowOp:
    ref: RowRef
    op: Op
    who: str
    request_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Receipt:
    ref: RowRef
    op: Op
    who: str
    request_id: str
    commit: str | None
    replays: int
    pushed: bool
    replayed: bool
    kind: str

    def wire(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": {"slot": self.ref.slot, "note": self.ref.note, "id": self.ref.id},
                "op": self.op.value, "who": self.who, "request_id": self.request_id, "commit": self.commit,
                "replays": self.replays, "pushed": self.pushed, "replayed": self.replayed}


def _tail(text: str | None) -> str:
    return _CREDENTIAL.sub("://***@", str(text or "").strip())[-200:]


# ── step 5: the precondition each op needs, as a table ──────────────────────


def _holder_or_operator(op: RowOp, row: Row) -> None:
    if row.taken is not None and op.who not in (row.taken.who, OPERATOR):
        raise WorkRefused(Reason.NOT_CLAIMANT, row.taken.who)


def _claimable(op: RowOp, row: Row | None) -> None:
    if row is None:
        raise WorkRefused(Reason.ROW_GONE, op.ref.id)
    if row.taken is not None:
        raise WorkRefused(Reason.ALREADY_TAKEN, row.taken.who)


def _held(op: RowOp, row: Row | None) -> None:
    if row is None:
        raise WorkRefused(Reason.ROW_GONE, op.ref.id)
    if row.taken is None:
        raise WorkRefused(Reason.NOT_CLAIMANT, "the row is not taken")
    _holder_or_operator(op, row)


def _present(op: RowOp, row: Row | None) -> None:
    """SET_STATUS / DELETE / ASSIGN / SET_SKILLS: the row exists; a taken row answers only its holder or the operator."""

    if row is None:
        raise WorkRefused(Reason.ROW_GONE, op.ref.id)
    _holder_or_operator(op, row)


_PRECONDITIONS: dict[Op, Callable[[RowOp, Row | None], None]] = {
    Op.CLAIM: _claimable,
    Op.RELEASE: _held,
    Op.SET_STATUS: _present,
    Op.DELETE: _present,
    Op.ASSIGN: _present,
    Op.SET_SKILLS: _present,
}


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.work-tmp")
    temp.write_bytes(text.encode("utf-8"))
    os.replace(temp, path)


class Writer:
    """The one writer of a board on this machine (one ``harness serve`` per root, doc 09 R-L2)."""

    def __init__(
        self,
        board: Board,
        *,
        machine_id: str,
        run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        now: Callable[[], datetime] | None = None,
        replay_budget: int = REPLAY_BUDGET,
    ) -> None:
        if run is None:
            from ..git_cmd import run_git as run
        self.board = board
        self.machine_id = machine_id
        self.branch = f"work/{machine_id}"
        self.worktree = paths.work_worktree_dir(board.workspace_id, board.slot)
        self.stale = False
        self._run = run
        self._now = now or (lambda: datetime.now(UTC))
        self._budget = replay_budget
        self._tip_sha: str | None = None

    # ── the git door ─────────────────────────────────────────────────────

    @property
    def tip(self) -> str:
        return self.board.default_branch if self.board.local else f"origin/{self.board.default_branch}"

    @property
    def brain_root(self) -> str:
        brain = PurePosixPath(self.board.brain_dir or "")
        return (brain.parent if str(brain.parent) != "." else brain).as_posix()

    def _git(self, args: list[str], *, repo: Path, config: tuple[str, ...] = ()) -> subprocess.CompletedProcess[str]:
        return self._run(args, repo=repo, config=config, encoding="utf-8", errors="replace",
                         timeout=120, stdin=subprocess.DEVNULL)

    def _must(self, args: list[str], reason: Reason, *, repo: Path, config: tuple[str, ...] = ()) -> str:
        done = self._git(args, repo=repo, config=config)
        if done.returncode != 0:
            raise WorkRefused(reason, f"git {args[0]}: {_tail(done.stderr)}")
        return str(done.stdout or "")

    # ── steps 0–3: sync (a read runs these only) ─────────────────────────

    def _clone(self) -> Path:
        from ..workspace_slots import bound_path

        if self.board.brain_dir is None:
            raise WorkRefused(Reason.NO_BRAIN, self.board.slot)
        clone = self.board.checkout or bound_path(self.board.slot)
        if clone is None or not (clone / ".git").exists():
            raise WorkRefused(Reason.SLOT_UNBOUND, self.board.slot)
        return clone

    def _common_dir(self, repo: Path) -> str:
        done = self._git(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo=repo)
        text = str(done.stdout or "").strip() if done.returncode == 0 else ""
        return os.path.normcase(os.path.realpath(text)) if text else f"?{repo}"

    def _ensure_worktree(self, clone: Path) -> None:
        self._git(["worktree", "prune"], repo=clone)
        if (self.worktree / ".git").exists():
            if self._common_dir(self.worktree) == self._common_dir(clone):
                return
            # Another checkout's worktree under this slot's name: the default brain and a declared slot
            # ``brain`` adopted on a second machine share it until the move retires the default (p10-work §2.5).
            shutil.rmtree(self.worktree)
            self._git(["worktree", "prune"], repo=clone)
        if self.worktree.exists():
            shutil.rmtree(self.worktree)
        self.worktree.parent.mkdir(parents=True, exist_ok=True)
        start = self.tip if self._git(["rev-parse", "-q", "--verify", self.tip], repo=clone).returncode == 0 else "HEAD"
        self._must(["worktree", "add", "-q", "--no-checkout", str(self.worktree), "-B", self.branch, start],
                   Reason.WORKTREE_FAILED, repo=clone)
        self._must(["sparse-checkout", "set", "--no-cone", f"/{self.brain_root}/"], Reason.WORKTREE_FAILED,
                   repo=self.worktree)

    def _fetch(self, clone: Path, *, stale_ok: bool) -> None:
        self.stale = False
        if self.board.local:
            return
        if self._git(["remote", "get-url", "origin"], repo=clone).returncode != 0:
            raise WorkRefused(Reason.REMOTE_MISSING, self.board.slot)
        done = self._git(["fetch", "-q", "origin", self.board.default_branch], repo=clone)
        if done.returncode == 0:
            return
        if "couldn't find remote ref" in str(done.stderr):
            raise WorkRefused(Reason.BRANCH_MISSING, self.board.default_branch)
        if not stale_ok:
            raise WorkRefused(Reason.FETCH_FAILED, _tail(done.stderr))
        self.stale = True

    def _dirty(self) -> bool:
        return bool(self._must(["status", "--porcelain"], Reason.WORKTREE_DIRTY, repo=self.worktree).strip())

    def _reset(self) -> None:
        self._must(["reset", "-q", "--hard", self.tip], Reason.BRANCH_MISSING, repo=self.worktree)
        if self._dirty():
            self._git(["clean", "-fdq"], repo=self.worktree)
            if self._dirty():
                raise WorkRefused(Reason.WORKTREE_DIRTY, self.board.slot)
        self._tip_sha = self._must(["rev-parse", "HEAD"], Reason.BRANCH_MISSING, repo=self.worktree).strip()

    def sync(self, *, stale_ok: bool = False) -> Path:
        """Steps 0–3: the worktree at the tip; ``stale`` is set when a tolerated fetch failed."""

        clone = self._clone()
        self._ensure_worktree(clone)
        self._fetch(clone, stale_ok=stale_ok)
        self._reset()
        return self.worktree

    # ── step 4: idempotency ──────────────────────────────────────────────

    def _replayed(self, request_id: str) -> tuple[str, str] | None:
        pattern = "^request_id: " + request_id.replace(".", "\\.") + "$"
        out = self._git(["log", "-n", "1", "-E", f"--grep={pattern}", "--format=%H%n%s", self.tip],
                        repo=self.worktree)
        lines = str(out.stdout or "").splitlines() if out.returncode == 0 else []
        return (lines[0], lines[1] if len(lines) > 1 else "") if lines else None

    # ── steps 5–6: precondition and the one-line edit ────────────────────

    def _note_rows(self, ref: RowRef) -> tuple[Path, str, list[Row]]:
        path = self.worktree / ref.note
        if not path.is_file():
            raise WorkRefused(Reason.NOTE_MISSING, ref.note)
        text = path.read_bytes().decode("utf-8")
        rows = parse_note(text, slot=ref.slot, note=ref.note)
        bad = next((row for row in rows if row.defects), None)
        if bad is not None:
            raise WorkRefused(Reason.GRAMMAR_INVALID, f"{ref.note}:{bad.line_no}: {bad.defects[0]}")
        return path, text, rows

    def _write_files(self, files: Mapping[str, str]) -> list[str]:
        written = []
        for relative, body in sorted(files.items()):
            target = PurePosixPath(self.brain_root, relative)
            if ".." in target.parts or target.is_absolute():
                raise WorkRefused(Reason.INVALID, f"payload file {relative!r} leaves the brain")
            _write_atomic(self.worktree / target, str(body))
            written.append(target.as_posix())
        return written

    def _append_files(self, appends: Mapping[str, str]) -> list[str]:
        """``payload.appends``: text added to the END of a brain file (created when absent), read at the tip.

        Read after step 3's reset, so a replay after a lost race appends to the newer tip instead of
        overwriting it (the batch manifest's one-line-per-state log, dispatcher plan §3.4).
        """

        written = []
        for relative, body in sorted(appends.items()):
            target = PurePosixPath(self.brain_root, relative)
            if ".." in target.parts or target.is_absolute():
                raise WorkRefused(Reason.INVALID, f"payload append {relative!r} leaves the brain")
            path = self.worktree / target
            text = path.read_bytes().decode("utf-8") if path.is_file() else ""
            _write_atomic(path, text + ("" if text.endswith("\n") or not text else "\n") + str(body))
            written.append(target.as_posix())
        return written

    def _append(self, op: RowOp) -> list[str]:
        """``payload.row`` (one line) or ``payload.rows`` (several, one commit) under the note's end."""

        lines = [str(line) for line in op.payload.get("rows") or [op.payload.get("row") or ""] if line]
        written = self._write_files(op.payload.get("files") or {}) + self._append_files(op.payload.get("appends") or {})
        if not lines:
            return written
        defects = [d for line in lines for d in row_defects(line)]
        if defects or not any(f"`{op.ref.id}` — " in line for line in lines):
            raise WorkRefused(Reason.GRAMMAR_INVALID, "; ".join(defects) or "payload rows do not carry ref.id")
        path, text, _rows = self._note_rows(op.ref)
        new_ids = [parse_note(line, slot=op.ref.slot, note=op.ref.note)[0].ref.id for line in lines]
        clash = (set(new_ids) & ids_in_brain(replace(self.board, read_root=self.worktree))) or (
            {i for i in new_ids if new_ids.count(i) > 1})
        if clash:
            raise WorkRefused(Reason.ID_EXISTS, ",".join(sorted(clash)))
        body = "".join(line + "\n" for line in lines)
        _write_atomic(path, text + ("" if text.endswith("\n") or not text else "\n") + body)
        return [op.ref.note, *written]

    def _bulk_delete(self, op: RowOp) -> list[str]:
        """DELETE with ``payload.ids``: every named row gone from the note in one commit (the move out)."""

        path, text, rows = self._note_rows(op.ref)
        ids = [str(i) for i in op.payload["ids"]]
        for row_id in ids:
            _present(replace(op, ref=replace(op.ref, id=row_id)), find(rows, row_id))
        drop = {row.line_no - 1 for row in rows if row.ref.id in ids}
        kept = [line for i, line in enumerate(text.split("\n")) if i not in drop]
        _write_atomic(path, "\n".join(kept))
        return [op.ref.note] if drop else []

    def _line_edit(self, op: RowOp) -> list[str]:
        path, text, rows = self._note_rows(op.ref)
        row = find(rows, op.ref.id)
        _PRECONDITIONS[op.op](op, row)
        assert row is not None
        lines = text.split("\n")
        carriage = "\r" if lines[row.line_no - 1].endswith("\r") else ""
        date = self._now().date().isoformat()
        edited = apply_line(row.raw, op.op, who=op.who, date=date, payload=dict(op.payload))
        if edited is None:
            del lines[row.line_no - 1]
        else:
            lines[row.line_no - 1] = edited + carriage
        updated = "\n".join(lines)
        if updated == text:
            return []
        _write_atomic(path, updated)
        return [op.ref.note]

    # ── steps 7–8: commit and push ───────────────────────────────────────

    def _commit(self, op: RowOp, changed: list[str]) -> str:
        self._must(["add", "--", *changed], Reason.COMMIT_FAILED, repo=self.worktree)
        note = PurePosixPath(op.ref.note).name
        subject = f"work: {op.op.value} {op.ref.id} {op.who} (ws {self.board.workspace_id}, {op.ref.slot}/{note})"
        body = f"request_id: {op.request_id}"
        if op.op is Op.DELETE and op.payload.get("result"):
            body += "\nresult: " + " ".join(str(op.payload["result"]).split())
        self._must(["commit", "-q", "-m", subject, "-m", body], Reason.COMMIT_FAILED, repo=self.worktree,
                   config=IDENTITY_PAIRS(self.machine_id))
        return self._must(["rev-parse", "HEAD"], Reason.COMMIT_FAILED, repo=self.worktree).strip()

    def _push(self, commit: str) -> bool:
        """True when the commit is the tip now; False on a non-fast-forward (the caller replays)."""

        if self.board.local:
            ref = f"refs/heads/{self.board.default_branch}"
            return self._git(["update-ref", ref, commit, self._tip_sha or ""], repo=self.worktree).returncode == 0
        done = self._git(["push", "-q", "origin", f"{self.branch}:{self.board.default_branch}"], repo=self.worktree)
        if done.returncode == 0:
            return True
        if any(marker in str(done.stderr) for marker in _NON_FAST_FORWARD):
            return False
        raise WorkRefused(Reason.PUSH_REFUSED, _tail(done.stderr))

    # ── the whole path ───────────────────────────────────────────────────

    def _receipt(self, op: RowOp, commit: str | None, *, replays: int, pushed: bool, replayed: bool) -> Receipt:
        receipt = Receipt(op.ref, op.op, op.who, op.request_id, commit, replays, pushed, replayed,
                          f"work.row_{op.op.value}")
        receipts.emit(receipt.kind, **{k: v for k, v in receipt.wire().items() if k != "kind"},
                      workspace_id=self.board.workspace_id)
        return receipt

    def _replay_receipt(self, op: RowOp, hit: tuple[str, str], replays: int) -> Receipt:
        words = hit[1].split()
        ref = replace(op.ref, id=words[2]) if len(words) > 2 and words[0] == "work:" else op.ref
        return self._receipt(replace(op, ref=ref), hit[0], replays=replays, pushed=not self.board.local,
                             replayed=True)

    def _edit(self, op: RowOp) -> list[str]:
        if op.op is Op.APPEND:
            return self._append(op)
        return self._bulk_delete(op) if op.op is Op.DELETE and "ids" in op.payload else self._line_edit(op)

    def _validate(self, op: RowOp) -> None:
        if not REQUEST_ID.match(op.request_id):
            raise WorkRefused(Reason.INVALID, "request_id is [A-Za-z0-9_.:-]{1,200}")
        if op.ref.slot != self.board.slot:
            raise WorkRefused(Reason.INVALID, "the op's slot is not this writer's board")

    def apply(self, op: RowOp) -> Receipt:
        """Steps 0–9 for one row operation; a typed :class:`WorkRefused` on every failure branch."""

        self._validate(op)
        tips: list[str] = []
        for replays in range(self._budget):
            self.sync()
            hit = self._replayed(op.request_id)
            if hit is not None:
                return self._replay_receipt(op, hit, replays)
            changed = self._edit(op)
            if not changed:
                return self._receipt(op, None, replays=replays, pushed=False, replayed=False)
            commit = self._commit(op, changed)
            if self._push(commit):
                return self._receipt(op, commit, replays=replays, pushed=not self.board.local, replayed=False)
            tips.append(self._tip_sha or "")
        raise WorkRefused(Reason.PUSH_CONTENDED, "tips seen: " + ",".join(tips))

    # ── reads of the history ─────────────────────────────────────────────

    def history(self, ref: RowRef) -> dict[str, Any] | None:
        """The last commit at the tip that changed the count of ``<ID>`` in the note — a gone row's ending."""

        done = self._git(["log", "-n", "1", "--format=%H%n%ct%n%B", f"-S`{ref.id}`", self.tip, "--", ref.note],
                         repo=self.worktree)
        lines = str(done.stdout or "").strip("\n").split("\n") if done.returncode == 0 else []
        if len(lines) < 3 or not lines[0]:
            return None
        return {"commit": lines[0], "at": int(lines[1]), "subject": lines[2], "body": "\n".join(lines[3:]).strip()}

    def note_committed_at(self, note: str) -> int | None:
        done = self._git(["log", "-n", "1", "--format=%ct", self.tip, "--", note], repo=self.worktree)
        value = str(done.stdout or "").strip() if done.returncode == 0 else ""
        return int(value) if value.isdigit() else None
