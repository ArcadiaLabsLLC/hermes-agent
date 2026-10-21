"""T1 of ``RT-HARNESS-ARGV-MANIFEST-SCAN``: the declared-command cache's fingerprint is a SUPERSET
of what the upstream walk parses.

``hermes_cli/plugins_declared_cli_cache.py::manifest_fingerprint`` decides whether
``discover_declared_cli_commands`` may skip ``collect_directory_manifests``; a manifest the walk parses
but the fingerprint never stats is a change the cache cannot see (a stale winner, a missed override).
This builds both sets from the repo's real bundled tree and compares them.

Killing mutation (2026-10-19): ``manifest_fingerprint(..., depth_cap=1)`` -> every category manifest
(``browser/browser_use``, ...) is missing -> red, 51 paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import plugins as plugins_mod
from hermes_cli import plugins_declared_cli_cache as cache_mod
from hermes_cli import plugins_declared_cli as declared_mod

pytestmark = pytest.mark.gate


def test_the_fingerprint_covers_every_manifest_the_upstream_walk_parses():
    """Built from the repo's real bundled tree: both sets are read, neither is assumed."""
    parsed = plugins_mod.collect_directory_manifests()
    fingerprint = cache_mod.manifest_fingerprint(declared_mod._manifest_roots())
    seen_dirs = {Path(path).parent for path, _size, _mtime in fingerprint.files}

    assert len(parsed) > 10 and any("/" in plugins_mod.manifest_key(m) for m in parsed), "fixture reached no category"
    missing = [m.path for m in parsed if Path(m.path) not in seen_dirs]
    assert missing == []
