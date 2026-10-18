"""One discovery sweep resolves the per-plugin load deadline once, not once per plugin.

Upstream's ``run_with_load_deadline`` (``hermes_cli/plugins_loader.py``) calls
``_resolve_plugin_load_timeout()`` for every plugin it loads, and each call is a
``load_config_readonly()``. A test home carries no ``config.yaml``, so upstream's config cache holds
nothing and every read rebuilds the defaults (deep copy + env expansion): 32 reads per discovery,
~0.08 s of the ~0.5 s a discovery costs (lane h3-plugins, 2026-10-18).

What is kept: the first resolved value of one ``PluginManager._discover_and_load_inner`` sweep, for the
rest of that sweep (a ContextVar, so a deadline worker's re-entrant sweep keeps its own). The next sweep
reads config again, so a test that edits ``plugins.load_timeout_seconds`` between discoveries sees it;
a test that patches ``_resolve_plugin_load_timeout`` replaces this wrapper for its own body.

Installed by the autouse ``_plugin_load_memo`` (re-exported by ``conftest_plugin``) once
``hermes_cli.plugins`` is imported, like ``plugin_discovery_cache``.
"""

from __future__ import annotations

import contextvars
import sys

import pytest

_SWEEP: contextvars.ContextVar[list | None] = contextvars.ContextVar("h_plugin_sweep_timeout", default=None)
_MARK = "_fork_sweep_timeout_memo"


def _memo_timeout(real):
    def _resolve_plugin_load_timeout():
        memo = _SWEEP.get()
        if memo is None:
            return real()
        if not memo:
            memo.append(real())
        return memo[0]

    _resolve_plugin_load_timeout.__wrapped__ = real
    setattr(_resolve_plugin_load_timeout, _MARK, True)
    return _resolve_plugin_load_timeout


def _sweep_scope(real_inner):
    def _discover_and_load_inner(self):
        token = _SWEEP.set([])
        try:
            return real_inner(self)
        finally:
            _SWEEP.reset(token)

    _discover_and_load_inner.__wrapped__ = real_inner
    setattr(_discover_and_load_inner, _MARK, True)
    return _discover_and_load_inner


def install_if_imported() -> bool:
    """Wrap the resolver and the sweep once ``hermes_cli.plugins`` is imported (idempotent)."""

    plugins = sys.modules.get("hermes_cli.plugins")
    loader = sys.modules.get("hermes_cli.plugins_loader")
    if plugins is None or loader is None:
        return False
    if not getattr(loader._resolve_plugin_load_timeout, _MARK, False):
        loader._resolve_plugin_load_timeout = _memo_timeout(loader._resolve_plugin_load_timeout)
    manager = plugins.PluginManager
    if not getattr(manager._discover_and_load_inner, _MARK, False):
        manager._discover_and_load_inner = _sweep_scope(manager._discover_and_load_inner)
    return True


@pytest.fixture(autouse=True)
def _plugin_load_memo():
    """Autouse: one deadline read per discovery sweep once the plugin stack is imported."""

    install_if_imported()
    yield
