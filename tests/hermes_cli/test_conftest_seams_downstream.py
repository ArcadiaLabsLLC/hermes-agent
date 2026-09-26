"""Every upstream attribute the hermes_cli conftest reaches SILENTLY still exists.

The fixtures in ``tests/_downstream/hermes_cli_conftest/`` patch these with
``raising=False`` or read them through ``getattr(..., None)`` / ``hasattr``, on
purpose — a fixture must not crash a directory's collection. The price is that
an upstream RENAME turns the fixture into a silent no-op and the machine it was
guarding is reachable again. This file turns that rename into a red that names
the seam (lane B5, 2026-09-25; sheet §4 lists the reaches).
"""

from __future__ import annotations

import importlib

import pytest

from tests._downstream.hermes_cli_conftest import _AGENT_BROWSER_PROBE_BINDINGS


@pytest.mark.parametrize(
    ("module_name", "attribute"),
    [
        ("hermes_cli.main", "_pause_windows_gateways_for_update"),
        ("hermes_cli.kanban_db_dispatch", "_live_worker_procs"),
        ("gateway.pairing", "PAIRING_DIR"),
        # Enumerated from the fixture's OWN tuple, never retyped here: a module
        # in it that no longer binds the probe is a patch that lands nowhere.
        *((module, "agent_browser_runnable") for module in _AGENT_BROWSER_PROBE_BINDINGS),
    ],
)
def test_the_seam_a_fixture_patches_still_exists(module_name, attribute):
    module = importlib.import_module(module_name)
    assert hasattr(module, attribute), (
        f"{module_name}.{attribute} is gone: the hermes_cli conftest fixture that "
        "patches it is now a silent no-op — re-point it at the new seam"
    )


def test_the_web_server_app_keeps_the_shape_the_reset_reads():
    """``_web_server_app_is_pristine`` returns early if Starlette's State stops
    keeping its mapping in ``_state`` — and the cross-test auth leak it fixes
    comes back with no signal. This is that signal."""

    from hermes_cli import web_server

    assert isinstance(web_server.app.state._state, dict)
    assert hasattr(web_server.app.router, "lifespan_context")
