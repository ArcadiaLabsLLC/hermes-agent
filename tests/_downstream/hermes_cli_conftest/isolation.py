"""Fixtures that keep one test's STATE from outliving it.

The kanban live-worker registry, ``hermes_cli.web_server.app`` (state and the
merged lifespan), ``gateway.pairing.PAIRING_DIR`` and ``sys.modules`` identity.
Each is autouse and bound by name on the package ``__init__``. The map is
``tests/_downstream/hermes_cli_conftest/__init__.py``.
"""

from __future__ import annotations

import sys

import pytest

from tests.hermes_cli import _module_identity

__layer__ = "lanes"

@pytest.fixture(autouse=True)
def _kanban_live_worker_registry_is_per_test():
    """Empty ``kanban_db_dispatch._live_worker_procs`` after every test here.

    On win32 ``reap_worker_zombies`` polls every handle ``_default_spawn``
    parked in that module-level dict. A test that spawns through a fake
    ``Popen`` leaves the fake parked, and upstream's fakes (``FakeProc``,
    ``_FakePopen``) have no ``poll()``, so the NEXT test's reaper raises
    (``test_gateway_dispatcher_disables_corrupt_board_without_traceback`` x2
    reds on upstream's bytes). Only a module already imported is touched.
    """
    yield
    dispatch = sys.modules.get("hermes_cli.kanban_db_dispatch")
    registry = getattr(dispatch, "_live_worker_procs", None)
    if isinstance(registry, dict):
        registry.clear()

#: Pristine ``web_server.app`` state — ``app.state`` and the router's merged
#: lifespan — as they stood the first time a test in this directory saw the
#: module. Every later test is reset to this.
_APP_BASELINE: dict = {}


@pytest.fixture(autouse=True)
def _web_server_app_is_pristine():
    """``hermes_cli.web_server.app`` is ONE object for the whole session.

    ``app`` is a module-level FastAPI instance, so ``app.state`` is a single
    mutable mapping shared by every test in the run — and the auth middleware
    branches on ``app.state.auth_required``. Several files here set it
    (test_dashboard_auth_gate, test_dashboard_auth_401_reauth,
    test_cron_fire_dashboard) and the gate tests deliberately leave it True:
    they assert that a fail-closed public bind RECORDS the flag, and the
    assertion is the last statement.

    Everything downstream is then 401ed. In gated mode the legacy session
    token is not honoured, so the ``HEADERS = {"X-Hermes-Session-Token":
    _SESSION_TOKEN}`` idiom — module-level in a dozen files here — stops
    working, and the test reads as "the endpoint broke" rather than "the
    process has been in OAuth mode since three files ago". Measured
    2026-08-31: test_dashboard_auth_gate.py alone reds 4 tests across
    test_env_custom_keys.py and test_env_export_line_lifecycle.py, which is
    exactly what the full run reports.

    The reset happens at SETUP, not teardown, and that is the load-bearing
    detail. ``monkeypatch`` is instantiated by the root conftest's first
    autouse fixture, so it tears down AFTER anything declared here — and
    ``monkeypatch.setattr(app.state, "bound_port", 9119, raising=False)``
    undoes itself with a ``delattr``. A teardown-time restore removes that key
    first and monkeypatch's undo then dies with ``KeyError: 'bound_port'``
    (measured while building this). Resetting on the way IN leaves every
    pending undo intact and still guarantees no test starts on another test's
    state.

    Restoring the whole mapping rather than the one key keeps this a class
    fix: a future flag stashed on app.state is covered without a second
    fixture. Tests that mean to change it still can — the change just does not
    outlive them.

    The router's merged lifespan is the SECOND thing this app accumulates, and
    it is the same shape of problem. ``app.include_router(r)`` does not only
    append routes — FastAPI wraps ``app.router.lifespan_context`` in a
    ``merged_lifespan`` that also enters ``r``'s. Tests that remount plugin
    API routes mid-session (test_web_server.py's example-plugin fixture,
    test_project_plugin_rce_bypass.py) restore ``app.router.routes`` and
    nothing else, so the wrappers stack up for the rest of the run. When one
    of those routers is a MagicMock, its lifespan yields an AsyncMock, and the
    NEXT test to start the app dies in FastAPI's
    ``{**(maybe_nested_state or {})}`` with ``AsyncMock.keys() returned a
    non-iterable (type coroutine)`` — a message that names nothing involved.
    Measured: test_project_plugin_rce_bypass.py alone reds
    test_web_server_boot_handshake.py::test_lifespan_warmup_is_synchronous.

    Routes are deliberately NOT restored here: the fixtures that append them
    already put the list back, and resetting the list on the way in would also
    drop a router legitimately mounted by a later import.
    """
    module = sys.modules.get("hermes_cli.web_server")
    app = getattr(module, "app", None)
    state = getattr(app, "state", None)
    router = getattr(app, "router", None)
    # Starlette keeps State's mapping in ``_state``; if that ever changes
    # shape, do nothing rather than guess — the reds come back honestly.
    if state is None or not hasattr(state, "_state"):
        return
    if not _APP_BASELINE:
        _APP_BASELINE["state"] = dict(state._state)
        _APP_BASELINE["lifespan"] = getattr(router, "lifespan_context", None)
        return
    state._state.clear()
    state._state.update(_APP_BASELINE["state"])
    if router is not None and _APP_BASELINE["lifespan"] is not None:
        router.lifespan_context = _APP_BASELINE["lifespan"]

@pytest.fixture(autouse=True)
def _pairing_dir_follows_the_test_home(monkeypatch):
    """``gateway.pairing.PAIRING_DIR`` is bound once, at import, and never again.

    ``PAIRING_DIR = get_hermes_dir("platforms/pairing", "pairing")`` runs at
    module scope, and a bare ``PairingStore()`` reads it. Every test that
    builds one therefore shares a single directory: whichever HERMES_HOME
    happened to be current the FIRST time some test imported the module —
    typically another test's tmp home, long since deleted, and (if the module
    is ever first imported outside a hermetic test) the live store's own
    ``platforms/pairing`` directory, which ``__init__`` will
    happily ``mkdir`` and write pending/approved JSON into.

    Measured 2026-08-31: run test_pairing.py and test_gateway_pairing_verbs.py
    ahead of test_dashboard_admin_endpoints.py and two of its pairing tests
    red, because ``data["pending"][0]`` is another file's leftover request
    (``assert 'global-1' == 'user1'``). Reversed, all 54 pass. The reds only
    surfaced once the auth-mode leak was fixed — while every dashboard pairing
    request 401ed, the polluting rows were never written.

    Re-pinned per test, which is the treatment ``tests/conftest.py`` already
    gives ``hermes_state.DEFAULT_DB_PATH`` for exactly this reason: a path
    constant frozen at import cannot follow a per-test home, so the fixture
    has to move it.
    """
    module = sys.modules.get("gateway.pairing")
    if module is None or not hasattr(module, "PAIRING_DIR"):
        return
    from hermes_constants import get_hermes_home

    monkeypatch.setattr(
        module, "PAIRING_DIR", get_hermes_home() / "platforms" / "pairing"
    )

@pytest.fixture(autouse=True)
def _sys_modules_identity_is_restored():
    """A test may IMPORT modules; it may not REPLACE or DROP one.

    The largest cross-test pollution class in this directory, measured
    2026-08-31. ``test_skills_subparser.py`` (since deleted by upstream's 2026-09 test purge) deleted ``hermes_cli.main`` from
    ``sys.modules`` and re-imports it to prove the parser still builds -- and
    never puts the original back. Python then holds TWO ``hermes_cli.main``
    module objects with two separate namespaces:

      * every test file that did ``from hermes_cli.main import _build_web_ui``
        at COLLECTION time holds a function whose ``__globals__`` is the FIRST
        namespace, now orphaned;
      * ``sys.modules["hermes_cli.main"]`` is the SECOND, which is what
        ``patch("hermes_cli.main._run_with_idle_timeout")`` and
        ``monkeypatch.setattr(cli_main, ...)`` reach.

    So the patch lands in a namespace the function under test never reads, and
    the test runs production for real. Measured: ``test_web_ui_build`` shelled
    out to a genuine ``npm run build`` (the ``npm error code EJSONPARSE`` in
    the baseline output is that build, not a mock), and the ``_cmd_update_impl``
    helper stubs in ``test_update_venv_health`` silently did nothing. It is
    also why these reds are green in isolation yet perfectly deterministic in a
    full run: they depend on running after ONE file, not on timing.
    Alphabetical order does the rest -- one file, 16 reds.

    Restoring identity fixes the class rather than the caller, and keeps
    working when the next test reaches for the same trick. Note the asymmetry:
    newly imported modules are LEFT alone (lazy imports are normal, and
    un-importing them would be its own pollution). Only a module the session
    already had, and which the test replaced or removed, is put back.

    ``importlib.reload`` is deliberately NOT covered: it mutates the existing
    module object in place, so identity -- and therefore every binding --
    survives. Reload is a different question, and this guard would answer it
    dishonestly by appearing to.
    """
    # Setup half: make sys.modules and the package attributes AGREE before the
    # test runs, so a hand-rolled loader's child module carries the binding a
    # real import would have made. ``tests/hermes_cli/_module_identity.py``
    # owns that repair, carries the measurement that moved it out of this
    # fixture body, and states why its two skips cannot lose the guarantee.
    # It is O(new modules), not O(sys.modules), and it never fires a parent's
    # module ``__getattr__``: the inline loop this replaced was 29.9 ms per
    # test at the aged tail of a full run, ~65% of the suite's aging floor.
    _module_identity.PARENT_BINDING_REPAIR.run()

    before = sys.modules.copy()
    try:
        yield
    finally:
        for name, module in before.items():
            # sys.modules can hold a non-str key: production does
            # ``sys.modules[spec.name] = module`` and a test that mocks
            # ``importlib.util.spec_from_file_location`` hands it a MagicMock
            # whose ``.name`` is another MagicMock (measured:
            # test_setup_openclaw_migration.py). Such a key has no package to
            # repair and unpacking its ``rpartition`` yields nothing, so skip
            # it rather than crash — policing junk keys is not this guard's
            # question.
            if not isinstance(name, str):
                continue
            if sys.modules.get(name) is not module:
                sys.modules[name] = module
                # The parent package attribute is the OTHER half, and on its
                # own it is enough to keep the split alive: ``import
                # hermes_cli.main`` binds ``main`` on the ``hermes_cli``
                # package object, and ``from hermes_cli import main`` reads
                # THAT attribute, not sys.modules. Restoring only the
                # sys.modules row leaves the two spellings answering with two
                # different module objects -- measured: the update tests kept
                # failing until this line existed.
                parent_name, _, child = name.rpartition(".")
                parent = sys.modules.get(parent_name) if parent_name else None
                if parent is not None and getattr(parent, child, None) is not module:
                    try:
                        setattr(parent, child, module)
                    except Exception:
                        pass
