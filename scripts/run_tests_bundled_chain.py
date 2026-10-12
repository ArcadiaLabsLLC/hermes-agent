"""The session chain: the paths EVERY test process loads (fast-gate §5).

``scripts/run_tests_bundled_scope.py::select_scope`` reaches an inherited test
file through a ``conftest.py`` in one of ITS directories. That rule is a path
spelling: the fork's root ``conftest.py`` (no directory above it) and the
plugin chain the conftests load — ``tests/_downstream/`` (the conftest plugin,
the id-marker tables), ``tests/_fixtures/`` (imported by ``tests/conftest.py``
at import time), the runner's ``scripts/_bundle_plugin/``, and the config pytest
reads (``pyproject.toml``'s ``addopts`` and markers, the fork's dev pins) — are
loaded by every process, so a change to any of them reaches every test file.
Owner ruling Q3 (2026-10-10): it does, the whole tree, batched into the
release-merge landing; no sampled discount.

A document under a chain prefix (``.md``) is read by nothing at session time
and does not count. Generic data: no import, no I/O.
"""

from __future__ import annotations

from typing import Iterable, List

#: exact paths, and prefixes ending in ``/``, that every test process loads
SESSION_CHAIN = (
    "conftest.py",
    "tests/conftest.py",
    "tests/_downstream/",
    "tests/_fixtures/",
    "scripts/_bundle_plugin/",
    "pyproject.toml",
    "requirements-fork-dev.txt",
)
#: suffixes under a chain prefix that no session reads
NOT_LOADED_SUFFIXES = (".md",)


def in_chain(rel: str) -> bool:
    """True when the repo-relative POSIX path ``rel`` is loaded by every test process."""

    for entry in SESSION_CHAIN:
        if entry.endswith("/") and rel.startswith(entry) and not rel.endswith(NOT_LOADED_SUFFIXES):
            return True
        if rel == entry:
            return True
    return False


def chain_changed(changed: Iterable[str]) -> List[str]:
    """The changed paths that are in the session chain, sorted (the printed reason)."""

    return sorted(rel for rel in changed if in_chain(rel))
