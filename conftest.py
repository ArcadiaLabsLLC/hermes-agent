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


def _hooks_of(half) -> types.SimpleNamespace:
    """The fork half's ``pytest_*`` hooks and nothing else, so registering them
    under a non-conftest name adds no session-wide fixture."""
    return types.SimpleNamespace(
        **{name: getattr(half, name) for name in dir(half) if name.startswith("pytest_")}
    )


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
