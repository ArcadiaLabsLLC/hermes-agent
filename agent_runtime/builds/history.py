"""Build history and the ETA it buys (plan ``build-running-work-2026-10-04.md`` §6).

``<background-work home>/builds/history.jsonl``: one line per ENDED build —
``{project_root_hash, toolchain, target, mode, duration_ms, outcome, ended_at}`` — appended by
the serve sweep (``builds.sweep``); the projection only READS it. A row's ``expected_ms`` is
the writer's own declaration when present, else the median of the last
:data:`MEDIAN_SAMPLES` ``succeeded`` lines for the same ``(project, toolchain, target, mode)``,
else null with ``history_samples: 0`` — the launcher draws a determinate bar only when it is
non-null. The file is a bounded log (the newest :data:`KEEP_LINES` survive a rewrite); the
project root is hashed, so the file names no path.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
from pathlib import Path
from typing import Any

from agent_runtime.builds.vocabulary import OUTCOME_SUCCEEDED

__layer__ = "stores"

HISTORY_FILENAME = "history.jsonl"
MEDIAN_SAMPLES = 5
#: The log is trimmed back to this many newest lines once it doubles past it.
KEEP_LINES = 1000


def project_root_hash(project_root: str) -> str:
    normalized = os.path.normcase(os.path.normpath(str(project_root or "")))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _lines(path: Path) -> list[dict[str, Any]]:
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in raw:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def append(directory: Path, *, project_root: str, toolchain: str, target: str, mode: str,
           duration_ms: int, outcome: str, ended_at: float) -> None:
    """One ended build. Trims to the newest ``KEEP_LINES`` once the file passes twice that."""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / HISTORY_FILENAME
    line = {"project_root_hash": project_root_hash(project_root), "toolchain": toolchain, "target": target,
            "mode": mode, "duration_ms": int(max(0, duration_ms)), "outcome": outcome, "ended_at": float(ended_at)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")
    lines = _lines(path)
    if len(lines) > 2 * KEEP_LINES:
        temp = path.with_suffix(".jsonl.tmp")
        temp.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in lines[-KEEP_LINES:]), encoding="utf-8")
        os.replace(temp, path)


def estimate(directory: Path, *, project_root: str, toolchain: str, target: str, mode: str) -> tuple[int | None, int]:
    """``(median ms, samples)`` over the last ``MEDIAN_SAMPLES`` succeeded builds of this key; ``(None, 0)`` without one."""

    key = (project_root_hash(project_root), toolchain, target, mode)
    durations = [int(item.get("duration_ms") or 0) for item in _lines(directory / HISTORY_FILENAME)
                 if item.get("outcome") == OUTCOME_SUCCEEDED
                 and (item.get("project_root_hash"), item.get("toolchain"), item.get("target"), item.get("mode")) == key]
    recent = durations[-MEDIAN_SAMPLES:]
    if not recent:
        return None, 0
    return int(statistics.median(recent)), len(recent)
