"""Per-file diagnosis of a bundled run: where each test file's seconds went.

The bundle plugin (``scripts/_bundle_plugin/hermes_bundle_report.py``) writes, per
file, its ``collect`` seconds, one ``test`` line per phase (``w``: setup / call /
teardown; a phase of 10 ms or more carries its node id) and one ``diag`` line (the
processes its tests started by program kind with the main thread's wait on them,
the seconds inside plugin discovery, the main thread's sleeps). This module folds
those lines into :class:`FileDiag` rows, Σ over every process that ran the file (a
re-run and each shard included: it is what the file cost the run), and:

* ``run_record`` — the totals for the run's ``runs.jsonl`` line;
* ``append`` — one ``diagnosis.jsonl`` line per file beside it in the gate store;
* ``render`` — the ``=== Diagnosis ===`` block after Run cost: the top files by
  each column.

No profiler: every number is a pytest phase duration, an audit event or a wrapped
call (owner, q-runner step 6, 2026-10-17).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

#: the callable whose seconds the ``plugins`` column counts (``--hermes-diag-wrap``)
PLUGIN_DISCOVERY = "hermes_cli.plugins:PluginManager.discover_and_load"
PLUGIN_ARGS = (f"--hermes-diag-wrap={PLUGIN_DISCOVERY}",)
PHASES = ("setup", "call", "teardown")
SPAWN_KINDS = ("python", "git", "other")
SLOWEST = 5
TOP = 20
DIAGNOSIS_FILE = "diagnosis.jsonl"
#: past this, ``diagnosis.jsonl`` moves to ``diagnosis.prev.jsonl`` before the next run appends
ROTATE_BYTES = 32 << 20


@dataclass
class FileDiag:
    collect: float = 0.0
    phases: Dict[str, float] = field(default_factory=lambda: dict.fromkeys(PHASES, 0.0))
    #: (seconds, node id, phase), the slowest first, at most ``SLOWEST``
    slowest: List[Tuple[float, str, str]] = field(default_factory=list)
    spawn: Dict[str, List[float]] = field(default_factory=dict)  # kind -> [count, wait seconds]
    plugins: float = 0.0
    sleep: float = 0.0

    def columns(self) -> Dict[str, float]:
        out = {"collect": self.collect, **self.phases}
        for kind in SPAWN_KINDS:
            out[f"spawn_{kind}_s"] = self.spawn.get(kind, [0, 0.0])[1]
        out.update(plugins=self.plugins, sleep=self.sleep)
        return out

    def line(self, rel: str, run: str) -> dict:
        r3 = lambda s: round(s, 3)  # noqa: E731
        return {
            "run": run, "f": rel, "collect": r3(self.collect), **{p: r3(s) for p, s in self.phases.items()},
            "slowest": [[node, phase, r3(s)] for s, node, phase in self.slowest],
            "spawn": {k: [int(v[0]), r3(v[1])] for k, v in sorted(self.spawn.items())},
            "plugins": r3(self.plugins), "sleep": r3(self.sleep),
        }


def _on_collect(rows: Dict[str, FileDiag], record: dict) -> None:
    rows.setdefault(record["f"], FileDiag()).collect += float(record.get("d") or 0.0)


def _on_test(rows: Dict[str, FileDiag], record: dict) -> None:
    row = rows.setdefault(record["f"], FileDiag())
    phase, seconds = record.get("w") or "call", float(record.get("d") or 0.0)
    row.phases[phase] = row.phases.get(phase, 0.0) + seconds
    if record.get("n"):
        row.slowest = sorted(row.slowest + [(seconds, record["n"], phase)], key=lambda e: (-e[0], e[1]))[:SLOWEST]


def _on_diag(rows: Dict[str, FileDiag], record: dict) -> None:
    row = rows.setdefault(record["f"], FileDiag())
    for kind, (count, wait) in (record.get("spawn") or {}).items():
        entry = row.spawn.setdefault(kind, [0, 0.0])
        entry[0] += int(count)
        entry[1] += float(wait)
    row.plugins += float(record.get("wrapped") or 0.0)
    row.sleep += float(record.get("sleep") or 0.0)


_HANDLERS = {"collect": _on_collect, "test": _on_test, "diag": _on_diag}


def fold(lines: Iterable[str], rows: Optional[Dict[str, FileDiag]] = None) -> Dict[str, FileDiag]:
    """Add one events file's lines to ``rows`` (a torn last line is skipped)."""

    rows = {} if rows is None else rows
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        handler = _HANDLERS.get(record.get("k")) if isinstance(record, dict) and record.get("f") else None
        if handler is not None:
            handler(rows, record)
    return rows


class Diagnosis:
    """The run's rows, added to from every worker thread."""

    def __init__(self) -> None:
        self.rows: Dict[str, FileDiag] = {}
        self._lock = threading.Lock()

    def add(self, lines: Iterable[str]) -> None:
        with self._lock:
            fold(lines, self.rows)


def run_record(diagnosis: Optional[Diagnosis]) -> dict:
    """The ``runs.jsonl`` keys: Σ of each column over the run's files."""

    if diagnosis is None or not diagnosis.rows:
        return {}
    totals: Dict[str, float] = {}
    for row in diagnosis.rows.values():
        for column, seconds in row.columns().items():
            totals[column] = totals.get(column, 0.0) + seconds
    spawns = {k: sum(int(r.spawn.get(k, [0])[0]) for r in diagnosis.rows.values()) for k in SPAWN_KINDS}
    return {"diagnosis": {"files": len(diagnosis.rows), "seconds": {k: round(v, 1) for k, v in totals.items()},
                          "spawns": spawns, "file": DIAGNOSIS_FILE}}


def append(store_root: Path, run_id: str, diagnosis: Optional[Diagnosis]) -> Optional[Path]:
    """One ``diagnosis.jsonl`` line per file, beside ``runs.jsonl``."""

    if diagnosis is None or not diagnosis.rows:
        return None
    path = Path(store_root) / DIAGNOSIS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size > ROTATE_BYTES:
        path.replace(path.with_name("diagnosis.prev.jsonl"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for rel in sorted(diagnosis.rows):
            handle.write(json.dumps(diagnosis.rows[rel].line(rel, run_id), sort_keys=True) + "\n")
    return path


def render(diagnosis: Optional[Diagnosis], top: int = TOP) -> List[str]:
    """The ``=== Diagnosis ===`` block: per column, the top files by its seconds."""

    if diagnosis is None or not diagnosis.rows:
        return []
    lines = ["", f"=== Diagnosis (top {top} files per column; Σ over every process that ran the file) ==="]
    columns = {rel: row.columns() for rel, row in diagnosis.rows.items()}
    for column in next(iter(columns.values())):
        ranked = sorted(((c[column], rel) for rel, c in columns.items() if c[column] >= 0.05), reverse=True)[:top]
        if not ranked:
            continue
        lines.append(f"  {column}:")
        for seconds, rel in ranked:
            extra = ""
            if column.startswith("spawn_"):
                extra = f"  ({int(diagnosis.rows[rel].spawn[column.split('_')[1]][0])} spawned)"
            elif column == "call" and diagnosis.rows[rel].slowest:
                s, node, phase = diagnosis.rows[rel].slowest[0]
                extra = f"  (slowest {node.split('::', 1)[-1]} {phase} {s:.1f}s)"
            lines.append(f"    {seconds:8.1f}s  {rel}{extra}")
    return lines
