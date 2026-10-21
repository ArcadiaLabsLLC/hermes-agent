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
#: per-file test COUNTS (not seconds): a body that left monkeypatch entries, a late fixture that pushed
#: some (``bp`` on the call line, ``tests/_downstream/body_patch_scope.py``), a teardown that errored
COUNTS = ("body_patches", "late_fixture_patches", "teardown_errors")
#: node ids kept per file for ``teardown_errors``
ERROR_IDS = 20
#: past this, ``diagnosis.jsonl`` moves to ``diagnosis.prev.jsonl`` before the next run appends
ROTATE_BYTES = 32 << 20


@dataclass
class FileDiag:
    collect: float = 0.0
    phases: dict[str, float] = field(default_factory=lambda: dict.fromkeys(PHASES, 0.0))
    #: (seconds, node id, phase), the slowest first, at most ``SLOWEST``
    slowest: list[tuple[float, str, str]] = field(default_factory=list)
    spawn: dict[str, list[float]] = field(default_factory=dict)  # kind -> [count, wait seconds]
    plugins: float = 0.0
    sleep: float = 0.0
    body_patches: int = 0
    late_fixture_patches: int = 0
    teardown_errors: int = 0
    teardown_error_ids: list[str] = field(default_factory=list)

    def columns(self) -> dict[str, float]:
        out = {"collect": self.collect, **self.phases}
        for kind in SPAWN_KINDS:
            out[f"spawn_{kind}_s"] = self.spawn.get(kind, [0, 0.0])[1]
        out.update(plugins=self.plugins, sleep=self.sleep)
        return out

    def line(self, rel: str, run: str) -> dict:
        r3 = lambda s: round(s, 3)
        return {
            "run": run, "f": rel, "collect": r3(self.collect), **{p: r3(s) for p, s in self.phases.items()},
            "slowest": [[node, phase, r3(s)] for s, node, phase in self.slowest],
            "spawn": {k: [int(v[0]), r3(v[1])] for k, v in sorted(self.spawn.items())},
            "plugins": r3(self.plugins), "sleep": r3(self.sleep),
            **{c: getattr(self, c) for c in COUNTS}, "teardown_error_ids": list(self.teardown_error_ids),
        }


def _on_collect(rows: dict[str, FileDiag], record: dict) -> None:
    rows.setdefault(record["f"], FileDiag()).collect += float(record.get("d") or 0.0)


def _on_test(rows: dict[str, FileDiag], record: dict) -> None:
    row = rows.setdefault(record["f"], FileDiag())
    phase, seconds = record.get("w") or "call", float(record.get("d") or 0.0)
    row.phases[phase] = row.phases.get(phase, 0.0) + seconds
    if record.get("n"):
        row.slowest = sorted(row.slowest + [(seconds, record["n"], phase)], key=lambda e: (-e[0], e[1]))[:SLOWEST]
    bp = record.get("bp") or (0, 0, 0)
    row.body_patches += int(bool(bp[0] or bp[1]))
    row.late_fixture_patches += int(bool(bp[2]))
    if phase == "teardown" and record.get("c") == "error":
        row.teardown_errors += 1
        if record.get("n") and len(row.teardown_error_ids) < ERROR_IDS:
            row.teardown_error_ids.append(record["n"])


def _on_diag(rows: dict[str, FileDiag], record: dict) -> None:
    row = rows.setdefault(record["f"], FileDiag())
    for kind, (count, wait) in (record.get("spawn") or {}).items():
        entry = row.spawn.setdefault(kind, [0, 0.0])
        entry[0] += int(count)
        entry[1] += float(wait)
    row.plugins += float(record.get("wrapped") or 0.0)
    row.sleep += float(record.get("sleep") or 0.0)


_HANDLERS = {"collect": _on_collect, "test": _on_test, "diag": _on_diag}


def fold(lines: Iterable[str], rows: Optional[dict[str, FileDiag]] = None) -> dict[str, FileDiag]:
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
        self.rows: dict[str, FileDiag] = {}
        self._lock = threading.Lock()

    def add(self, lines: Iterable[str]) -> None:
        with self._lock:
            fold(lines, self.rows)


def run_record(diagnosis: Optional[Diagnosis]) -> dict:
    """The ``runs.jsonl`` keys: Σ of each column over the run's files."""

    if diagnosis is None or not diagnosis.rows:
        return {}
    totals: dict[str, float] = {}
    for row in diagnosis.rows.values():
        for column, seconds in row.columns().items():
            totals[column] = totals.get(column, 0.0) + seconds
    spawns = {k: sum(int(r.spawn.get(k, [0])[0]) for r in diagnosis.rows.values()) for k in SPAWN_KINDS}
    counts = {c: sum(getattr(r, c) for r in diagnosis.rows.values()) for c in COUNTS}
    return {"diagnosis": {"files": len(diagnosis.rows), "seconds": {k: round(v, 1) for k, v in totals.items()},
                          "spawns": spawns, "counts": counts, "file": DIAGNOSIS_FILE}}


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


def render(diagnosis: Optional[Diagnosis], top: int = TOP) -> list[str]:
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
    for column in COUNTS:
        ranked = sorted(((getattr(r, column), rel) for rel, r in diagnosis.rows.items() if getattr(r, column)),
                        reverse=True)[:top]
        if ranked:
            lines.append(f"  {column} (tests):")
            lines.extend(f"    {n:8d}   {rel}" for n, rel in ranked)
    return lines
