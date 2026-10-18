"""The gate directory (``docs/agent-runtime-harness/11-gate-directory.md``) is current.

Two arms. Every repo path the page names in backticks exists (a renamed or deleted
gate reds here instead of leaving a dead row). Every gate in the enumerated places --
``tests/tooling/test_*.py``, ``scripts/check*``, ``scripts/*_gate.py`` and
``scripts/dump_*_contract.py`` -- has a row (a new gate without one reds here).

Killing mutations (2026-10-18): delete the ``test_no_ladder_routing.py`` row ->
``test_every_enumerated_gate_has_a_row`` red; rename a named path to
``tests/tooling/test_gone.py`` -> ``test_every_named_path_exists`` red.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PAGE = REPO / "docs" / "agent-runtime-harness" / "11-gate-directory.md"
_NAMED = re.compile(r"`((?:tests|scripts|\.github)/[^`\s]+)")


def _named() -> set[str]:
    # a glob the page quotes to describe the enumeration is not a path
    return {p for p in _NAMED.findall(PAGE.read_text(encoding="utf-8")) if "*" not in p}


def _enumerated() -> set[str]:
    found = {p for p in REPO.glob("tests/tooling/test_*.py")}
    for pattern in ("scripts/check*", "scripts/*_gate.py", "scripts/dump_*_contract.py"):
        found.update(p for p in REPO.glob(pattern) if p.is_file())
    return {p.relative_to(REPO).as_posix() for p in found}


def test_every_named_path_exists():
    missing = sorted(p for p in _named() if not (REPO / p).exists())
    assert not missing, f"11-gate-directory.md names paths that do not exist: {missing}"


def test_every_enumerated_gate_has_a_row():
    unlisted = sorted(_enumerated() - _named())
    assert not unlisted, f"gates with no row in 11-gate-directory.md: {unlisted}"
