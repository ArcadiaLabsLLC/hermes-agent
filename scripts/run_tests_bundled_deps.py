"""The dependency records one run's processes wrote, per test file (fast-gate §1).

Moved out of ``scripts/run_tests_bundled_cache.py`` (size ceiling, q-runner 2026-10-18),
which re-exports every name: ``FileDeps``, ``DepsCollector``, ``uncovered_spawn``.
The recorder that writes these lines is ``scripts/_bundle_plugin/hermes_dep_record.py``.
Pure: no sibling imports.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Optional


def uncovered_spawn(spawn_py: int, spawn_other: int, child_records: int) -> bool:
    """Whether a file spawned a process whose dependencies are not on record:
    the file then depends on the whole tree (the ALL sentinel). A non-Python
    program is never on record; a Python child is when it wrote its own record
    (``sitecustomize``), so the file is covered only when the records number at
    least the Python spawns, counted over the file and all its children."""

    return bool(spawn_other) or child_records < spawn_py


# ── Dependency records out of one run ───────────────────────────────────────


@dataclass
class FileDeps:
    """Everything the processes of one run recorded for one test file."""

    paths: set = field(default_factory=set)
    dirs: set = field(default_factory=set)
    mods: set = field(default_factory=set)
    #: directories the import system listed, and the name sets of the processes that ran the file:
    #: each process's set is shared and still growing until its file is read to the end
    idirs: set = field(default_factory=set)
    name_sets: list = field(default_factory=list)
    spawn_py: int = 0
    spawn_other: int = 0
    #: records written by Python children that inherited the file (stage 1b)
    child_records: int = 0
    #: fixtures the file's tests set up (``fx``), and whether every record of it said so
    fixtures: set = field(default_factory=set)
    fx_records: int = 0
    deps_records: int = 0
    #: paths the file itself opened (not the session's imports), and what its children touched:
    #: both stay keyed by their whole blob (``run_tests_bundled_fixtures``)
    own: set = field(default_factory=set)
    opaque: set = field(default_factory=set)
    #: the modules the file itself first loaded (``mods_own``, a child's whole set included) and the
    #: ones its test module names (``mods_ref``), and how many deps records carried them: read by
    #: ``--affected`` only, never by a key
    mods_own: set = field(default_factory=set)
    mods_ref: set = field(default_factory=set)
    own_records: int = 0

    @property
    def spawned(self) -> bool:
        return bool(self.spawn_py or self.spawn_other)

    @property
    def inames(self) -> set:
        """Every module name a process that ran the file tried to import (a superset of the file's own)."""

        return set().union(*self.name_sets) if self.name_sets else set()

    def note_names(self, names: set) -> None:
        if not any(found is names for found in self.name_sets):
            self.name_sets.append(names)

    @property
    def own_known(self) -> bool:
        """Every deps record of the file said which modules it loaded itself."""

        return bool(self.deps_records) and self.own_records == self.deps_records

    @property
    def fx(self) -> Optional[list[str]]:
        """The fixtures the file set up, or None when a record did not say (the blob key applies)."""

        known = self.deps_records and self.fx_records == self.deps_records
        return sorted(self.fixtures) if known else None

    def merge(self, record: dict, mods: Iterable[str]) -> None:
        self.paths.update(record.get("paths") or ())
        self.dirs.update(record.get("dirs") or ())
        self.idirs.update(record.get("idirs") or ())
        self.mods.update(mods)
        self.spawn_py += int(record.get("spawn_py") or 0)
        self.spawn_other += int(record.get("spawn_other") or 0)

    def merge_deps(self, record: dict, mods: Iterable[str]) -> None:
        """One ``deps`` line of the test process (its fixtures and own opens, when recorded)."""

        self.merge(record, mods)
        self.deps_records += 1
        if isinstance(record.get("fx"), list):
            self.fx_records += 1
            self.fixtures.update(record["fx"])
        self.own.update(record.get("own") or ())
        if isinstance(record.get("mods_own"), list):
            self.own_records += 1
            self.mods_own.update(record["mods_own"])
            self.mods_ref.update(record.get("mods_ref") or ())

    def merge_child(self, record: dict) -> None:
        """One ``child`` line: a Python child's paths and modules are never fingerprinted."""

        mods = record.get("mods") or ()
        self.merge(record, mods)
        self.child_records += 1
        self.opaque.update(record.get("paths") or ())
        self.opaque.update(mods)
        self.mods_own.update(mods)

    @property
    def child_covered(self) -> bool:
        """Every process the file started left a record (stage 1b)."""

        return not uncovered_spawn(self.spawn_py, self.spawn_other, self.child_records)


class DepsCollector:
    """Reads the recorder's per-process files under one directory, incrementally:
    each call consumes the complete lines written since the last call, so the
    runner can read a file's record as soon as its process has finished."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.files: dict[str, FileDeps] = {}
        #: what each file reached by the end of its collection (``partial`` lines): the
        #: record of a file whose process was killed before its ``deps`` line
        self.partial: dict[str, FileDeps] = {}
        self._offsets: dict[str, int] = {}
        self._mods: dict[str, set] = {}
        self._names: dict[str, set] = {}

    def poll(self) -> dict[str, FileDeps]:
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
        names = self._names.setdefault(name, set())
        for line in data[: end + 1].splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict) or not record.get("f"):
                continue
            handler = _RECORD_HANDLERS.get(record.get("k"))
            if handler is not None:
                names.update(record.get("inames_add") or ())
                handler(self, record, mods, names)

    def _on_deps(self, record: dict, mods: set, names: set) -> None:
        mods.update(record.get("mods_add") or ())
        entry = self.files.setdefault(record["f"], FileDeps())
        entry.merge_deps(record, mods)
        entry.note_names(names)

    def _on_partial(self, record: dict, mods: set, names: set) -> None:
        mods.update(record.get("mods_add") or ())
        entry = self.partial.setdefault(record["f"], FileDeps())
        entry.merge(record, mods)
        entry.note_names(names)

    def _on_child(self, record: dict, mods: set, names: set) -> None:
        """A Python child of the file (sitecustomize, stage 1b)."""

        self.files.setdefault(record["f"], FileDeps()).merge_child(record)


#: one handler per recorder line kind (``k``); an unknown kind is skipped
_RECORD_HANDLERS = {
    "deps": DepsCollector._on_deps,
    "partial": DepsCollector._on_partial,
    "child": DepsCollector._on_child,
}
