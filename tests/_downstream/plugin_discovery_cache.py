"""Bundled-plugin DISCOVERY is kept between tests; plugin LOAD still runs fresh in every test.

``tests/conftest.py::_hermetic_environment`` resets every plugin manager before each test, so the first
``discover_plugins()`` of every test re-walked the bundled ``plugins/`` tree, re-parsed every bundled
``plugin.yaml`` with the pure-Python YAML parser, and re-read the installed entry points: the parse
alone was 29% of ``test_persona_assignments``' profiled CPU (r-perf-2026-10-17). Owner ruling
2026-10-10 (fork-hygiene-queue): session-cache bundled-plugin discovery across tests, with a reset
fixture.

What is kept, per process:

* the manifests a top-level ``scan_directory`` of the real bundled root returns, re-used while the
  tree's signature is unchanged — every file's name, mtime and size and every directory's listing
  down to the plugin directories' own listings (a directory's mtime is not part of it), read with ``os.scandir`` (its stat is free on Windows), so an added, removed or edited
  plugin is a miss and a fresh scan;
* ``plugins.discover_entrypoint_manifests()``, re-used while ``importlib.metadata.entry_points`` is the original
  function and ``sys.path`` is unchanged (a test that patches either gets the real scan).

Every hit hands out a deep copy. The user and project scans, gating, load order and the LOAD itself —
the import and ``register()`` that write tools, hooks and providers into process-wide registries — run
exactly as before, so the registry state each test sees is the one a cold discovery gives
(``tests/test_plugin_discovery_cache_downstream.py`` compares the two).

Installed by the autouse ``_plugin_discovery_cache`` below (re-exported by ``conftest_plugin``) at the first
test setup after ``hermes_cli.plugins`` is
imported (installing it eagerly would import the plugin stack into every test process). A test that
needs a cold rediscovery requests the ``cold_plugin_discovery`` fixture: the cache is bypassed for its
whole body and emptied afterwards.
"""

from __future__ import annotations

import copy
import importlib.metadata
import os
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

_LOCK = threading.Lock()
_SCANS: dict[tuple[Any, ...], tuple[Any, list]] = {}
_ENTRY_POINTS: dict[tuple[Any, ...], list] = {}
_STATE = {"bypass": 0, "hits": 0, "misses": 0}
_REAL_ENTRY_POINTS = importlib.metadata.entry_points


def stats() -> dict[str, int]:
    """Hit and miss counts since the process started (for the chain contract)."""

    with _LOCK:
        return {"hits": _STATE["hits"], "misses": _STATE["misses"]}


def clear() -> None:
    """Forget every kept discovery result: the next discovery scans from disk."""

    with _LOCK:
        _SCANS.clear()
        _ENTRY_POINTS.clear()


def set_bypass(on: bool) -> None:
    with _LOCK:
        _STATE["bypass"] += 1 if on else -1


def _bypassed() -> bool:
    return _STATE["bypass"] > 0


def _tree_signature(root: str, depth: int = 0) -> tuple:
    """Every file's name, mtime and size, and every directory's listing, down to the plugin directories' own listings."""

    entries = []
    try:
        with os.scandir(root) as it:
            for entry in sorted(it, key=lambda e: e.name):
                if entry.name.startswith("__") and entry.name.endswith("__"):
                    continue  # __pycache__ churns with every import; scan_directory skips dunders too
                try:
                    st = entry.stat()
                    is_dir = entry.is_dir()
                except OSError:
                    entries.append((entry.name, None))
                    continue
                if is_dir:
                    # A directory is its listing, not its mtime: an import writing __pycache__ moves
                    # the mtime (NTFS shows it ~1 s later), and a concurrent worker's first import
                    # made the second discovery of a test a miss on a fresh worktree.
                    entries.append((entry.name, "dir", _tree_signature(entry.path, depth + 1) if depth < 2 else ()))
                else:
                    entries.append((entry.name, st.st_mtime_ns, st.st_size, ()))
    except OSError:
        return (None,)
    return tuple(entries)


def _caching_scan(real, bundled_root: Path):
    root_key = os.path.normcase(os.path.abspath(bundled_root))

    def scan_directory(path, source, *, skip_names=None, prefix="", depth=0):
        if depth != 0 or prefix or _bypassed() or os.path.normcase(os.path.abspath(path)) != root_key:
            return real(path, source, skip_names=skip_names, prefix=prefix, depth=depth)
        key = (root_key, source, frozenset(skip_names or ()))
        signature = _tree_signature(root_key)
        with _LOCK:
            kept = _SCANS.get(key)
        if kept is not None and kept[0] == signature:
            with _LOCK:
                _STATE["hits"] += 1
            return copy.deepcopy(kept[1])
        found = real(path, source, skip_names=skip_names, prefix=prefix, depth=depth)
        with _LOCK:
            _STATE["misses"] += 1
            _SCANS[key] = (signature, copy.deepcopy(found))
        return found

    scan_directory.__wrapped__ = real
    scan_directory._fork_discovery_cache = True
    return scan_directory


def _caching_entry_points(real):
    def discover_entrypoint_manifests():
        if _bypassed() or importlib.metadata.entry_points is not _REAL_ENTRY_POINTS:
            return real()
        key = tuple(sys.path)
        with _LOCK:
            kept = _ENTRY_POINTS.get(key)
        if kept is not None:
            return copy.deepcopy(kept)
        found = real()
        with _LOCK:
            _ENTRY_POINTS[key] = copy.deepcopy(found)
        return found

    discover_entrypoint_manifests.__wrapped__ = real
    discover_entrypoint_manifests._fork_discovery_cache = True
    return discover_entrypoint_manifests


def install_if_imported() -> bool:
    """Wrap the bundled scan and the entry-point read once ``hermes_cli.plugins`` is imported (idempotent).

    Returns True when the cache is installed. Patches the names where discovery resolves them at
    call time: ``plugins_discovery.scan_directory`` (``collect_directory_manifests``) and
    ``plugins.discover_entrypoint_manifests`` (``PluginManager._scan_entry_points``). A test that
    patches either name itself replaces the cache for its own body, as before.
    """

    plugins = sys.modules.get("hermes_cli.plugins")
    discovery = sys.modules.get("hermes_cli.plugins_discovery")
    if plugins is None or discovery is None:
        return False
    if not getattr(discovery.scan_directory, "_fork_discovery_cache", False):
        discovery.scan_directory = _caching_scan(discovery.scan_directory, plugins.get_bundled_plugins_dir())
    if not getattr(plugins.discover_entrypoint_manifests, "_fork_discovery_cache", False):
        plugins.discover_entrypoint_manifests = _caching_entry_points(plugins.discover_entrypoint_manifests)
    return True


@pytest.fixture(autouse=True)
def _plugin_discovery_cache():
    """Autouse: keep bundled discovery between tests once the plugin stack is imported."""

    install_if_imported()
    yield


@pytest.fixture
def cold_plugin_discovery():
    """Request for a cold rediscovery: the cache is bypassed for the whole test and emptied after it."""

    set_bypass(True)
    try:
        yield
    finally:
        set_bypass(False)
        clear()
