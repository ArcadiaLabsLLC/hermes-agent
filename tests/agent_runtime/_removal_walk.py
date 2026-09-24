"""One import walk of the production tree, shared by the removal-contract gates.

WHY. The removal gates ``test_s27_snapshot_orphan_tree_removal``,
``test_s29_snapshot_dead_local_removal``, ``test_s49_operator_control_removal``
and ``test_s50_launcher_process_hygiene_removal`` each asked the same question
of the same ~1,000 production files — "what does this file import, and which
attributes does it read off what it imported" — and each answered it by
parsing every file into a full AST: 18–20 s per gate file, measured 2026-09-24
(``docs/agent-runtime-harness/planned/suite-cost-centres-2026-09-24.md`` §2).
The ASTs were then held until a family of four modules finished (785 MB for
the tree, ``_tree_index.py``'s lifetime note), all to read a few thousand
import statements.

WHAT. This module extracts, per file, only what those gates read:

* every ``import`` / ``from … import`` statement (kind, module, level, the
  aliases, the line) — at any depth, function bodies included;
* every ``name.attr`` attribute LOAD whose ``name`` is bound by a first-party
  import in that file (``from agent_runtime import snapshot`` → ``snapshot.X``);
* whether the file decodes as strict UTF-8, and whether it parses at all.

Records are memoized for the life of the process — they are small, so unlike
``_tree_index`` nothing needs clearing between modules, and under the bundled
runner every gate in one process shares one walk — and persisted to
``<repo>/.pytest_cache/hermes-removal-walk/`` keyed per file on
``(mtime_ns, size)`` and on this module's own bytes, so a later process (or a
later run in the same checkout) re-parses only the files that changed. An
edited file changes its stamp and is re-read; an edited extractor changes the
key and discards the whole store.

WHAT IT IS NOT. Not an enumeration authority, on the same ruling as
``_tree_index``: each gate keeps its own walk, package list, skip list and
anti-vacuity assertion, and hands this module the paths it chose.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import tempfile
import threading
import warnings
from pathlib import Path
from typing import Iterable, NamedTuple, Optional

__all__ = ["Alias", "ImportRecord", "FileImports", "index", "cache_dir", "clear_memory"]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STORE_NAME = "imports-v1.json"


class Alias(NamedTuple):
    name: str
    asname: Optional[str]


class ImportRecord(NamedTuple):
    """One import statement. Duck-types the ``ast.ImportFrom`` / ``ast.Import``
    fields the gates read (``module``, ``level``, ``names``, ``lineno``)."""

    kind: str  # "from" | "import"
    module: Optional[str]
    level: int
    names: tuple[Alias, ...]
    lineno: int


class FileImports(NamedTuple):
    imports: tuple[ImportRecord, ...]
    attribute_loads: tuple[tuple[str, str, int], ...]  # (bound name, attr, line)
    decode_ok: bool


def _extractor_key() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]


_KEY = _extractor_key()
_lock = threading.Lock()
#: abs path -> (stamp, FileImports | None)
_memory: dict[str, tuple[tuple[int, int], Optional[FileImports]]] = {}
_disk_loaded = False


def cache_dir() -> Path:
    return _REPO_ROOT / ".pytest_cache" / "hermes-removal-walk"


def clear_memory() -> None:
    """Forget the in-process memo (the disk store is untouched). For tests."""

    global _disk_loaded
    with _lock:
        _memory.clear()
        _disk_loaded = False


def _first_party_tops(root: Path) -> frozenset[str]:
    tops = set()
    for entry in os.scandir(root):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            tops.add(entry.name)
        elif entry.name.endswith(".py"):
            tops.add(entry.name[:-3])
    return frozenset(tops)


_FIRST_PARTY = _first_party_tops(_REPO_ROOT)


def _stamp(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def _extract(path: str) -> Optional[FileImports]:
    raw = Path(path).read_bytes()
    try:
        raw.decode("utf-8")
        decode_ok = True
    except UnicodeDecodeError:
        decode_ok = False
    try:
        with warnings.catch_warnings():
            # A production file's own invalid escape is not this walk's finding.
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(raw.decode("utf-8", errors="replace"))
    except SyntaxError:
        return None
    imports: list[ImportRecord] = []
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = tuple(Alias(a.name, a.asname) for a in node.names)
            imports.append(ImportRecord("from", node.module, node.level, names, node.lineno))
            top = (node.module or "").split(".", 1)[0]
            if node.level > 0 or top in _FIRST_PARTY:
                bound.update(a.asname or a.name for a in node.names if a.name != "*")
        elif isinstance(node, ast.Import):
            names = tuple(Alias(a.name, a.asname) for a in node.names)
            imports.append(ImportRecord("import", None, 0, names, node.lineno))
            for alias in node.names:
                if alias.name.split(".", 1)[0] in _FIRST_PARTY:
                    bound.add(alias.asname or alias.name.split(".", 1)[0])
    loads: list[tuple[str, str, int]] = []
    if bound:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.ctx, ast.Load)
                and isinstance(node.value, ast.Name)
                and node.value.id in bound
            ):
                loads.append((node.value.id, node.attr, node.lineno))
    imports.sort(key=lambda r: (r.lineno, r.kind))
    return FileImports(tuple(imports), tuple(loads), decode_ok)


def _to_json(record: Optional[FileImports]):
    if record is None:
        return None
    return {
        "i": [[r.kind, r.module, r.level, [list(a) for a in r.names], r.lineno] for r in record.imports],
        "a": [list(t) for t in record.attribute_loads],
        "u": record.decode_ok,
    }


def _from_json(data) -> Optional[FileImports]:
    if data is None:
        return None
    imports = tuple(
        ImportRecord(kind, module, level, tuple(Alias(n, a) for n, a in names), lineno)
        for kind, module, level, names, lineno in data["i"]
    )
    return FileImports(imports, tuple(tuple(t) for t in data["a"]), bool(data["u"]))


def _read_store() -> dict:
    try:
        payload = json.loads((cache_dir() / _STORE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("key") != _KEY:
        return {}
    files = payload.get("files")
    return files if isinstance(files, dict) else {}


def _write_store(entries: dict) -> None:
    directory = cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        merged = _read_store()
        merged.update(entries)
        fd, tmp = tempfile.mkstemp(prefix="imports-", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"key": _KEY, "files": merged}, handle)
        os.replace(tmp, directory / _STORE_NAME)
    except OSError:
        # A cache that cannot be written is a slower run, never a wrong one.
        pass


def index(paths: Iterable[Path | str]) -> dict[str, Optional[FileImports]]:
    """``{str(path): FileImports | None}`` for every path given (``None`` = the
    file does not parse). Misses are extracted once and persisted together."""

    global _disk_loaded
    wanted = [str(p) for p in paths]
    out: dict[str, Optional[FileImports]] = {}
    missing: list[tuple[str, tuple[int, int]]] = []
    with _lock:
        disk = None
        for path in wanted:
            stamp = _stamp(path)
            hit = _memory.get(path)
            if hit is not None and hit[0] == stamp:
                out[path] = hit[1]
                continue
            if not _disk_loaded:
                disk = _read_store()
                _disk_loaded = True
                for key, (disk_stamp, data) in disk.items():
                    _memory.setdefault(key, (tuple(disk_stamp), _from_json(data)))
                hit = _memory.get(path)
                if hit is not None and hit[0] == stamp:
                    out[path] = hit[1]
                    continue
            missing.append((path, stamp))
        fresh: dict[str, list] = {}
        for path, stamp in missing:
            record = _extract(path)
            _memory[path] = (stamp, record)
            out[path] = record
            fresh[path] = [list(stamp), _to_json(record)]
    if fresh:
        _write_store(fresh)
    return out
