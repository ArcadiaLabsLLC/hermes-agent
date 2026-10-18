"""A test's TEARDOWN never performs a cold plugin discovery; hooks still reach plugins the test loaded.

``hermes_cli.plugins.invoke_hook`` lazily discovers AND LOADS every plugin when the active manager never
ran (``_delivery_manager``; the right call for a production surface that never imported ``model_tools``).
``tests/conftest.py::_reset_tui_gateway_server_state`` closes the sessions a test left behind through the
production teardown (``_close_session_by_id`` -> ``_finalize_session`` -> ``on_session_end`` /
``on_session_finalize``), and ``_hermetic_environment`` resets the plugin managers before every test. So the
cleanup of every test that left a TUI session paid a full cold load of the bundled plugins (32 module
executions, each on its own deadline thread) to deliver two hooks to plugins nothing in the test had
loaded: 27 of 31 teardown seconds in ``tests/tui_gateway/test_ws_orphan_races.py`` alone, ~13 of 28 in the
connector bundle (lane h6-collect, 2026-10-18; the features run's teardown column was 921 s).

For the whole teardown phase (every fixture finalizer, ``monkeypatch`` included) delivery uses the manager
as it stands: a manager the test discovered delivers exactly as before; one that never ran delivers to
nobody, which is what it had loaded. Setup and the test body keep the lazy discovery untouched.
"""

from __future__ import annotations

import contextlib
import sys

import pytest

_PLUGINS_MODULE = "hermes_cli.plugins"


@contextlib.contextmanager
def no_cold_discovery():
    """While open, ``hermes_cli.plugins`` delivers hooks without discovering a manager that never ran."""

    plugins = sys.modules.get(_PLUGINS_MODULE)
    real = getattr(plugins, "_delivery_manager", None)
    if real is None:
        yield
        return
    def manager_as_it_stands():
        # Looked up per call: a ``monkeypatch`` of ``get_plugin_manager`` undone during this teardown
        # must not leave a stand-in bound to the test's manager (the next test would deliver to it).
        return plugins.get_plugin_manager()

    plugins._delivery_manager = manager_as_it_stands
    try:
        yield
    finally:
        if plugins._delivery_manager is manager_as_it_stands:
            plugins._delivery_manager = real


@pytest.hookimpl(specname="pytest_runtest_teardown", wrapper=True)
def pytest_runtest_teardown_plugin_delivery(item, nextitem):  # noqa: D401 — pytest hook
    with no_cold_discovery():
        return (yield)
