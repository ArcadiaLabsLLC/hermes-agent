"""Fingerprint cache for the declared-command scan (``RT-HARNESS-ARGV-MANIFEST-SCAN``).

Every ``hermes harness …`` process runs
:func:`hermes_cli.plugins_declared_cli.discover_declared_cli_commands`, which parses EVERY
directory ``plugin.yaml`` to find the one or two that declare ``cli_commands``. This module lets a
process skip that parse when no manifest file the upstream walk could read has changed:

- :func:`manifest_fingerprint` is an OVER-APPROXIMATING stat enumeration of the same roots the
  upstream walk (``plugins_discovery.collect_directory_manifests``) reads: every manifest-named file
  in every directory down to ``depth_cap`` below each root, with no skip list, no parse, no key rule.
  It answers only "which manifest files exist and when did they change"; the superset is the point,
  so any change upstream could observe changes the fingerprint.
- the cache file (``<HERMES_HOME>/cache/declared_cli_commands.json``) maps that fingerprint to the
  declaring winners (path, source, prefix, plugin key) — never to a gate verdict; the enable gate is
  always re-run live by the caller.

Malformed, schema-mismatched or unreadable cache files read as ``None`` (a miss). A cache that cannot be
written is a cache that always misses, never a broken CLI.

Pinned by ``tests/hermes_cli/test_plugin_declared_cli_commands.py`` (T1 is the positive superset gate).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

SCHEMA = 1
MANIFEST_FILE_NAMES = ("plugin.yaml", "plugin.yml", "plugin.json")
CACHE_RELPATH = "cache/declared_cli_commands.json"
_ROW_FIELDS = ("manifest_path", "plugin_dir", "source", "prefix", "plugin_key")


@dataclass(frozen=True)
class Fingerprint:
    """What the upstream walk could observe: the roots, the env flags that pick them, the files."""

    schema: int
    roots: tuple[tuple[str, str], ...]  # (source, root path), in scan order
    env: tuple[tuple[str, str], ...]
    files: tuple[tuple[str, int, int], ...]  # (path, size, mtime_ns), sorted

    def digest(self) -> str:
        body = json.dumps([self.schema, self.roots, self.env, self.files], separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachedRows:
    digest: str
    rows: tuple[dict, ...]  # one per declaring winner, in winner order; keys = _ROW_FIELDS


def _stat_row(path: str, entry: os.DirEntry) -> tuple[str, int, int]:
    try:
        st = entry.stat()
    except OSError:
        try:  # a dangling symlink still counts as present (upstream's ``is_symlink`` rule)
            st = entry.stat(follow_symlinks=False)
        except OSError:
            return (path, -1, -1)
    return (path, st.st_size, st.st_mtime_ns)


def _walk_manifests(directory: str, level: int, depth_cap: int, out: list) -> None:
    """Record manifest files in ``directory`` (``level`` below its root) and recurse to ``depth_cap``."""
    try:
        with os.scandir(directory) as it:
            entries = list(it)
    except OSError:
        return
    for entry in entries:
        if level >= 1 and entry.name in MANIFEST_FILE_NAMES:
            out.append(_stat_row(os.path.join(directory, entry.name), entry))
            continue
        if level < depth_cap:
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                _walk_manifests(os.path.join(directory, entry.name), level + 1, depth_cap, out)


def manifest_fingerprint(
    roots: Iterable[tuple[str, Path]], *, env: Iterable[tuple[str, str]] = (), depth_cap: int = 2,
) -> Fingerprint:
    """Stat every manifest-named file at most ``depth_cap`` directories below each root.

    ``depth_cap=2`` reaches ``<root>/<cat>/<name>/plugin.yaml``, the deepest file
    ``scan_directory`` parses."""
    roots = tuple((str(source), os.fspath(root)) for source, root in roots)
    files: list = []
    for _source, root in roots:
        _walk_manifests(root, 0, depth_cap, files)
    return Fingerprint(SCHEMA, roots, tuple((str(k), str(v)) for k, v in env), tuple(sorted(files)))


def cache_path(home: Path) -> Path:
    return Path(home) / CACHE_RELPATH


def read_cache(home: Path) -> Optional[CachedRows]:
    """The cached declaring winners, or None for a missing, malformed or other-schema file."""
    path = cache_path(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("digest"), str):
            raise ValueError("schema mismatch")
        rows = data.get("rows")
        if not isinstance(rows, list) or not all(
            isinstance(r, dict) and all(isinstance(r.get(f), str) for f in _ROW_FIELDS) for r in rows
        ):
            raise ValueError("malformed rows")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:  # json.JSONDecodeError is a ValueError
        logger.debug("declared_cli_cache unreadable at %s: %s", path, exc)
        return None
    return CachedRows(data["digest"], tuple({f: r[f] for f in _ROW_FIELDS} for r in rows))


def write_cache(home: Path, fingerprint: Fingerprint, rows: Iterable[dict]) -> bool:
    """Temp file + ``os.replace``; False (debug receipt) when the cache cannot be written."""
    path = cache_path(home)
    body = json.dumps({"schema": SCHEMA, "digest": fingerprint.digest(),
                       "rows": [{f: r[f] for f in _ROW_FIELDS} for r in rows]}, indent=1)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("declared_cli_cache unwritable at %s: %s", path, exc)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True
