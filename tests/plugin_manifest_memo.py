"""Parse each bundled ``plugin.yaml`` once per process instead of once per test.

``tests/conftest.py::_hermetic_environment`` resets every plugin manager before each test, so
the first ``discover_plugins()`` of every test re-reads and re-parses all ~57 bundled manifests
with the pure-Python YAML parser (Python 3.14 runs ruamel without its C extension): about 10 ms
a manifest, 29% of ``test_persona_assignments``' profiled CPU on 2026-10-16.

The memo sits only on the PARSE: the same bytes give the same manifest, so the cache is keyed
by the call's arguments plus the file's ``utils.file_signature`` and hands out a deep copy, and a
failed parse (``None``) is never cached, so its warning still prints every time. Plugin LOADING —
the import and ``register()`` that write hooks and tools into process-wide registries — still
runs fresh in every test.

Use: ``from tests.plugin_manifest_memo import memoized_plugin_manifests`` and
``pytestmark = pytest.mark.usefixtures("memoized_plugin_manifests")``. A test that needs the
real parser for one call (a manifest rewritten in place inside the same mtime tick) calls
``clear_plugin_manifest_memo()``.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

import pytest

_MEMO: dict[tuple[Any, ...], Any] = {}
_LOCK = threading.Lock()


def clear_plugin_manifest_memo() -> None:
    """Forget every memoised manifest: the next discovery parses from disk."""

    with _LOCK:
        _MEMO.clear()


def _memoizing(real):
    from utils import file_signature

    def parse_manifest_file(manifest_file: Path, plugin_dir: Path, source: str, prefix: str):
        try:
            signature = file_signature(Path(manifest_file).stat())
        except OSError:
            return real(manifest_file, plugin_dir, source, prefix)
        key = (str(manifest_file), str(plugin_dir), source, prefix, signature)
        with _LOCK:
            hit = _MEMO.get(key)
        if hit is None:
            hit = real(manifest_file, plugin_dir, source, prefix)
            if hit is None:
                return None
            with _LOCK:
                _MEMO[key] = hit
        return copy.deepcopy(hit)

    parse_manifest_file.__wrapped__ = real
    return parse_manifest_file


@pytest.fixture(scope="module")
def memoized_plugin_manifests():
    """Route directory-plugin discovery's manifest parse through the per-process memo for this file."""

    import hermes_cli.plugins_discovery as discovery

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(discovery, "parse_manifest_file", _memoizing(discovery.parse_manifest_file))
        yield
