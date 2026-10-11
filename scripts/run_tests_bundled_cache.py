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
import fnmatch
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

#: bumped when the key's shape changes; part of every key
CACHE_SCHEMA = 1
STORE_SUBDIR = Path(".pytest_cache") / "hermes_gate"
STORE_ENV = "HERMES_GATE_CACHE_DIR"
#: tracked prefixes a file that spawned an unrecorded process may ignore (owner ruling Q1)
ALL_EXCLUDED_PREFIXES = ("Harness_Brain/", "docs/")
#: the runner's own inputs: a change to any of them changes every key
RUNNER_GLOBS = (
    "scripts/run_tests_bundled*.py", "scripts/_bundle_plugin/*", "scripts/run_tests_bundled.sh",
    "scripts/run_tests.sh", "scripts/run_tests_parallel.py", "scripts/_activation.sh",
    "scripts/ensure_fork_dev_deps.py", "scripts/test_*.txt",
    "tests/fixtures/upstream_skip_list.txt", "tests/fixtures/upstream_manifest.txt",
)
#: the interpreter's lock inputs
LOCK_FILES = ("uv.lock", "pyproject.toml", "requirements-fork-dev.txt")
#: passthrough pytest args that change only what is printed; any other disables the cache
OUTPUT_ONLY_ARGS = frozenset({"-q", "-qq", "-v", "-vv"})
#: runner-only knobs that never change what a test does
ENV_IGNORED = frozenset({"HERMES_TEST_WORKERS"})
ENV_NAMES = ("CI", "GITHUB_ACTIONS", "TZ", "LANG", "LC_ALL", "PYTHONHASHSEED", "PYTHONUTF8", "PYTEST_PLUGINS")
MISSING = "MISSING"
#: owner ruling Q2: a green older than this misses
DEFAULT_MAX_AGE_DAYS = 14.0
#: a file that was flaky, leaked or went unreached is cached again only after this many greens in a row
PROBATION_GREENS = 2
PROBATION_DROPS = frozenset({"flaky", "leak", "unreached"})


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
            elif record.get("k") == "child":  # a Python child of the file (sitecustomize, stage 1b)
                deps = self.files.setdefault(record["f"], FileDeps())
                deps.merge(record, record.get("mods") or ())
                deps.child_records += 1


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

    # ── greens and the generation ──

    def generation(self) -> int:
        try:
            return int(self.generation_file.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    def bump_generation(self) -> int:
        new = self.generation() + 1
        self.root.mkdir(parents=True, exist_ok=True)
        self.generation_file.write_text(f"{new}\n", encoding="utf-8")
        return new

    def skip_runs(self) -> int:
        """How many recorded runs skipped cached greens (the audit's 5 % → 2 % switch)."""

        return sum(1 for r in _read_jsonl(self.runs) if isinstance(r.get("cache"), dict) and r["cache"].get("skipped"))

    def drop_green(self, rels: Iterable[str], reason: str, run_id: str) -> None:
        """Supersede a file's green with a line that carries no key: it misses next time."""

        _append_lines(self.green, [{"f": rel, "drop": reason, "run": run_id} for rel in rels])

    def append_green(self, lines: Iterable[dict]) -> None:
        _append_lines(self.green, lines)

    def load_green(self) -> Dict[str, dict]:
        """rel → its newest ``green.jsonl`` line (a later line supersedes)."""

        return {r["f"]: r for r in _read_jsonl(self.green) if r.get("f")}

    # ── durations ──

    def load_durations(self) -> Dict[str, float]:
        try:
            data = json.loads(self.durations.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float))}

    def save_durations(self, seconds: Mapping[str, float]) -> None:
        """Merge clean-pass seconds into ``durations.json``: repo-relative POSIX
        keys only, so a test's temp file can never land in the planner's input."""

        data = self.load_durations()
        data.update({
            rel: round(float(s), 3) for rel, s in seconds.items()
            if not rel.startswith("/") and ":" not in rel and "\\" not in rel
        })
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.durations.with_name(f"durations.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.durations)

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
    covered = sum(1 for rel in spawned if entries[rel].child_covered)
    return (
        f"  deps recorded for {len(entries)} files; {len(spawned)} spawned a process "
        f"(Σ {cost:.1f}s; {other} started a non-Python program; {covered} fully recorded through their children)"
    )


# ── The tree a run starts from ──────────────────────────────────────────────

GitCall = Callable[..., str]


def git_blob_id(data: bytes) -> str:
    """The id git gives these bytes as a blob (no filters: this repo stores LF on disk)."""

    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class TreeSnapshot:
    """The blob of every path at the START of a run: ``git ls-files -s`` for
    clean tracked paths, hashed the git way for paths ``git status`` names
    (modified, untracked), so committing a file unchanged keeps its blob. A
    path neither tracked nor listed (git-ignored) is hashed from disk when
    asked; a path that does not exist is ``MISSING``."""

    def __init__(self, root: Path, index: Dict[str, str], changed: Iterable[str], head: str = "") -> None:
        self.root = Path(root)
        self.head = head
        self.blobs: Dict[str, str] = dict(index)
        for rel in changed:
            self.blobs[rel] = self._disk(rel)
        self.visible = {rel for rel, blob in self.blobs.items() if blob != MISSING}
        self._children: Optional[Dict[str, set]] = None
        self._all: Optional[str] = None
        self._dirs: Dict[str, str] = {}

    @classmethod
    def take(cls, root: Path, git: GitCall) -> "TreeSnapshot":
        index: Dict[str, str] = {}
        for entry in git(root, "ls-files", "-s", "-z").split("\0"):
            meta, _tab, rel = entry.partition("\t")
            if rel:
                index[rel] = meta.split()[1]
        changed: List[str] = []
        parts = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
        i = 0
        while i < len(parts):
            entry = parts[i]
            i += 1
            if len(entry) < 4:
                continue
            changed.append(entry[3:])
            if entry[0] in "RC" and i < len(parts):  # a rename's source follows as its own field
                changed.append(parts[i])
                i += 1
        try:
            head = git(root, "rev-parse", "HEAD").strip()
        except RuntimeError:
            head = ""
        return cls(root, index, changed, head)

    def _disk(self, rel: str) -> str:
        try:
            return git_blob_id((self.root / rel).read_bytes())
        except OSError:
            return MISSING

    def blob(self, rel: str) -> str:
        found = self.blobs.get(rel)
        if found is None:
            found = self.blobs[rel] = self._disk(rel)
        return found

    def dir_names(self, rel: str) -> str:
        """A listed directory as git sees it (tracked + untracked, never the
        ignored noise a run writes); a directory git cannot see is read from disk."""

        found = self._dirs.get(rel)
        if found is not None:
            return found
        if self._children is None:
            self._children = {}
            for path in self.visible:
                parts = path.split("/")
                for depth in range(len(parts)):
                    parent = "/".join(parts[:depth]) or "."
                    self._children.setdefault(parent, set()).add(parts[depth])
        names = self._children.get(rel)
        if names is None:
            try:
                names = {n for n in os.listdir(self.root / rel) if n not in ("__pycache__", ".pytest_cache")}
            except OSError:
                names = None
        found = self._dirs[rel] = MISSING if names is None else "/".join(sorted(names))
        return found

    def all_digest(self) -> str:
        """The ALL sentinel: every visible path and blob outside the excluded prefixes."""

        if self._all is None:
            h = hashlib.sha256()
            for rel in sorted(self.visible):
                if not rel.startswith(ALL_EXCLUDED_PREFIXES):
                    h.update(f"{rel}\t{self.blobs[rel]}\n".encode("utf-8"))
            self._all = h.hexdigest()
        return self._all


def _tool_version(argv: Sequence[str]) -> str:
    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "none"
    text = (proc.stdout or proc.stderr or "").strip()
    return text.splitlines()[0] if text else "none"


def interpreter_lines() -> List[str]:
    """The interpreter, its installed distributions, and the system tools a test may run."""

    import importlib.metadata as metadata

    dists = sorted({f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions() if d.metadata["Name"]})
    return [
        f"interp\tpython\t{sys.version}",
        f"interp\tplatform\t{platform.platform()}",
        f"interp\tdists\t{hashlib.sha256(chr(10).join(dists).encode('utf-8')).hexdigest()}",
        f"interp\tgit\t{_tool_version(['git', '--version'])}",
        f"interp\tnode\t{_tool_version(['node', '--version'])}",
    ]


def env_lines(environ: Mapping[str, str], strip_paths: Iterable[str] = ()) -> List[str]:
    """The environment a test process inherits from the runner, minus runner-only
    knobs and the per-checkout plugin directory on ``PYTHONPATH``."""

    strip = {os.path.normcase(os.path.abspath(p)) for p in strip_paths}
    out = []
    for name in sorted(environ):
        if name in ENV_IGNORED or name.startswith("HERMES_GATE_"):
            continue
        if name.startswith("HERMES_") or name in ENV_NAMES:
            out.append(f"env\t{name}={environ[name]}")
    entries = [p for p in environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    kept = [p for p in entries if os.path.normcase(os.path.abspath(p)) not in strip]
    out.append(f"env\tPYTHONPATH={os.pathsep.join(kept)}")
    return out


@dataclass
class FixedInputs:
    """The inputs every key of the run shares, and why the cache is off, if it is."""

    lines: List[str]
    disabled: str = ""

    @property
    def digest(self) -> str:
        return hashlib.sha256("\n".join(self.lines).encode("utf-8")).hexdigest()

    @classmethod
    def collect(
        cls, snapshot: TreeSnapshot, pytest_args: Sequence[str], environ: Mapping[str, str], *,
        strip_paths: Iterable[str] = (), interp: Optional[List[str]] = None,
    ) -> "FixedInputs":
        lines = [f"schema\t{CACHE_SCHEMA}"]
        lines += [
            f"runner\t{rel}\t{snapshot.blobs[rel]}"
            for rel in sorted(snapshot.visible) if any(fnmatch.fnmatchcase(rel, g) for g in RUNNER_GLOBS)
        ]
        lines += [f"lock\t{rel}\t{snapshot.blob(rel)}" for rel in LOCK_FILES]
        lines += interp if interp is not None else interpreter_lines()
        lines += env_lines(environ, strip_paths)
        extra = [a for a in pytest_args if a not in OUTPUT_ONLY_ARGS]
        lines.append(f"pytest\t{' '.join(extra)}")
        return cls(lines, f"pytest args {' '.join(extra)}" if extra else "")


# ── Keys ────────────────────────────────────────────────────────────────────


def uncovered_spawn(spawn_py: int, spawn_other: int, child_records: int) -> bool:
    """Whether a file spawned a process whose dependencies are not on record:
    the file then depends on the whole tree (the ALL sentinel). A non-Python
    program is never on record; a Python child is when it wrote its own record
    (``sitecustomize``), so the file is covered only when the records number at
    least the Python spawns, counted over the file and all its children."""

    return bool(spawn_other) or child_records < spawn_py


class Keyer:
    """``key(rel) = sha256`` over the file's recorded paths, listed directories,
    module sets and (when a spawned process went unrecorded) the ALL sentinel,
    each against the run's start snapshot, plus the fixed inputs."""

    def __init__(self, snapshot: TreeSnapshot, fixed: FixedInputs, modsets: Dict[str, List[str]]) -> None:
        self.snapshot = snapshot
        self.fixed = fixed
        self.modsets = modsets
        self._modset_hash: Dict[str, str] = {}

    def _mods(self, digest: str) -> str:
        found = self._modset_hash.get(digest)
        if found is None:
            paths = self.modsets.get(digest)
            if paths is None:
                return MISSING
            h = hashlib.sha256()
            for rel in paths:
                h.update(f"{rel}\t{self.snapshot.blob(rel)}\n".encode("utf-8"))
            found = self._modset_hash[digest] = h.hexdigest()
        return found

    def key(self, rel: str, paths: Iterable[str], dirs: Iterable[str], mods: Iterable[str], uncovered: bool) -> str:
        snap = self.snapshot
        lines = [f"path\t{p}\t{snap.blob(p)}" for p in sorted(set(paths) | {rel})]
        lines += [f"dir\t{d}\t{snap.dir_names(d)}" for d in sorted(set(dirs))]
        lines += [f"mods\t{self._mods(m)}" for m in sorted(set(mods))]
        if uncovered:
            lines.append(f"ALL\t{snap.all_digest()}")
        lines.append(f"fixed\t{self.fixed.digest}")
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()

    def key_stored(self, deps: "StoredDeps") -> str:
        return self.key(
            deps.rel, deps.paths, deps.dirs, deps.mods,
            uncovered_spawn(deps.spawn_py, deps.spawn_other, deps.child_records),
        )

    def key_fresh(self, rel: str, deps: FileDeps) -> str:
        digest = _digest(deps.mods)
        self.modsets.setdefault(digest, sorted(deps.mods))
        return self.key(
            rel, deps.paths, deps.dirs, [digest], uncovered_spawn(deps.spawn_py, deps.spawn_other, deps.child_records)
        )


# ── Greens and the decision ─────────────────────────────────────────────────


@dataclass
class GreenEntry:
    """A file's newest line in ``green.jsonl``: its last green and the key it ran under."""

    rel: str
    key: str
    run: str
    t: str
    epoch: float
    seconds: float
    gen: int
    head: str = ""
    #: greens in a row since a probation drop, and how many the file needs
    streak: int = 1
    needs: int = 1

    def line(self) -> dict:
        return {"f": self.rel, "key": self.key, "run": self.run, "t": self.t, "epoch": round(self.epoch, 1),
                "s": round(self.seconds, 2), "gen": self.gen, "head": self.head, "streak": self.streak,
                "needs": self.needs}

    @classmethod
    def from_line(cls, r: Mapping) -> Optional["GreenEntry"]:
        if not r.get("f") or not r.get("key"):
            return None
        return cls(r["f"], r["key"], str(r.get("run") or ""), str(r.get("t") or ""), float(r.get("epoch") or 0.0),
                   float(r.get("s") or 0.0), int(r.get("gen") or 0), str(r.get("head") or ""),
                   int(r.get("streak") or 1), int(r.get("needs") or 1))


@dataclass
class CacheDecision:
    """Per selected file: run it (and why) or skip it as cached green."""

    run: List[Path] = field(default_factory=list)
    cached: List[Tuple[Path, GreenEntry]] = field(default_factory=list)
    sampled: List[Path] = field(default_factory=list)
    reasons: Dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0

    def misses_by_reason(self) -> Counter:
        return Counter(reason for reason in self.reasons.values() if reason != "hit")


def rel_of(path: Path, repo_root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def streak_after(previous: Optional[Mapping]) -> Tuple[int, int]:
    """``(streak, needs)`` for a new green line given the file's previous line:
    after a flaky / leak / unreached drop the file needs two greens in a row."""

    if not previous:
        return 1, 1
    if previous.get("drop") in PROBATION_DROPS:
        return 1, PROBATION_GREENS
    if previous.get("key"):
        needs = int(previous.get("needs") or 1)
        return min(needs, int(previous.get("streak") or 1) + 1), needs
    return 1, 1


def decide(
    files: Sequence[Path], repo_root: Path, *, keyer: Optional[Keyer], disabled: str,
    deps: Mapping[str, StoredDeps], greens: Mapping[str, Mapping], generation: int,
    named: Iterable[Path] = (), known_reds: Iterable[str] = (),
    now: Optional[float] = None, max_age_days: float = DEFAULT_MAX_AGE_DAYS,
) -> CacheDecision:
    """Every selected file is a hit (cached green, key unchanged) or a miss with
    its reason. A disabled cache, a NAMED file, a known red, a file whose last
    run was red / flaky / a leak / unreached / a straggler retry, a file on
    probation and a green older than ``max_age_days`` always run."""

    started = time.monotonic()
    now = time.time() if now is None else now
    named_real = {Path(p).resolve() for p in named}
    known = set(known_reds)
    out = CacheDecision()
    for path in files:
        rel = rel_of(path, repo_root)
        line = greens.get(rel) or {}
        entry = GreenEntry.from_line(line)
        stored = deps.get(rel)
        if disabled or keyer is None:
            reason = f"off ({disabled or 'no keys'})"
        elif Path(path).resolve() in named_real:
            reason = "named"
        elif rel in known:
            reason = "known-red"
        elif entry is None:
            reason = str(line.get("drop") or "no-green")
        elif entry.gen < generation:
            reason = "generation"
        elif now - entry.epoch > max_age_days * 86400:
            reason = "max-age"
        elif entry.streak < entry.needs:
            reason = "probation"
        elif stored is None:
            reason = "no-deps"
        elif keyer.key_stored(stored) != entry.key:
            reason = "changed"
        else:
            reason = "hit"
        out.reasons[rel] = reason
        if reason == "hit":
            out.cached.append((path, entry))
        else:
            out.run.append(path)
    out.seconds = time.monotonic() - started
    return out


# ── The audit (stage 3) ─────────────────────────────────────────────────────

#: owner ruling Q2: 2 % of the hits, at least 25; 5 % for the first three skipping runs
SAMPLE_FRACTION = 0.02
SAMPLE_FRACTION_EARLY = 0.05
SAMPLE_EARLY_RUNS = 3
SAMPLE_MINIMUM = 25


def sample_fraction(prior_skip_runs: int) -> float:
    return SAMPLE_FRACTION_EARLY if prior_skip_runs < SAMPLE_EARLY_RUNS else SAMPLE_FRACTION


def audit_sample(hits: Sequence[str], seed: int, fraction: float = SAMPLE_FRACTION, minimum: int = SAMPLE_MINIMUM) -> List[str]:
    """The hits this run re-executes anyway: ``max(minimum, ceil(fraction × hits))``
    of them (all of them when there are fewer), drawn by ``random.Random(seed)``
    over the sorted hits, so a printed seed reproduces the sample."""

    pool = sorted(hits)
    size = min(len(pool), max(minimum, math.ceil(fraction * len(pool))))
    return sorted(random.Random(seed).sample(pool, size))


@dataclass
class AuditVerdict:
    #: cached-green files red in the run AND red again alone: the key missed a dependency
    defects: List[str] = field(default_factory=list)
    #: red in the run, green alone: a flake, never a cache defect
    flakes: List[str] = field(default_factory=list)


def audit_verdict(sampled: Iterable[str], final_rc: Mapping[str, int], rerun: Callable[[str], int]) -> AuditVerdict:
    """A sampled hit that came back red is run once more, alone (``rerun``):
    red again is a cache defect, green is a flake."""

    verdict = AuditVerdict()
    for rel in sorted(sampled):
        if final_rc.get(rel, 0) == 0:
            continue
        rc_alone = rerun(rel)
        (verdict.defects if rc_alone != 0 else verdict.flakes).append(rel)
    return verdict
