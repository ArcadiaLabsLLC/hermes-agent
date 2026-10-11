"""The green-result cache's store and dependency records (fast-gate §1).

``docs/agent-runtime-harness/planned/fast-gate-2026-10-10.md`` §1: a test file is
skipped when nothing it depends on has changed since its last green run on this
box, and the dependency set is RECORDED at run time
(``scripts/_bundle_plugin/hermes_dep_record.py``), never inferred.

This module is pure: no sibling imports, no fork path but the store's
directory name. ``scripts/run_tests_bundled_gate.py`` wires it into the runner.

The store lives per CLONE (owner ruling Q6): ``<primary checkout>/.pytest_cache/
hermes_gate/``, shared by every worktree, git-ignored, never committed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

#: bumped when the key's shape changes; part of every key
CACHE_SCHEMA = 1
STORE_SUBDIR = Path(".pytest_cache") / "hermes_gate"
STORE_ENV = "HERMES_GATE_CACHE_DIR"
#: compact a store file to its newest line per file past this size
COMPACT_BYTES = 4 << 20
MODSETS_COMPACT_BYTES = 32 << 20


def gate_store_dir(repo_root: Path, primary: Optional[Path], override: Optional[str] = None) -> Path:
    """The store: ``override`` (``--cache-dir`` / ``HERMES_GATE_CACHE_DIR``),
    else ``<primary or repo_root>/.pytest_cache/hermes_gate`` — so a landing
    worktree and its primary share one store, and the store outlives the
    worktree."""

    if override:
        return Path(override)
    return Path(primary or repo_root) / STORE_SUBDIR


# ── Dependency records out of one run ───────────────────────────────────────


@dataclass
class FileDeps:
    """Everything the processes of one run recorded for one test file."""

    paths: set = field(default_factory=set)
    dirs: set = field(default_factory=set)
    mods: set = field(default_factory=set)
    spawn_py: int = 0
    spawn_other: int = 0
    #: records written by Python children that inherited the file (stage 1b)
    child_records: int = 0

    @property
    def spawned(self) -> bool:
        return bool(self.spawn_py or self.spawn_other)

    def merge(self, record: dict, mods: Iterable[str]) -> None:
        self.paths.update(record.get("paths") or ())
        self.dirs.update(record.get("dirs") or ())
        self.mods.update(mods)
        self.spawn_py += int(record.get("spawn_py") or 0)
        self.spawn_other += int(record.get("spawn_other") or 0)


class DepsCollector:
    """Reads the recorder's per-process files under one directory, incrementally:
    each call consumes the complete lines written since the last call, so the
    runner can read a file's record as soon as its process has finished."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.files: Dict[str, FileDeps] = {}
        self._offsets: Dict[str, int] = {}
        self._mods: Dict[str, set] = {}

    def poll(self) -> Dict[str, FileDeps]:
        try:
            names = sorted(os.listdir(self.directory))
        except OSError:
            return self.files
        for name in names:
            if name.endswith(".jsonl"):
                self._consume(name)
        return self.files

    def _consume(self, name: str) -> None:
        try:
            with open(self.directory / name, "rb") as handle:
                handle.seek(self._offsets.get(name, 0))
                data = handle.read()
        except OSError:
            return
        end = data.rfind(b"\n")
        if end < 0:
            return
        self._offsets[name] = self._offsets.get(name, 0) + end + 1
        mods = self._mods.setdefault(name, set())
        for line in data[: end + 1].splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict) or not record.get("f"):
                continue
            if record.get("k") == "deps":
                mods.update(record.get("mods_add") or ())
                self.files.setdefault(record["f"], FileDeps()).merge(record, mods)


# ── The store ───────────────────────────────────────────────────────────────


def _digest(paths: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(paths)).encode("utf-8")).hexdigest()[:32]


def _pack(paths: Iterable[str]) -> str:
    return base64.b64encode(zlib.compress("\n".join(sorted(paths)).encode("utf-8"), 9)).decode("ascii")


def _unpack(blob: str) -> List[str]:
    text = zlib.decompress(base64.b64decode(blob)).decode("utf-8")
    return text.split("\n") if text else []


def _read_jsonl(path: Path) -> List[dict]:
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # a torn line from a killed run
        if isinstance(record, dict):
            out.append(record)
    return out


def _append_lines(path: Path, records: Iterable[dict]) -> None:
    payload = "".join(json.dumps(r, sort_keys=True) + "\n" for r in records)
    if not payload:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)


@dataclass
class StoredDeps:
    """A file's newest dependency line, its module sets resolved."""

    rel: str
    paths: List[str]
    dirs: List[str]
    mods: List[str]  # modset digests
    spawn_py: int
    spawn_other: int
    child_records: int
    run: str


class GateStore:
    """``<store>/``: ``deps.jsonl`` + ``modsets.jsonl`` (what each file
    depends on), ``green.jsonl`` (its last green and the key it ran under),
    ``runs.jsonl`` (the run record, ex ``.pytest_cache/hermes_bundled_runs.jsonl``),
    ``durations.json`` (clean-pass seconds, rel-keyed) and ``generation``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.deps = self.root / "deps.jsonl"
        self.modsets = self.root / "modsets.jsonl"
        self.green = self.root / "green.jsonl"
        self.runs = self.root / "runs.jsonl"
        self.durations = self.root / "durations.json"
        self.generation_file = self.root / "generation"
        self._known_modsets: Optional[set] = None

    # ── deps ──

    def _modset_ids(self) -> set:
        if self._known_modsets is None:
            self._known_modsets = {r.get("id") for r in _read_jsonl(self.modsets)}
        return self._known_modsets

    def write_deps(self, entries: Dict[str, FileDeps], run_id: str) -> None:
        """One ``deps.jsonl`` line per file; its module set stored once by digest."""

        known = self._modset_ids()
        modsets, lines = [], []
        for rel, deps in sorted(entries.items()):
            digest = _digest(deps.mods)
            if digest not in known:
                known.add(digest)
                modsets.append({"id": digest, "z": _pack(deps.mods)})
            lines.append({
                "f": rel, "run": run_id, "paths": sorted(deps.paths), "dirs": sorted(deps.dirs),
                "mods": [digest], "spawn_py": deps.spawn_py, "spawn_other": deps.spawn_other,
                "child": deps.child_records,
            })
        _append_lines(self.modsets, modsets)
        _append_lines(self.deps, lines)

    def load_deps(self) -> Dict[str, StoredDeps]:
        out: Dict[str, StoredDeps] = {}
        for r in _read_jsonl(self.deps):
            rel = r.get("f")
            if not rel:
                continue
            out[rel] = StoredDeps(
                rel, list(r.get("paths") or ()), list(r.get("dirs") or ()), list(r.get("mods") or ()),
                int(r.get("spawn_py") or 0), int(r.get("spawn_other") or 0), int(r.get("child") or 0),
                str(r.get("run") or ""),
            )
        return out

    def load_modsets(self, wanted: Optional[Iterable[str]] = None) -> Dict[str, List[str]]:
        want = None if wanted is None else set(wanted)
        out: Dict[str, List[str]] = {}
        for r in _read_jsonl(self.modsets):
            digest = r.get("id")
            if digest and (want is None or digest in want) and digest not in out:
                try:
                    out[digest] = _unpack(r.get("z") or "")
                except (ValueError, zlib.error):
                    continue
        return out


def census(entries: Dict[str, FileDeps], seconds: Dict[str, float]) -> str:
    """Stage 1's line: how many files carry a record, how many spawned a process
    and what those cost — the number that decides whether stage 1b is next."""

    spawned = [rel for rel, deps in entries.items() if deps.spawned]
    cost = sum(float(seconds.get(rel) or 0.0) for rel in spawned)
    other = sum(1 for rel in spawned if entries[rel].spawn_other)
    return (
        f"  deps recorded for {len(entries)} files; {len(spawned)} spawned a process "
        f"(Σ {cost:.1f}s; {other} started a non-Python program)"
    )
