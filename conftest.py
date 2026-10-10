"""Fork-only loader for the downstream test plugins (seam lane CARRY3).

Upstream's ``tests/conftest.py`` and the ``tests/{agent,tools,hermes_cli}``
directory conftests stay upstream's bytes. Their fork halves live in
``tests/_downstream/`` and are registered from here, at the moment pytest
registers the upstream conftest they belong to, so load order and fixture
scope are what the one-line ``pytest_plugins`` / star-import carries gave:

* ``tests/conftest.py`` -> ``tests._downstream.conftest_plugin``, imported as a
  plugin (session-wide fixtures, node id ``""``) right after the root test
  conftest, exactly as its ``pytest_plugins`` line did.
* a directory conftest -> its ``tests._downstream.<dir>_conftest`` module,
  split in two. Its FIXTURES are grafted onto the upstream conftest module
  itself, so pytest parses them with that conftest, at that directory's scope,
  exactly as when they were star-imported. Its HOOKS are registered as a
  fixture-free plugin named ``<module>:hooks``.

  It used to be registered whole, under a ``<dir>/_downstream_conftest.py``
  name, as a second conftest for the same directory. pytest 9.1 defers conftest
  fixture parsing and holds ONE pending conftest per directory
  (``FixtureManager._pending_conftests[conftest_dir] = plugin``), so the fork
  half silently evicted the upstream one: every autouse fixture of
  ``tests/{agent,tools,hermes_cli}/conftest.py`` stopped running under the
  pinned pytest (``_materialize_mcp_sdk_symbols`` among them, which is how six
  MCP transport tests went red). The graft keeps one conftest per directory.

Nothing registers unless pytest collects under ``tests/``: a run of another
tree (``mobile_core/tests``, a skill's own tests) loads this file and does
nothing, because the upstream conftests it keys on never register.
"""

from __future__ import annotations

import importlib
import os
import types
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent / "tests"

# The operator's home leaves the environment BEFORE ``tests/conftest.py`` runs,
# so a bare ``python -m pytest`` from a live shell starts where the runner's
# ``env -i`` starts and every child inherits the session sandbox, never the
# live home (``tests/_downstream/session_home.py`` says why; lane h-suite-hermetic).
from tests._downstream import session_home as _session_home  # noqa: E402

_SPAWNED_BY_TEST = bool(os.environ.get(_session_home.ISOLATION_ENV))
_session_home.detach_operator_home(os.environ)

# No test leaves a zero-byte ``index.lock`` in the checkout it runs from: git's
# opportunistic index refresh (``status``/``diff``/``describe``) takes the lock,
# and a process killed between the lock and the write (``--file-timeout`` is a
# kill) leaves it behind. ``GIT_OPTIONAL_LOCKS=0`` skips the refresh for every
# git this session spawns, under the runners' ``env -i`` and under bare pytest
# alike (design sweep D3.16).
os.environ.setdefault("GIT_OPTIONAL_LOCKS", "0")


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):  # noqa: D401 — pytest hook
    """Refuse to run a session whose HERMES_HOME is a real install."""
    home = _session_home.ensure_session_home(os.environ)
    refusal = _session_home.live_home_refusal(
        home, _session_home.real_roots(os.environ), check_markers=not _SPAWNED_BY_TEST
    )
    if refusal:
        raise pytest.UsageError(f"hermetic session home refused: {refusal}")

#: upstream conftest (relative to ``tests/``) -> fork module that rides it.
_ROOT_PLUGIN = "tests._downstream.conftest_plugin"
_DIRECTORY_PLUGINS = {
    "agent": "tests._downstream.agent_conftest",
    "tools": "tests._downstream.tools_conftest",
    "hermes_cli": "tests._downstream.hermes_cli_conftest",
}


def _key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


_ROOT_CONFTEST = _key(_TESTS / "conftest.py")
_DIRECTORY_CONFTESTS = {
    _key(_TESTS / directory / "conftest.py"): (directory, module)
    for directory, module in _DIRECTORY_PLUGINS.items()
}


def _is_fixture(value) -> bool:
    """A ``@pytest.fixture`` definition (pytest >= 8.4 marker, then the older one)."""
    return hasattr(value, "_fixture_function_marker") or hasattr(value, "_pytestfixturefunction")


def _graft_fixtures(half, upstream) -> None:
    """Bind the fork half's fixtures on the upstream conftest module.

    A name the upstream module already binds is refused rather than shadowed:
    the fork half exists so upstream's bytes stay upstream's, and overriding an
    upstream fixture by name would be a silent edit of its behaviour.
    """
    for name in dir(half):
        value = getattr(half, name)
        if not _is_fixture(value):
            continue
        existing = getattr(upstream, name, None)
        if existing is not None and existing is not value:
            raise RuntimeError(
                f"{half.__name__}.{name} would shadow {upstream.__name__}.{name}; rename the fork fixture"
            )
        setattr(upstream, name, value)


def _hooks_of(half) -> types.ModuleType:
    """The fork half's ``pytest_*`` hooks and nothing else, so registering them
    under a non-conftest name adds no session-wide fixture.

    A MODULE object, not a ``SimpleNamespace``: pytest < 9.1's FixtureManager keys
    plugins in a set/dict when it replays ``pytest_plugin_registered``, and a
    ``SimpleNamespace`` is unhashable (INTERNALERROR under pytest 9.0.3)."""
    holder = types.ModuleType(f"{half.__name__}:hooks")
    for name in dir(half):
        if name.startswith("pytest_"):
            setattr(holder, name, getattr(half, name))
    return holder


@pytest.hookimpl(tryfirst=True)
def pytest_plugin_registered(plugin, plugin_name, manager):  # noqa: D401 — pytest hook
    """Attach a conftest's fork half right after the conftest itself registers.

    ``tryfirst`` so the graft lands before ``FixtureManager`` reads the conftest
    (immediately before pytest 9.1, at collection since).
    """
    if not plugin_name or not plugin_name.endswith("conftest.py"):
        return
    key = _key(plugin_name)
    if key == _ROOT_CONFTEST:
        manager.import_plugin(_ROOT_PLUGIN)
        return
    entry = _DIRECTORY_CONFTESTS.get(key)
    if entry is None:
        return
    _directory, module_name = entry
    name = hooks_plugin_name(module_name)
    if manager.get_plugin(name) is None:
        half = importlib.import_module(module_name)
        _graft_fixtures(half, plugin)
        manager.register(_hooks_of(half), name)


def hooks_plugin_name(module_name: str) -> str:
    """The plugin name a directory half's hooks are registered under."""
    return f"{module_name}:hooks"
