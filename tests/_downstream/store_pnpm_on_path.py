"""Put PM's own pnpm on PATH for the ids the table marks (FH-SOURCE-LAUNCHER-AND-PM-TESTS-RED-ON-MAIN).

Upstream's ``tests/pm/test_update_dependency_legs.py::pnpm_project`` drives the REAL pnpm and
fails without one: "a developer run finds PM's own pnpm under the real Hermes home", because an
activated shell (``scripts/run-in-hermes-env``) has PM's tool dirs on PATH. The fork's
workstation runs use the shared test venv instead of activating
(``scripts/_fork_test_env.sh::fork_shared_test_venv_fallback``), so PATH never gets PM's tools
and a box whose only pnpm is PM's (no system pnpm) reds both tests on the box, never in the code.

For a marked test whose PATH finds no ``pnpm``, this prepends the directory the operator's own
tool store records for pnpm (``Facts.env_for``), exactly the entry activation would add. The
store is read once at ``pytest_configure``, before any test's home-I/O guard exists; the test
then only stats that PATH entry (command lookup, which the guard allows) and execs the binary
in a child. A PATH that already has pnpm, or no store that records one, is left alone, so the
upstream failure still names a box with no pnpm at all.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tests._downstream.id_markers.reasons import STORE_PNPM_ON_PATH_MARK as _MARK

#: The PATH entries the operator's store records for pnpm; resolved at configure time.
_STORE_PNPM_PATH: list[str] = []


def _candidate_roots() -> list[Path]:
    """The operator's Hermes roots, as the runner forwarded them or as the root conftest captured them."""
    roots: list[Path] = []
    recorded = (os.environ.get("HERMES_TEST_REAL_ROOT") or "").strip()
    if recorded:
        roots.append(Path(recorded).expanduser())
    from tests import _downstream

    door = getattr(_downstream.root_conftest, "real_hermes_root_candidates", None)
    roots.extend(door() if door is not None else [])
    roots.append(Path.home() / ".hermes")
    return roots


def store_pnpm_path(roots) -> list[str]:
    """The first root whose ``tools/facts.json`` records pnpm: that store's PATH entries for it."""
    from pm.lock import Facts

    for root in roots:
        store = Path(root) / "tools"
        facts = store / "facts.json"
        try:
            if not facts.is_file():
                continue
            fact = Facts(facts)
            if fact.get("pnpm") is None:
                continue
            entries = fact.env_for("pnpm", store).get("PATH", [])
        except (OSError, ValueError):
            continue
        entries = [entries] if isinstance(entries, str) else list(entries)
        if entries:
            return [str(entry) for entry in entries]
    return []


@pytest.fixture(autouse=True)
def _store_pnpm_on_path(request, monkeypatch, _hermetic_environment):
    if request.node.get_closest_marker(_MARK) is None or shutil.which("pnpm") or not _STORE_PNPM_PATH:
        return
    monkeypatch.setenv("PATH", os.pathsep.join([*_STORE_PNPM_PATH, os.environ.get("PATH", "")]))


@pytest.hookimpl(specname="pytest_configure")
def pytest_configure_store_pnpm_on_path(config):  # pytest hook
    config.addinivalue_line(
        "markers",
        f"{_MARK}: with no pnpm on PATH, PATH gains the pnpm dir the operator's PM tool store "
        "records, as activation would (applied by id from tests/_downstream/id_markers/).",
    )
    _STORE_PNPM_PATH[:] = store_pnpm_path(_candidate_roots())
