"""The session chain's contract: one test per promise a file EVERY test loads makes.

A change to the session chain (``scripts/run_tests_bundled_chain.py``: the root and
``tests/`` conftests, ``tests/_downstream/``, ``tests/_fixtures/``, the bundle
plugins, the pytest config) reaches every test file. The landing gate runs this
file plus one sample per test folder instead of the whole tree (owner ruling
2026-10-16, r-fastgate step 5); the release merge's whole tree is the backstop for
an interaction no promise here names. Each test pins ONE promise, and its killing
mutation is named in its docstring and recorded in the commit that landed it.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest

from hermes_cli import plugins  # imported here so the chain installs the discovery cache
import hermes_cli.config  # imported here so the chain's home-config fixture finds it at setup
import hermes_constants
import hermes_state  # imported here so the chain's state-db fixture finds it at setup
import hermes_state_wal
import pm.shell  # imported here so the chain's bash-probe memo finds it at setup

pytestmark = pytest.mark.gate

#: the platform-native Hermes home, read at import — before any autouse fixture patches it
_NATIVE_HOME = hermes_constants._get_platform_default_hermes_home()
_CREDENTIAL = "OPENAI_API_KEY"
_FORK_BEHAVIOURAL = "HERMES_HEAD_HOME"
_SENTINEL = "session-chain-contract-sentinel"


@pytest.fixture(scope="module")
def _set_before_the_autouse_fixtures():
    """Module scope: set up before every function-scoped autouse fixture runs."""

    saved = {name: os.environ.get(name) for name in (_CREDENTIAL, _FORK_BEHAVIOURAL)}
    os.environ[_CREDENTIAL] = _SENTINEL
    os.environ[_FORK_BEHAVIOURAL] = str(_NATIVE_HOME)
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def test_root_conftest_disables_gits_optional_index_lock():
    """``conftest.py``: GIT_OPTIONAL_LOCKS=0 for every process (D3.16).
    Mutation: drop its ``os.environ.setdefault("GIT_OPTIONAL_LOCKS", "0")``."""

    assert os.environ.get("GIT_OPTIONAL_LOCKS") == "0"


def test_hermes_home_is_a_per_test_sandbox(tmp_path):
    """``tests/conftest.py::_hermetic_environment``: HERMES_HOME is ``<tmp_path>/hermes_test``.
    Mutation: drop its ``monkeypatch.setenv("HERMES_HOME", ...)``."""

    home = Path(os.environ["HERMES_HOME"])
    assert home == tmp_path / "hermes_test" and home.is_dir()
    assert hermes_constants.get_hermes_home() == home
    assert not home.resolve().is_relative_to(_NATIVE_HOME.resolve())


def test_credentials_are_scrubbed(_set_before_the_autouse_fixtures):
    """``tests/conftest.py::_hermetic_environment`` step 1: every credential-shaped var is gone.
    Mutation: skip its ``monkeypatch.delenv`` of credential-shaped names."""

    assert _CREDENTIAL not in os.environ


def test_the_forks_behavioural_vars_are_scrubbed(_set_before_the_autouse_fixtures):
    """``tests/_downstream/conftest_plugin.py::_downstream_behavioral_vars_scrubbed``: HERMES_HEAD_HOME,
    which outranks the sandboxed HERMES_HOME, is gone. Mutation: make the fixture's body ``pass``."""

    assert _FORK_BEHAVIOURAL not in os.environ


def test_process_state_is_reset_into_the_sandbox(tmp_path):
    """``conftest_plugin.py::_isolate_launcher_process_index``: the process index writes under
    ``tmp_path``, never the operator's Launcher index. Mutation: drop its ``monkeypatch.setattr``."""

    from agent_runtime import process_index

    assert Path(process_index.index_directory()).resolve().is_relative_to(tmp_path.resolve())


def test_every_test_has_the_forks_default_timeout(request):
    """``conftest_plugin.py::pytest_configure``: 30 s per test, thread method, unless the
    command line says otherwise. Mutation: ``FORK_TEST_TIMEOUT_SECONDS = 300.0``."""

    if not request.config.pluginmanager.hasplugin("timeout"):
        pytest.skip("pytest-timeout is not installed: the default is not applied")
    assert request.config.option.timeout == 30.0
    assert request.config.option.timeout_method == "thread"


def test_temp_files_land_under_the_test_tmp_root(tmp_path):
    """``scripts/_fork_test_env.sh``: under the runners, TEMP/TMP/TMPDIR are ``HERMES_TEST_TMP_ROOT``,
    so tempfile and tmp_path stay out of %TEMP%. Mutation: drop its ``TMP=… TEMP=… TMPDIR=…`` export."""

    root = os.environ.get("HERMES_TEST_TMP_ROOT")
    if not root:
        pytest.skip("not under scripts/run_tests.sh or the bundled runner")
    base = Path(root).resolve()
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(base)
    assert tmp_path.resolve().is_relative_to(base)


def test_the_dependency_recorder_is_live_when_the_gate_asks(request):
    """``scripts/_bundle_plugin/hermes_dep_record.py``: with ``--hermes-gate-deps`` the recorder is
    registered and hands its directory to child processes. Mutation: drop its ``register`` call."""

    directory = request.config.getoption("hermes_gate_deps", default=None)
    if not directory:
        pytest.skip("not under the bundled runner's green-result cache")
    assert request.config.pluginmanager.get_plugin("hermes_dep_recorder") is not None
    assert os.environ.get("HERMES_GATE_CHILD_EVENTS") == os.fspath(directory)


def test_the_recorder_gives_a_module_first_loaded_during_a_test_to_that_tests_file(request):
    """``scripts/_bundle_plugin/hermes_dep_record.py``: a repo module that enters ``sys.modules`` while
    a file runs is that file's ``mods_own`` (what ``--affected`` selects on), swept at every change of
    file. Mutation: drop the ``_sweep()`` call from ``_DepRecorder._point``."""

    import sys
    import types

    recorder = request.config.pluginmanager.get_plugin("hermes_dep_recorder")
    if recorder is None:
        pytest.skip("not under the bundled runner's green-result cache")
    current = recorder._trail.current
    module = types.ModuleType("_session_chain_contract_probe")
    module.__file__ = __file__
    sys.modules[module.__name__] = module
    try:
        recorder._point(current)  # the same file again: only the sweep runs
    finally:
        del sys.modules[module.__name__]
    assert current and recorder._trail.filter.rel(__file__) in recorder._own_mods.get(current, set())


def _a_port_nothing_listens_on() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        return held.getsockname()[1]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_closed_loopback_port_refuses_at_once(host):
    """``tests/_downstream/closed_loopback.py``: a connect to a loopback port nothing listens on raises
    ConnectionRefusedError in well under Windows' 2.3 s SYN-retry wait. Mutation: drop
    ``closed_loopback.install()`` from ``conftest_plugin.pytest_configure``."""

    port = _a_port_nothing_listens_on()
    started = time.perf_counter()
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection((host, port), timeout=10).close()
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize("family, host", [(socket.AF_INET, "127.0.0.1"), (socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")])
def test_a_real_loopback_listener_still_connects(family, host):
    """``closed_loopback.py``: the "nothing listens" probe sees a listener on loopback or either wildcard,
    and the connect reaches it. Mutation: make ``port_is_unbound`` return True."""

    with socket.socket(family, socket.SOCK_STREAM) as server:
        if family == socket.AF_INET6:
            server.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        server.bind((host, 0))
        server.listen()
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
            accepted, _ = server.accept()
            accepted.close()
            assert client.getpeername()[1] == port


def test_bundled_plugin_discovery_is_kept_between_tests():
    """``tests/_downstream/plugin_discovery_cache.py``: once the plugin stack is imported, a fresh manager's
    discovery re-uses the kept bundled scan instead of walking and parsing ``plugins/`` again (owner
    ruling 2026-10-10). Mutation: drop the ``_plugin_discovery_cache`` re-export from ``conftest_plugin``."""

    import hermes_cli.plugins_discovery as discovery
    from tests._downstream import plugin_discovery_cache as cache

    assert getattr(discovery.scan_directory, "_fork_discovery_cache", False)
    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins()
    hits = cache.stats()["hits"]
    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins()
    assert cache.stats()["hits"] > hits


def test_a_discovery_sweep_reads_the_load_deadline_once():
    """``tests/_downstream/plugin_load_memo.py``: once the plugin stack is imported, the per-plugin load
    deadline is resolved once per discovery sweep (lane h3-plugins). Mutation: drop the
    ``_plugin_load_memo`` re-export from ``conftest_plugin``."""

    import hermes_cli.plugins_loader as loader

    assert getattr(loader._resolve_plugin_load_timeout, "_fork_sweep_timeout_memo", False)
    assert getattr(plugins.PluginManager._discover_and_load_inner, "_fork_sweep_timeout_memo", False)


def test_a_bundled_yaml_file_parses_once_per_process():
    """``tests/_downstream/parse_memo.py``: once ``hermes_yaml`` is imported, a checkout file's parse is kept
    for the process (lane w2-speed-b). Mutation: drop the ``_bundled_parse_memo`` re-export from
    ``conftest_plugin``."""

    import hermes_yaml

    assert getattr(hermes_yaml.safe_load, "_fork_bundled_parse_memo", False)


def test_a_test_server_notices_shutdown_within_the_short_poll():
    """``tests/_downstream/server_shutdown_poll.py``: a thread-served ``socketserver`` exits in well under its
    0.5 s stock poll (lane w2-speed-b). Mutation: drop ``server_shutdown_poll.install()`` from
    ``conftest_plugin``."""

    import socketserver
    import threading
    import time

    from tests._downstream import server_shutdown_poll

    with socketserver.TCPServer(("127.0.0.1", 0), socketserver.BaseRequestHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.02)
        started = time.perf_counter()
        server.shutdown()
        took = time.perf_counter() - started
        thread.join(timeout=5)
    assert took < 0.4, f"shutdown took {took:.3f} s; the poll is not {server_shutdown_poll.TEST_POLL_INTERVAL}"


def _two_discoveries():
    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins()
    first = {k: p.module for k, p in plugins.get_plugin_manager()._plugins.items() if p.module is not None}
    plugins._reset_plugin_managers_for_tests()
    plugins.discover_plugins()
    second = {k: p.module for k, p in plugins.get_plugin_manager()._plugins.items() if p.module is not None}
    shared = set(first) & set(second)
    assert shared
    return [first[k] is second[k] for k in shared]


def test_bundled_plugin_modules_are_kept_by_default(monkeypatch):
    """``tests/_downstream/plugin_module_keep.py`` is ON by default (owner ruling 2026-10-18): a second
    discovery re-uses at least one bundled plugin module. Mutation: make ``plugin_module_keep.enabled()``
    return False."""

    from tests._downstream import plugin_module_keep as keep

    monkeypatch.delenv(keep.ENV, raising=False)
    keep.install_if_imported()
    assert any(_two_discoveries())
    keep.clear()


def test_bundled_plugin_modules_are_not_kept_when_switched_off(monkeypatch):
    """``HERMES_TEST_KEEP_PLUGIN_MODULES=0`` switches the keep off: two discoveries import each bundled
    plugin twice. Mutation: make ``plugin_module_keep.enabled()`` return True."""

    from tests._downstream import plugin_module_keep as keep

    monkeypatch.setenv(keep.ENV, "0")
    keep.install_if_imported()
    assert not any(_two_discoveries())


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS keeps synchronous=FULL (its btree floor is a subject)")
def test_a_session_db_commits_without_fsync(tmp_path):
    """``tests/_downstream/state_db_no_fsync.py``: a ``SessionDB`` the test opens runs ``PRAGMA synchronous=OFF``
    (the test venv's SQLite forces journal_mode=DELETE, where every autocommitted statement is an fsync).
    Mutation: drop the ``_state_db_no_fsync`` re-export from ``conftest_plugin``."""

    db = hermes_state.SessionDB(db_path=tmp_path / "state.db")
    try:
        assert db._conn.execute("PRAGMA synchronous").fetchone()[0] == 0
    finally:
        db.close()


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS keeps synchronous=FULL (its btree floor is a subject)")
def test_a_store_through_the_wal_door_commits_without_fsync(tmp_path):
    """``tests/_downstream/state_db_no_fsync.py``: a raw ``sqlite3`` store passed through
    ``hermes_state_wal.apply_wal_with_fallback`` (run idempotency, response store, kanban) runs
    ``PRAGMA synchronous=OFF``. Mutation: drop the door ``monkeypatch.setattr`` in ``_state_db_no_fsync``."""
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "store.db"))
    try:
        hermes_state_wal.apply_wal_with_fallback(conn, db_label="store.db")
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 0
    finally:
        conn.close()


def test_a_fresh_session_db_is_seeded_from_the_template(tmp_path):
    """``tests/_downstream/session_db_template.py``: a writer open of an absent ``state.db`` is
    seeded from the stripped template (its pins: ``tests/agent_runtime/test_session_db_template.py``).
    Mutation: drop the ``session_db_from_template`` re-export from ``conftest_plugin``."""
    from tests._downstream import session_db_template

    assert hermes_state.SessionDB._open_writer.__name__ == "seeded_open_writer"
    hermes_state.SessionDB(db_path=tmp_path / "state.db").close()
    hermes_state.SessionDB(db_path=tmp_path / "other" / "state.db").close()
    assert session_db_template.BUILDS["count"] >= 1


def test_the_test_home_carries_a_version_stamped_config(tmp_path):
    """``tests/_downstream/home_config.py``: the per-test home holds ``config.yaml`` with only the
    current ``_config_version``, so ``load_config_readonly`` is a cache hit after its first build.
    Mutation: drop the ``_home_carries_a_config`` re-export from ``conftest_plugin``."""

    path = tmp_path / "hermes_test" / "config.yaml"
    version = hermes_cli.config.DEFAULT_CONFIG["_config_version"]
    assert path.read_text(encoding="utf-8") == f"_config_version: {version}\n"
    assert hermes_cli.config.load_config_readonly() is hermes_cli.config.load_config_readonly()


@pytest.mark.skipif(os.name != "nt", reason="the bash.exe probe runs on Windows only")
def test_a_bash_that_started_is_not_probed_again():
    """``tests/_downstream/bash_probe_memo.py``: once ``pm.shell.bash()`` proved a bash.exe starts, the next call
    spawns no ``bash -c "exit 0"`` probe for it (upstream probes on every call, so every local-backend command
    cost two spawns). Mutation: drop the ``_bash_probe_memo`` re-export from ``conftest_plugin``."""

    first = pm.shell.bash()
    assert first is not None
    spawns: list = []
    watching = [True]

    def count(event, args):
        if watching and event == "subprocess.Popen":
            spawns.append(args)

    sys.addaudithook(count)  # an audit hook cannot be removed: it goes quiet once the call returns
    try:
        assert pm.shell.bash() == first
    finally:
        watching.clear()
    assert spawns == []


def test_a_spawned_child_gets_the_start_up_shortcut():
    """``tests/_downstream/child_startup.py``: the environment every test child inherits carries the
    child-side shortcut (``child_site/sitecustomize``: no git version lookup, no bundled-manifest
    re-parse, no background update check; ``tests/test_child_startup_downstream.py`` proves those).
    Mutation: drop ``child_startup.install()`` from ``conftest_plugin``."""

    import subprocess

    from tests._downstream import child_startup

    done = subprocess.run(
        [sys.executable, "-c", "import os, sys, sitecustomize; print(sitecustomize.__file__); "
         "print(os.environ['HERMES_TEST_CHILD_STARTUP']); print(sys.dont_write_bytecode)"],
        capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    site_file, snapshot, no_bytecode = done.stdout.split()
    assert Path(site_file).parent == child_startup.CHILD_SITE
    assert snapshot == os.environ[child_startup.ENV]
    # The child writes the bytecode it compiles (w2-speed-b). Mutation: drop the
    # ``PYTHONDONTWRITEBYTECODE`` pop from ``child_startup.install``, run from a shell that exports it.
    assert no_bytecode == "False"


def test_the_version_identity_is_put_back_after_every_test(request):
    """``tests/_downstream/version_info_scope.py``: a test that resolves or replaces the process version
    identity hands the next test the identity it found. Mutation: drop the ``_version_info_scope``
    re-export from ``conftest_plugin``."""

    from hermes_cli import version_info

    assert "_version_info_scope" in request.fixturenames
    from tests._downstream.version_info_scope import _version_info_scope

    before = version_info._cached_version_info
    steps = _version_info_scope.__wrapped__()
    next(steps)
    version_info._cached_version_info = version_info.VersionInfo("9.9.9", "9.9.9", 0, None, None, "git")
    next(steps, None)
    assert version_info._cached_version_info is before


def test_every_test_starts_with_an_empty_bash_memo(request):
    """``tests/_downstream/bash_resolution_reset.py``: the production bash memo
    (``agent_runtime/bash_resolution_memo.py``) is emptied before every test, so a test that fakes a
    candidate is never handed an earlier test's bash. Mutation: drop the ``_bash_resolution_reset``
    re-export from ``conftest_plugin``."""

    assert "_bash_resolution_reset" in request.fixturenames


def test_teardown_delivers_hooks_without_a_cold_plugin_discovery(request, monkeypatch):
    """``tests/_downstream/teardown_plugin_delivery.py``: for the whole teardown phase a lifecycle hook
    reaches the plugins the test loaded and never triggers a discover-and-load of a manager that never ran
    (the leaked-TUI-session cleanup paid a cold load of every bundled plugin per test). Mutation: drop the
    ``pytest_runtest_teardown_plugin_delivery`` re-export from ``conftest_plugin``."""

    from tests._downstream.teardown_plugin_delivery import no_cold_discovery

    hooked = [impl.function.__name__ for impl in request.config.pluginmanager.hook.pytest_runtest_teardown.get_hookimpls()]
    assert "pytest_runtest_teardown_plugin_delivery" in hooked
    plugins._reset_plugin_managers_for_tests()
    manager = plugins.get_plugin_manager()
    loads: list = []
    monkeypatch.setattr(manager, "discover_and_load", lambda *a, **k: loads.append(a))
    with no_cold_discovery():
        assert plugins.invoke_hook("on_session_finalize", session_id="s", platform="tui") == []
    assert loads == []
    plugins.invoke_hook("on_session_finalize", session_id="s", platform="tui")
    assert len(loads) == 1  # outside teardown the lazy discovery is untouched


def test_a_run_naming_files_builds_no_node_for_a_sibling(request, tmp_path):
    """``tests/_downstream/named_files_collect.py``: when every argument is a file, a directory entry that is
    neither a named file nor on the way to one is ignored before pytest builds a node for it (pytest walked
    every sibling of every named file: ~0.9 CPU-s for one file of ``tests/hermes_cli``). A run naming a
    directory is untouched. Mutation: drop the ``pytest_ignore_collect_named_files`` re-export from
    ``conftest_plugin``."""

    from tests._downstream.named_files_collect import named_scope

    hooked = [impl.function.__name__ for impl in request.config.pluginmanager.hook.pytest_ignore_collect.get_hookimpls()]
    assert "pytest_ignore_collect_named_files" in hooked
    (tmp_path / "pkg").mkdir()
    named = tmp_path / "pkg" / "test_named.py"
    named.write_text("", encoding="utf-8")
    files, ancestors = named_scope(["pkg/test_named.py::test_x"], tmp_path)
    norm = lambda p: os.path.normcase(os.path.abspath(p))  # noqa: E731
    assert files == {norm(named)} and norm(tmp_path / "pkg") in ancestors and norm(tmp_path) in ancestors
    assert norm(tmp_path / "pkg" / "test_sibling.py") not in files | ancestors
    assert named_scope(["pkg"], tmp_path) is None  # a directory argument: pytest's own walk
