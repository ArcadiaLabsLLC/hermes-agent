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
  registered under a ``<dir>/_downstream_conftest.py`` name. pytest scopes a
  plugin's fixtures to the directory of a name ending in ``conftest.py``
  (``FixtureManager.pytest_plugin_registered``), so the module's autouse
  fixtures apply to that directory only, as they did when star-imported.

Nothing registers unless pytest collects under ``tests/``: a run of another
tree (``mobile_core/tests``, a skill's own tests) loads this file and does
nothing, because the upstream conftests it keys on never register.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

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


def pytest_plugin_registered(plugin, plugin_name, manager):  # noqa: D401 — pytest hook
    """Register a conftest's fork half right after the conftest itself."""
    if not plugin_name or not plugin_name.endswith("conftest.py"):
        return
    key = _key(plugin_name)
    if key == _ROOT_CONFTEST:
        manager.import_plugin(_ROOT_PLUGIN)
        return
    entry = _DIRECTORY_CONFTESTS.get(key)
    if entry is None:
        return
    directory, module_name = entry
    name = str(_TESTS / directory / "_downstream_conftest.py")
    if manager.get_plugin(name) is None:
        manager.register(importlib.import_module(module_name), name)
