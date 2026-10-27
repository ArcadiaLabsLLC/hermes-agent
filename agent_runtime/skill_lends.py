"""Skills lent to a WORKER (a live child agent): one record per child, never the child's session.

Plan ``docs/agent-runtime-harness/archive/p10-work-2026-10-19.md`` §4 (S2, RT-ETERNIA-SKILLS-LENDS-SKILLS).
A Work row lends through its own ``skills:`` segment; a worker has no row, so ``eternia.skills.lend`` writes
``<store_root>/skill_lends/<token>.json`` ``{target, owner_session, skills, lent_at, lent_by}``, the target
being ``child:<subagent_id>``. The child's session file is upstream's and a replaced worker (a new generation
under the same id) must not inherit a lend, so the record lives only as long as the child is registered:
:func:`sweep` drops a record whose child is gone. A child lives in the process that wrote its lend (a
gateway worker, or the serve's in-process peer), so a sweep judges only its OWN process's records by the
child registry and drops another process's records only once that process is dead (``pid``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import paths

__layer__ = "stores"
__all__ = ["CHILD_PREFIX", "LendRecord", "child_target", "lend", "lent_to", "revoke", "sweep"]

CHILD_PREFIX = "child:"


@dataclass(frozen=True)
class LendRecord:
    target: str
    owner_session: str
    skills: tuple[str, ...]
    lent_at: str
    lent_by: str
    #: The process the child lives in (the writer's pid).
    pid: int = 0


def child_target(subagent_id: str) -> str:
    return f"{CHILD_PREFIX}{subagent_id}"


def _lends_dir() -> Path:
    return paths.store_root() / "skill_lends"


def _lend_path(target: str) -> Path:
    return _lends_dir() / f"{paths.safe_path_token(target)}.json"


def _read_lend(path: Path) -> LendRecord | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return LendRecord(str(raw["target"]), str(raw.get("owner_session") or ""),
                          tuple(map(str, raw.get("skills") or ())), str(raw.get("lent_at") or ""),
                          str(raw.get("lent_by") or ""), int(raw.get("pid") or 0))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_lend(record: LendRecord) -> LendRecord:
    from utils import atomic_json_write

    _lends_dir().mkdir(parents=True, exist_ok=True)
    atomic_json_write(_lend_path(record.target), {**asdict(record), "skills": list(record.skills)}, indent=2,
                      sort_keys=True)
    return record


def lend(target: str, skills: Iterable[str], *, owner_session: str, by: str) -> LendRecord:
    """The union of what ``target`` already holds and ``skills``, written atomically."""

    held = _read_lend(_lend_path(target))
    merged = tuple(dict.fromkeys([*(held.skills if held else ()), *map(str, skills)]))
    at = datetime.now(UTC).isoformat(timespec="seconds")
    return _write_lend(LendRecord(target, owner_session, merged, at, by, os.getpid()))


def revoke(target: str, skills: Iterable[str]) -> LendRecord | None:
    """``target``'s record without ``skills``; the record is deleted (None) when nothing stays lent."""

    path = _lend_path(target)
    held = _read_lend(path)
    if held is None:
        return None
    gone = set(map(str, skills))
    kept = tuple(skill for skill in held.skills if skill not in gone)
    if not kept:
        path.unlink(missing_ok=True)
        return None
    return _write_lend(LendRecord(held.target, held.owner_session, kept, held.lent_at, held.lent_by, held.pid))


def lent_to(target: str) -> tuple[str, ...]:
    record = _read_lend(_lend_path(target))
    return record.skills if record else ()


def _gone(record: LendRecord, alive: Callable[[str], bool], pid: int) -> bool:
    from .parent_watch import process_alive

    if record.pid != pid:
        return not process_alive(record.pid)
    return not alive(record.target[len(CHILD_PREFIX):])


def sweep(alive: Callable[[str], bool], *, pid: int | None = None) -> int:
    """Drop every child lend whose child is gone; how many.

    A record written by this process (``pid``, default ``os.getpid()``) is gone when ``alive(subagent_id)``
    says its child is no longer registered; another process's record only when that process is dead.
    """

    me = os.getpid() if pid is None else pid
    dropped = 0
    for path in sorted(_lends_dir().glob("*.json")) if _lends_dir().is_dir() else ():
        record = _read_lend(path)
        if record is None or not record.target.startswith(CHILD_PREFIX):
            continue
        if _gone(record, alive, me):
            path.unlink(missing_ok=True)
            dropped += 1
    return dropped
