"""Idle-box test files: skipped unless the run says the box is idle (design sweep D3.01).

Owner ruling 2026-10-10: the turn-cost / timing files keep their absolute
budgets and run only on an idle box, serial, never inside a parallel gate.
``scripts/test_idle_box_files.txt`` lists them. Every test collected from a
listed file gets the ``idle_box`` marker, and an ``idle_box`` test skips unless
``HERMES_TEST_IDLE_BOX=1`` — which ``scripts/run_tests_idle.sh`` sets after it
has checked that nothing else is running a suite.

The hooks are named ``pytest_<hook>_idle_box`` with ``specname`` so the root
plugin (``conftest_plugin``) can re-export them beside its own hooks of the
same spec.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

IDLE_BOX_MARK = "idle_box"
IDLE_BOX_ENV = "HERMES_TEST_IDLE_BOX"
IDLE_BOX_LIST = Path(__file__).resolve().parents[2] / "scripts" / "test_idle_box_files.txt"
SKIP_REASON = "idle-box file (owner ruling 2026-10-10): run scripts/run_tests_idle.sh"


def load_idle_box_files(path: Path = IDLE_BOX_LIST) -> frozenset[str]:
    """Repo-relative POSIX paths the list names (``#`` starts a comment). A
    missing list names nothing."""

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return frozenset()
    entries = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return frozenset(Path(entry).as_posix() for entry in entries if entry)


@pytest.hookimpl(specname="pytest_configure")
def pytest_configure_idle_box(config):  # noqa: D401 — pytest hook
    config.addinivalue_line(
        "markers",
        f"{IDLE_BOX_MARK}: runs only on an idle box, serial ({IDLE_BOX_ENV}=1, set by "
        "scripts/run_tests_idle.sh); applied to every test of a file on scripts/test_idle_box_files.txt",
    )


@pytest.hookimpl(specname="pytest_collection_modifyitems")
def pytest_collection_modifyitems_idle_box(items):  # noqa: D401 — pytest hook
    listed = load_idle_box_files()
    for item in items:
        if item.nodeid.split("::", 1)[0] in listed:
            item.add_marker(IDLE_BOX_MARK)


@pytest.hookimpl(specname="pytest_runtest_setup", tryfirst=True)
def pytest_runtest_setup_idle_box(item):  # noqa: D401 — pytest hook
    if item.get_closest_marker(IDLE_BOX_MARK) is not None and os.environ.get(IDLE_BOX_ENV) != "1":
        pytest.skip(SKIP_REASON)
