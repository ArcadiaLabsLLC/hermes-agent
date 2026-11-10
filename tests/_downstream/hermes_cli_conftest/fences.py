"""Fixtures that keep every test in ``tests/hermes_cli`` off THIS MACHINE.

The gateway fence (installed at import, armed per test, latched at session
finish by ``hooks``), the Windows gateway-pause token and the live process
table. Each is autouse and bound by name on the package ``__init__``, which is the object pytest registers. The map is
``tests/_downstream/hermes_cli_conftest/__init__.py``.
"""

from __future__ import annotations

import pytest

from tests._downstream.id_markers.reasons import REAL_PROCESS_TABLE_MARK
from tests.hermes_cli import _gateway_fence

__layer__ = "lanes"

# L2/L3 of the gateway fence: the spawn wrappers go on at conftest IMPORT — the
# earliest moment this directory owns — and are never removed, because the
# measured escape ran from an ``atexit`` handler, a window no fixture can
# cover. Installing is not the same as refusing: the refusal is armed by
# ``_gateway_fence_is_armed_for_this_test`` below for items in THIS directory,
# and latched on for good at ``pytest_sessionfinish``. See
# tests/hermes_cli/_gateway_fence.py for the full reproduction and for why the
# two had to be separated.
_gateway_fence.install()

@pytest.fixture(autouse=True)
def _gateway_fence_is_armed_for_this_test(request):
    """Arm the gateway fence for the duration of THIS directory's tests.

    Conftest import is process-wide, and in a combined run
    ``tests/agent_runtime tests/hermes_cli`` it is the same process. Merely
    COLLECTING a module here therefore used to install a refusal that outlived
    this directory entirely — and tests/agent_runtime spawns real
    ``python -m hermes_cli.main harness serve`` children on purpose, against
    roots it sandboxes itself. Measured 2026-08-31 on `671ae4f9a7`:

        python -m pytest tests/hermes_cli/test_env_export_prefix.py \
                         tests/agent_runtime/test_serve_socket_child_e2e.py -q
        -> 2 failed  (GatewayFenceViolation on a legitimate serve child)

    and in the wave-close full run, 6 failed / 5 errors across
    test_serve_socket_child_e2e, test_gateway_peer_cross_install_chat_e2e and
    test_gateway_peer_two_roots_e2e — all green in isolation. A fence that reds
    another directory's honest work is not a fence, it is a bug with a good
    excuse.

    Being a fixture in THIS conftest is the scoping: pytest runs a directory
    conftest's fixtures for its own items and no others, so the arming follows
    the running item's path without anyone matching path strings. It is
    deliberately NOT keyed on collection order — in a combined run
    tests/agent_runtime happens to collect first, but nothing should depend on
    that.

    The atexit window is not covered here (a spawn from a handler happens long
    after this teardown) and does not need to be — ``pytest_sessionfinish``
    latches the refusal on permanently, before any atexit handler runs.

    A test marked ``spawns_gateway_lookalike`` runs unfenced here, the same
    exemption the root live-system guard grants it (a test-owned gateway
    stand-in; ``serve``/``dashboard`` stay refused there). Upstream's
    ``test_cross_profile_kill_refusal.py`` and ``test_stderr_timestamp.py``
    carry that mark and stay at upstream's path because of it.
    """
    if request.node.get_closest_marker("spawns_gateway_lookalike") is not None:
        yield
        return
    _gateway_fence.arm()
    try:
        yield
    finally:
        _gateway_fence.disarm()

@pytest.fixture(autouse=True)
def _no_windows_gateway_pause_token(request, monkeypatch):
    """L1 of the gateway fence: no test drives the REAL Windows gateway pause.

    ``_cmd_update_impl`` opens with
    ``_pause_windows_gateways_for_update()``. On a real Windows host that
    function walks this machine's live gateway process table and, finding
    nothing running, asks ``gateway_windows.is_installed()`` — a ``schtasks
    /Query`` against the operator's registered ``Hermes_Gateway_alice`` task.
    When that answers yes it returns a ``cold_start_if_installed`` token, and
    ``_cmd_update_impl`` parks the resume on ``atexit``. The handler then fires
    at INTERPRETER EXIT, after every monkeypatch has been undone, and starts a
    real gateway against the operator's real profile. Measured 2026-08-31;
    ``test_update_autostash.py`` alone reproduces it.

    Several files here call ``cmd_update`` / ``_cmd_update_impl`` and the one that
    patched this seam, ``test_update_venv_health.py``, was deleted since (``427d4936c2``), so the default belongs in
    the directory's conftest — the same shape, and the same reasoning, as
    ``_suppress_concurrent_hermes_gate`` above: a Windows-only production guard
    that reads the developer's live machine has no defined answer in a test.

    ``None`` is production's own "nothing to pause" answer, so the code under
    test takes its normal path; nothing is registered and nothing is resumed.
    Tests that are ABOUT the pause/resume path opt out with
    ``@pytest.mark.real_windows_gateway_pause`` and bring their own mocks —
    L2/L3 still stand behind them.
    """
    if request.node.get_closest_marker(_gateway_fence.REAL_PAUSE_MARK):
        return
    try:
        from hermes_cli import main as _cli_main
    except Exception:
        return
    monkeypatch.setattr(
        _cli_main,
        "_pause_windows_gateways_for_update",
        lambda *_a, **_k: None,
        raising=False,
    )

def _empty_process_iter(*_args, **_kwargs):
    """``psutil.process_iter`` for a machine running nothing."""
    return iter(())


@pytest.fixture(autouse=True)
def _no_live_process_table(monkeypatch, request):
    """No test in this directory reads this machine's real process table.

    ``hermes profile delete`` scans for backends bound to the profile being
    deleted, and the scan walks every process on the box (and, for candidates,
    reads their environment). Measured on this workstation 2026-08-18: 448
    processes, ~4.2s per scan, three scans in ``test_profiles.py`` alone —
    which is what made ``tests/hermes_cli`` time out as a directory (ledger
    row F1). The live table is also not a fact any test can drive: what it
    holds depends on what the developer happens to be running.

    Both consumers — ``profiles._profile_bound_backend_pids`` and the desktop
    build-lock sweep ``main_desktop._stop_desktop_processes_locking_build``
    (reached from ``cmd_gui``, ledger row B20(vi)) — are upstream's inline
    ``psutil`` loops since lane ADOPT (2026-09-24) retired the fork's
    process-table seam, so the default is set where they read it:
    ``psutil.process_iter``. Tests that are ABOUT a scan replace ``psutil``
    themselves (``monkeypatch.setitem(sys.modules, "psutil", fake)`` or
    ``monkeypatch.setattr(psutil, "process_iter", ...)``) and drive the rows.

    ``raising`` stays True: if ``psutil`` ever loses ``process_iter`` this
    fixture must fail loudly rather than silently stop guarding.

    A test that scans for a child IT spawned (upstream's
    ``test_desktop_release_holders.py``, v0.23.1: the holder is a sleeper whose cwd is the
    test's own release dir) carries ``real_process_table``, applied by id. The scan still
    reads the box's table; what it acts on is filtered to the test's own paths.
    """
    if request.node.get_closest_marker(REAL_PROCESS_TABLE_MARK) is not None:
        return
    try:
        import psutil  # type: ignore
    except Exception:
        return
    monkeypatch.setattr(psutil, "process_iter", _empty_process_iter)
