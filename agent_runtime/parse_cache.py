"""Process-wide, mtime-keyed parse cache for hot, idempotent file loads.

Snapshot builds resolve every persona's profile/skill/config state, and each
persona summary re-resolves the same profile + skill tree several times (readiness
+ four tool-visibility passes). Those leaf loads — YAML config/meta files, skill
frontmatter, file hashes — are pure functions of file content, so re-parsing them
dozens of times per build is wasted work (profiled as the dominant snapshot cost:
YAML scanning ≫ everything else).

This caches by ``(path, device, inode, ctime_ns, mtime_ns, size)`` so a file edit invalidates the entry
(safe in a long-lived daemon) while repeats within a build are free. Caches are
bounded and self-clearing.

**The disk tier (D1.05 CF-2).** The memo is per process, so every new process
(a serve boot, each CLI child) paid every parse again: ~2,000 SKILL.md
frontmatter parses, ~4.8 s, on the operator's store. A :class:`DiskTier` under
the memo, for ONE loader family at a time, persists ``{path: [stamp, value]}``
to ``<store_root>/derived_cache/<file>``: loaded once per process on the first
memo miss, validated per entry by the SAME stamp the memo keys on (a stale
entry misses and re-parses), written back only by :meth:`DiskTier.flush`, which
the family's owner schedules on an idle path -- never the turn thread. A value
that does not survive a JSON round trip unchanged (a YAML date, an int key) is
served from memory and never persisted, so a disk hit is always the value a
fresh parse would return.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

__layer__ = "models"

_MISSING = object()
_MAX_ENTRIES = 4096

_value_cache: dict[tuple, Any] = {}
_sha_cache: dict[tuple, str] = {}


def _stamp(path: Path) -> tuple | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_dev, st.st_ino, st.st_ctime_ns, st.st_mtime_ns, st.st_size)


def _bounded_set(cache: dict, key: tuple, value: Any) -> None:
    if len(cache) >= _MAX_ENTRIES:
        cache.clear()
    cache[key] = value


def cached_by_mtime(
    path: Path, loader: Callable[[Path], Any], *, default: Any = None, disk: "DiskTier | None" = None,
) -> Any:
    """Return ``loader(path)``, memoized by the file's identity+mtime.

    On a missing file or loader error, returns ``default`` (and does not cache,
    so a transient error self-heals on the next call). With ``disk``, a memo
    miss asks that cross-process tier before calling ``loader``, and a fresh
    load is offered back to it.
    """

    key = _stamp(path)
    if key is None:
        return default
    cached = _value_cache.get(key, _MISSING)
    if cached is not _MISSING:
        return cached
    if disk is not None:
        stored = disk.get(key)
        if stored is not _MISSING:
            _bounded_set(_value_cache, key, stored)
            return stored
    try:
        value = loader(path)
    except Exception:
        return default
    _bounded_set(_value_cache, key, value)
    if disk is not None:
        disk.put(key, value)
    return value


#: Bump when the on-disk shape changes; a file with another version is ignored.
DISK_TIER_VERSION = 1

#: Past this many entries a flush drops the ones whose file is gone.
_DISK_TIER_PRUNE_AT = 16384

_DISK_TIERS: list["DiskTier"] = []


def _derived_cache_target(filename: str) -> Path | None:
    try:
        from agent_runtime import paths

        return paths.derived_cache_dir() / filename
    except Exception:  # an unresolvable / probe-fenced store root: no disk tier
        return None


def _read_disk_entries(target: Path) -> dict[str, Any]:
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict) or raw.get("version") != DISK_TIER_VERSION:
        return {}
    entries = raw.get("entries")
    return entries if isinstance(entries, dict) else {}


class DiskTier:
    """A cross-process tier under :func:`cached_by_mtime` for ONE loader family.

    ``filename`` names the family's file under ``paths.derived_cache_dir()``,
    resolved on every memo miss (a process that changes store root reads and
    writes the new one). ``on_dirty`` is called after a fresh load is recorded:
    the owner uses it to schedule :meth:`flush` on its idle path. Never raises.
    """

    def __init__(self, filename: str, *, on_dirty: Callable[[], Any] | None = None):
        self.filename = filename
        self._on_dirty = on_dirty
        self._lock = threading.Lock()
        self._target: Path | None = None
        self._entries: dict[str, Any] = {}
        self._delta: dict[str, Any] = {}
        _DISK_TIERS.append(self)

    def _bind(self) -> Path | None:
        """Point at the current store root's file; load it on a change (lock held)."""

        target = _derived_cache_target(self.filename)
        if target != self._target:
            self._target = target
            self._entries = _read_disk_entries(target) if target is not None else {}
            self._delta = {}
        return target

    def get(self, key: tuple) -> Any:
        """The stored value for this exact stamp, else the module's miss sentinel."""

        try:
            with self._lock:
                if self._bind() is None:
                    return _MISSING
                row = self._entries.get(key[0])
        except Exception:
            return _MISSING
        if isinstance(row, list) and len(row) == 2 and row[0] == list(key[1:]):
            return row[1]
        return _MISSING

    def put(self, key: tuple, value: Any) -> None:
        try:
            if json.loads(json.dumps(value)) != value:
                return  # would come back different from a fresh parse: memory only
        except (TypeError, ValueError):
            return
        try:
            with self._lock:
                if self._bind() is None:
                    return
                row = [list(key[1:]), value]
                self._entries[key[0]] = row
                self._delta[key[0]] = row
            if self._on_dirty is not None:
                self._on_dirty()
        except Exception:
            return

    def flush(self) -> bool:
        """Merge this process's fresh loads into the file; True when it wrote.

        Re-reads the file first, so a second process's flush is merged, not
        overwritten. A failed write keeps the delta for the next flush.
        """

        with self._lock:
            target, delta = self._target, dict(self._delta)
        if target is None or not delta:
            return False
        if not target.parent.parent.is_dir():  # never create a store root out of nothing
            return False
        merged = _read_disk_entries(target)
        merged.update(delta)
        if len(merged) > _DISK_TIER_PRUNE_AT:
            merged = {path: row for path, row in merged.items() if os.path.exists(path)}
        try:
            from utils import atomic_json_write

            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_json_write(target, {"version": DISK_TIER_VERSION, "entries": merged},
                              indent=None, separators=(",", ":"))
        except Exception:
            return False
        with self._lock:
            if self._target == target:
                self._entries.update(merged)
                for path, row in delta.items():
                    if self._delta.get(path) is row:
                        del self._delta[path]
        return True

    def reset(self) -> None:
        """Forget the loaded file and any unflushed loads (tests / explicit invalidation)."""

        with self._lock:
            self._target = None
            self._entries = {}
            self._delta = {}


def cached_yaml_file(path: Path, *, default: Any = None) -> Any:
    """mtime-cached ``yaml_io.load`` of a file. Returns ``default`` if absent/bad."""

    def _load(p: Path) -> Any:
        from agent_runtime import yaml_io

        return yaml_io.load(p.read_text(encoding="utf-8"))

    return cached_by_mtime(path, _load, default=default)


def cached_file_sha256(path: Path) -> str:
    """mtime-cached SHA-256 of a file (same ``sha256:<hex>`` shape as the original).

    Falls back to a direct (uncached) hash when the file cannot be stat'd, so the
    original FileNotFoundError semantics are preserved for callers that don't
    guard existence.
    """

    key = _stamp(path)
    if key is not None:
        hit = _sha_cache.get(key)
        if hit is not None:
            return hit
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = "sha256:" + digest.hexdigest()
    if key is not None:
        _bounded_set(_sha_cache, key, value)
    return value


def clear_parse_cache() -> None:
    """Drop all cached entries (tests / explicit invalidation).

    Disk tiers forget their loaded file and unflushed loads; the files on disk
    stay (each entry is validated by its stamp, so a kept file is never wrong).
    """

    _value_cache.clear()
    _sha_cache.clear()
    for tier in _DISK_TIERS:
        tier.reset()
