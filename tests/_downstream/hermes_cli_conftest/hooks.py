"""The five pytest hooks, and the per-session accumulators they write.

Collection applies the prerequisite guards and the ``_ENV_GAP_SKIPS`` rows (owned
by ``registry``); the report hooks keep the KNOWN DEFECTS banner honest; session
finish latches the gateway fence. Every hook is scoped to ``tests/hermes_cli``
by ``_OWNER_DIR`` / ``_OWNER_NODEID_PREFIX``. The map is
``tests/_downstream/hermes_cli_conftest/__init__.py``.
"""

from __future__ import annotations

import pathlib

import pytest

from tests._env_gap_fence import apply_skips, is_owned
from tests._downstream.hermes_cli_conftest.probes import (
    _local_model_probe_reason,
    _web_build_prereq_reason,
)
from tests._downstream.hermes_cli_conftest.registry import (
    _ENV_GAP_SKIPS,
    _KNOWN_DEFECTS,
    _LOCAL_MODEL_PROBE_NODE_IDS,
    _WEB_BUILD_PREREQ_FILES,
)
from tests.hermes_cli import _gateway_fence

__layer__ = "wiring"

#: The directory this conftest's registries own, and the node-id prefix its
#: reports carry. Both hooks below are GLOBAL and every registry is keyed by file
#: BASENAME, so without these a combined run lets one directory's rows skip — or
#: claim the pass of — a same-named file in another. tests/_env_gap_fence.py
#: carries the measurement and the shared half of this scoping.
_OWNER_DIR = pathlib.Path(__file__).resolve().parents[2] / "hermes_cli"
_OWNER_NODEID_PREFIX = "tests/hermes_cli/"

_WINDOWS = "windows_env_gap"
_HOST = "host_dependency_gap"

_ENV_GAPS: dict[str, list[tuple[str, str, set[str]]]] = {}


def pytest_configure(config):  # noqa: D401 — pytest hook
    """Register the environment-gap marks (see the block comment above)."""
    config.addinivalue_line(
        "markers",
        f"{_gateway_fence.REAL_PAUSE_MARK}: let this test drive the REAL "
        "_pause_windows_gateways_for_update (it reads this machine's live "
        "gateway table and Scheduled Task). The test must mock the spawn "
        "itself; the process-wide gateway fence still stands behind it.",
    )
    config.addinivalue_line(
        "markers",
        f"{_WINDOWS}: pre-existing failure caused by POSIX-only test "
        "expectations that Windows cannot satisfy. Not a fork regression; "
        "deselect with -m 'not windows_env_gap'.",
    )
    config.addinivalue_line(
        "markers",
        f"{_HOST}: pre-existing failure caused by a missing host package or "
        "toolchain (croniter / pywinpty / pathspec, Node "
        ">=20.19 for the Vite 8 web build, git >=2.31 semantics for "
        "`--name-only --ignore-cr-at-eol`, outbound HTTP). Not a fork "
        "regression; deselect with -m 'not host_dependency_gap'.",
    )


def pytest_collection_modifyitems(items):  # noqa: D401 — pytest hook
    """Attach the environment-gap mark to every registered node id.

    Items OUTSIDE this directory are skipped first. This is a global pytest
    hook — once this conftest is loaded, pytest hands it every item in the
    session — and every registry it reads is keyed by file BASENAME, so in a
    combined run (``pytest tests/hermes_cli tests/cli``) a row here would reach
    a same-named file one directory over and skip it. See the ownership block in
    tests/_env_gap_fence.py for the measurement.
    """
    for item in items:
        if not is_owned(item.path, _OWNER_DIR):
            continue
        if (
            item.path.name in _WEB_BUILD_PREREQ_FILES
            and _web_build_prereq_reason() is not None
        ):
            item.add_marker(pytest.mark.skip(reason=_web_build_prereq_reason()))
        probe_ids = _LOCAL_MODEL_PROBE_NODE_IDS.get(item.path.name)
        _, _, probe_name = item.nodeid.partition("::")
        if (
            probe_ids is not None
            and probe_name in probe_ids
            and _local_model_probe_reason() is not None
        ):
            item.add_marker(pytest.mark.skip(reason=_local_model_probe_reason()))
        groups = _ENV_GAPS.get(item.path.name)
        if groups is None:
            continue
        _, _, within_file = item.nodeid.partition("::")
        for mark, reason, node_ids in groups:
            if within_file in node_ids:
                item.add_marker(getattr(pytest.mark, mark)(reason=reason))
    apply_skips(items, _ENV_GAP_SKIPS, owner_dir=_OWNER_DIR)

_STALE_ENV_GAP_ENTRIES: list[str] = []

_KNOWN_DEFECT_FAILURES: list[str] = []

def pytest_runtest_logreport(report):  # noqa: D401 — pytest hook
    """Record stale env-gap passes, and the known-defect tests' outcomes.

    The known-defect test is ``xfail(strict=True)``, so its ordinary outcome is
    ``skipped`` with ``wasxfail`` set — NOT ``failed``. Matching on ``failed``
    alone would have silenced this banner the moment the mark landed, which is
    exactly the hazard fencing a defect creates: the fence must not also
    retire the report. The ``failed`` arm still earns its place, because a
    strict XPASS arrives as ``failed`` with no ``wasxfail`` — and that is the
    day someone must read the row and delete it.
    """
    if report.when != "call":
        return
    if not report.nodeid.replace("\\", "/").startswith(_OWNER_NODEID_PREFIX):
        # Another directory's report. Global hook, basename-keyed registries —
        # see pytest_collection_modifyitems above.
        return
    file_name = report.nodeid.split("::", 1)[0].rsplit("/", 1)[-1]

    if file_name in _KNOWN_DEFECTS and (
        report.outcome == "failed" or hasattr(report, "wasxfail")
    ):
        _KNOWN_DEFECT_FAILURES.append(report.nodeid)
        return

    if report.outcome != "passed":
        return
    groups = _ENV_GAPS.get(file_name)
    if groups is None:
        return
    _, _, within_file = report.nodeid.partition("::")
    if any(within_file in node_ids for _, _, node_ids in groups):
        _STALE_ENV_GAP_ENTRIES.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):  # noqa: D401 — pytest hook
    """Latch the gateway fence on for whatever the process does next.

    Every fixture has torn down by now and every monkeypatch is undone, which
    is precisely the state the measured escape ran in: ``_cmd_update_impl``
    parks ``_resume_windows_gateways_after_update`` on ``atexit`` mid-test, and
    it fires at interpreter exit against the operator's real profile. Arming is
    a flag the already-installed wrappers read at spawn time, so it does not
    have to beat that handler in atexit's LIFO order — it only has to be down
    before the handler runs, and session finish always is.

    Nothing is disarmed after this point, on purpose. The run is over; no
    legitimate test spawn can still be owed.
    """
    _gateway_fence.arm_permanently()


def pytest_terminal_summary(terminalreporter):  # noqa: D401 — pytest hook
    """Surface stale registry rows, and explain the deliberate reds."""
    if _KNOWN_DEFECT_FAILURES:
        terminalreporter.write_sep(
            "=", "KNOWN DEFECTS — fenced xfail(strict), still open"
        )
        seen: set[str] = set()
        for nodeid in sorted(set(_KNOWN_DEFECT_FAILURES)):
            file_name = nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
            terminalreporter.write_line(f"  {nodeid}")
            if file_name not in seen:
                seen.add(file_name)
                terminalreporter.write_line(f"  {_KNOWN_DEFECTS[file_name]}")
                terminalreporter.write_line("")

    if not _STALE_ENV_GAP_ENTRIES:
        return
    terminalreporter.write_sep("=", "stale environment-gap registry entries")
    terminalreporter.write_line(
        "These node ids are registered in _ENV_GAPS (tests/hermes_cli/conftest.py) "
        "but PASSED. Delete their rows — a stale row hides a future regression."
    )
    for nodeid in sorted(set(_STALE_ENV_GAP_ENTRIES)):
        terminalreporter.write_line(f"  {nodeid}")
