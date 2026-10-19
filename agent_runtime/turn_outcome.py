"""What one persona turn left behind: tests run, commits made, files written.

Derived in a plugin hook, never in the upstream executor (``RULED 2026-10-10``,
``RT-TURN-LEFT-BEHIND-RECORD``; plan ``planned/p10-turn-2026-10-19.md`` §1). The
persona runner binds a :class:`TurnOutcomeFold` around ``run_conversation``
(:func:`bind_turn_outcome`); the eternia-harness plugin's ``post_tool_call``
hook folds each terminal call into it (:func:`on_post_tool_call`). Tool calls run
under ``contextvars.copy_context().run`` (``tools/daemon_pool.py``), so the bound
fold is visible inside the hook — the same path ``usage_ledger`` rides. Nothing
is recorded when no fold is bound.

Failed calls are INCLUDED: a red test is the thing a turn left behind. A command
is classified by the :data:`COMMAND_SHAPES` table and each kind names its own
row builder in :data:`_ROW_BUILDERS`; nothing downstream branches on a kind.

The Codex app-server path never fires ``post_tool_call``; its block is absent,
which is the truth about it.
"""

from __future__ import annotations

import copy
import json
import re
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from agent_runtime.running_work.rows import bounded_operator_text

__layer__ = "policy"

TURN_OUTCOME_KEY = "turn_outcome"
TURN_OUTCOME_SCHEMA = 1

TURN_OUTCOME_TEXT_LIMIT = 400
TURN_OUTCOME_MAX_TESTS = 32
TURN_OUTCOME_MAX_COMMITS = 16
TURN_OUTCOME_MAX_FILES = 64

VERDICT_PASSED = "passed"
VERDICT_FAILED = "failed"
VERDICT_UNKNOWN = "unknown"
TEST_VERDICTS = frozenset({VERDICT_PASSED, VERDICT_FAILED, VERDICT_UNKNOWN})

#: The file-writing tools and the ``op`` each records; ``read_file`` is not "left behind".
FILE_TOOL_OPS: Mapping[str, str] = MappingProxyType({"write_file": "write", "patch": "patch"})
FILE_OPS = frozenset(FILE_TOOL_OPS.values())

TERMINAL_TOOL = "terminal"

# A git commit's own ``[<branch> <sha>]`` line (``[main (root-commit) abc1234]`` too).
_COMMIT_SHA_RE = re.compile(r"^\[[^\]\n]*?\b([0-9a-f]{7,40})\]", re.MULTILINE)
SHA_RE = re.compile(r"[0-9a-f]{7,40}")

# The git subcommand position: ``git``, then global options (``-C <dir>``, ``-c k=v``,
# ``--no-pager``), then the verb — so ``git commit -m "push fix"`` is not a push.
_GIT_VERB = r"\bgit(?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*\s+{verb}\b"


class CommandKind(StrEnum):
    TEST = "test"
    COMMIT = "commit"
    PUSH = "push"


@dataclass(frozen=True)
class CommandShape:
    kind: CommandKind
    pattern: re.Pattern[str]


#: The table, in precedence order (push before commit). ``classify_command`` reports
#: every kind a line matches, ordered by where it appears in the line, so
#: ``git commit && git push`` folds the commit first and the push then marks it.
COMMAND_SHAPES: tuple[CommandShape, ...] = (
    CommandShape(CommandKind.TEST, re.compile(
        r"\b(pytest|run_tests(_bundled)?\.sh|flutter test|dart test|npm test|pnpm test"
        r"|go test|cargo test|dotnet test)\b")),
    CommandShape(CommandKind.PUSH, re.compile(_GIT_VERB.format(verb="push"))),
    CommandShape(CommandKind.COMMIT, re.compile(_GIT_VERB.format(verb="commit"))),
)


def classify_command(text: str) -> tuple[CommandKind, ...]:
    """Every kind ``text`` matches, in line order (a regex over-approximation: a
    quoted ``pytest`` still reads as a test)."""

    hits: list[tuple[int, int, CommandKind]] = []
    for precedence, shape in enumerate(COMMAND_SHAPES):
        match = shape.pattern.search(text or "")
        if match is not None:
            hits.append((match.start(), precedence, shape.kind))
    return tuple(kind for _start, _precedence, kind in sorted(hits))


def _exit_code(value: Any) -> int | None:
    return value if type(value) is int and -256 <= value <= 256 else None


def verdict_for_exit(exit_code: int | None) -> str:
    """``0`` passed, non-zero failed, no code unknown — never read from output text."""

    if exit_code is None:
        return VERDICT_UNKNOWN
    return VERDICT_PASSED if exit_code == 0 else VERDICT_FAILED


def _terminal_payload(result: Any) -> dict[str, Any]:
    # Guarded exactly as agent/turn_summary.py::_extract_line_deltas reads a result.
    payload: Any = result
    if isinstance(payload, str):
        text = payload.strip()
        if not text.startswith("{"):
            return {}
        try:
            payload = json.loads(text, strict=False)
        except Exception:
            return {}
    return payload if isinstance(payload, dict) else {}


@dataclass
class TurnOutcomeFold:
    """One turn's accumulating record. Tool calls may run on pool threads: locked."""

    tests: list[dict[str, Any]] = field(default_factory=list)
    commits: list[dict[str, Any]] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def _append(self, rows: list[dict[str, Any]], row: dict[str, Any], cap: int) -> None:
        if len(rows) >= cap:
            self.truncated = True
        else:
            rows.append(row)

    def fold_terminal(self, command: str, exit_code: int | None, output: str) -> None:
        with self._lock:
            for kind in classify_command(command):
                _ROW_BUILDERS[kind](self, command, exit_code, output)

    def fold_file(self, path: str, op: str) -> None:
        row = {"path": path, "op": op}
        with self._lock:
            if row not in self.files:
                self._append(self.files, row, TURN_OUTCOME_MAX_FILES)

    def block(self) -> dict[str, Any] | None:
        """The ``turn_outcome`` block, or None when nothing was folded (absent stays absent)."""

        with self._lock:
            if not (self.tests or self.commits or self.files or self.truncated):
                return None
            return {
                "schema": TURN_OUTCOME_SCHEMA,
                "tests": [dict(row) for row in self.tests],
                "commits": [dict(row) for row in self.commits],
                "files": [dict(row) for row in self.files],
                "truncated": self.truncated,
            }


def _test_row(fold: TurnOutcomeFold, command: str, exit_code: int | None, _output: str) -> None:
    fold._append(fold.tests, {"command": command, "exit_code": exit_code,
                              "verdict": verdict_for_exit(exit_code)}, TURN_OUTCOME_MAX_TESTS)


def _commit_row(fold: TurnOutcomeFold, command: str, _exit_code: int | None, output: str) -> None:
    match = _COMMIT_SHA_RE.search(output or "")
    fold._append(fold.commits, {"command": command, "sha": match.group(1) if match else None,
                                "pushed": None}, TURN_OUTCOME_MAX_COMMITS)


def _push_row(fold: TurnOutcomeFold, _command: str, exit_code: int | None, _output: str) -> None:
    # ``pushed`` is true or null, never false: the fold cannot prove a push did not
    # happen elsewhere. A push that exited 0 marks every commit folded before it.
    if exit_code == 0:
        for row in fold.commits:
            row["pushed"] = True


_ROW_BUILDERS: Mapping[CommandKind, Callable[[TurnOutcomeFold, str, int | None, str], None]] = (
    MappingProxyType({
        CommandKind.TEST: _test_row,
        CommandKind.COMMIT: _commit_row,
        CommandKind.PUSH: _push_row,
    })
)

_FOLD: ContextVar[TurnOutcomeFold | None] = ContextVar("agent_runtime_turn_outcome", default=None)


@contextmanager
def bind_turn_outcome() -> Iterator[TurnOutcomeFold]:
    """Fold this context's ``post_tool_call`` events into the yielded record."""

    fold = TurnOutcomeFold()
    token = _FOLD.set(fold)
    try:
        yield fold
    finally:
        _FOLD.reset(token)


def on_post_tool_call(tool_name: Any = None, args: Any = None, result: Any = None,
                      status: Any = None, **_context: Any) -> None:
    """``post_tool_call`` hook: a terminal call or a file write becomes a row of the bound fold."""

    fold = _FOLD.get()
    if fold is None:
        return
    args = args if isinstance(args, dict) else {}
    if tool_name == TERMINAL_TOOL:
        command = bounded_operator_text(args.get("command"), limit=TURN_OUTCOME_TEXT_LIMIT)
        if command:
            payload = _terminal_payload(result)
            output = payload.get("output")
            fold.fold_terminal(command, _exit_code(payload.get("exit_code")),
                               output if isinstance(output, str) else "")
        return
    op = FILE_TOOL_OPS.get(str(tool_name or ""))
    if op is not None and status == "ok":
        path = bounded_operator_text(args.get("path"), limit=TURN_OUTCOME_TEXT_LIMIT)
        if path:
            fold.fold_file(path, op)


def turn_outcome_block(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """The stored ``turn_outcome`` block of a turn record, COPIED (never derived), or None.

    The store already bounded it through ``mission_chat_turns.records.safe_turn_outcome``;
    a record with no block (an older turn, a Codex app-server turn) answers None.
    """

    block = (record or {}).get(TURN_OUTCOME_KEY)
    return copy.deepcopy(block) if isinstance(block, dict) and block else None
