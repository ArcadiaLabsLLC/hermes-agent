"""One ``pm.ensure("git")`` per test process, not one per git spawn.

Upstream's ``tools/checkpoint_manager.py`` builds a fresh environment for every git it spawns
(``_git_env`` → ``selected_git_env`` → ``pm.ensure("git", base_env=…)``): 16.6 ms a call measured by
q-pm, 1,180 calls in one file. PM's git does not move while a process runs, so the chain keeps the
DELTA ``ensure`` applies to its base — the keys it changed, with their values, and the keys it removed —
from the first call, and applies it to every later base (p10-suite B.3).

The delta is reused only when it is the same answer ``ensure`` would give:

* ``pm.ensure`` is PM's own ``pm.client.ensure``. A test that patches ``pm.ensure`` or
  ``pm.client.ensure`` gets the real ``selected_git_env``, so its stub is called every time;
* no loaded ``pm`` module carries a test's stand-in (``_pm_patched``: a mock, or a callable a test
  module defined): a test that patches a boundary deeper in PM (``pm.install.current_target``,
  ``_installed_location`` — ``tests/tools/test_git_consumer_environment.py``) gets the real
  ``selected_git_env`` while the stand-in is planted, and its answer is never kept;
* ``HERMES_RUNTIME_DIR`` (PM's store override) is the one the delta was taken under;
* the new base agrees with the first base on every key the delta touches. ``compose_env`` PREPENDS
  PM's dirs to ``PATH``, so a delta's ``PATH`` is the whole joined string: a base with another
  ``PATH`` gets its own entry (at most ``_ENTRIES`` per context), never the first base's ``PATH``.

The wrapper sits on ``hermes_cli._subprocess_compat.selected_git_env`` and on the names its callers
imported (``_CALLERS``), never on ``pm.ensure``: pm's own tests are untouched. A test that patches
``selected_git_env`` on either replaces the wrapper for its body. Installed by the autouse
``_git_env_memo`` (re-exported by ``conftest_plugin``) once ``hermes_cli._subprocess_compat`` is imported —
never eagerly, which would import pm into every process.
"""

from __future__ import annotations

import os
import sys

import pytest

_MARK = "_fork_git_env_memo"
#: modules that bound ``selected_git_env`` by name at import (``from … import selected_git_env``);
#: ``tests/test_git_env_memo_downstream.py`` walks the tree so a new importer joins this list
_CALLERS = ("tools.checkpoint_manager", "tools.working_diff")
#: bases with distinct values on the delta's keys kept per context (a test that moves PATH)
_ENTRIES = 8
_RUNTIME_DIR = "HERMES_RUNTIME_DIR"
#: the chain's own long-lived wrappers are not a test's stand-in
_CHAIN = "tests._downstream"


def _pm_ensure():
    """``pm.ensure`` when it is PM's own ``pm.client.ensure``, else ``None`` (a test patched it)."""

    pm = sys.modules.get("pm")
    client = sys.modules.get("pm.client")
    if pm is None or client is None:
        return None
    current = pm.__dict__.get("ensure", client.__dict__.get("ensure"))
    genuine = client.__dict__.get("ensure")
    if current is None or current is not genuine or getattr(current, "__module__", None) != "pm.client":
        return None
    return current


def _planted(value) -> bool:
    """A test's stand-in: a mock, or a callable a test module (or conftest) defined."""

    mock = sys.modules.get("unittest.mock")
    if mock is not None and isinstance(value, mock.NonCallableMock):
        return True
    module = getattr(value, "__module__", None)
    if not isinstance(module, str) or module.startswith(_CHAIN):
        return False
    return any(part.startswith("test") or part == "conftest" for part in module.split("."))


def _pm_patched() -> bool:
    """Some loaded ``pm`` module carries a test's stand-in (0.35 ms over 23 modules / 463 callables)."""

    return any(_planted(value) for name, module in list(sys.modules.items())
               if module is not None and (name == "pm" or name.startswith("pm."))
               for value in list(vars(module).values()) if callable(value))


def _memo_delta(real):
    """Wrap ``real`` (``selected_git_env``) so the delta of the first call serves every matching base."""

    memo: dict = {}

    def selected_git_env(base=None):
        ensure = _pm_ensure()
        real = selected_git_env.__wrapped__  # read per call: the contract test counts resolves through it
        if ensure is None or _pm_patched():
            return real(base)
        env = dict(base if base is not None else os.environ)
        entries = memo.setdefault((ensure, os.environ.get(_RUNTIME_DIR)), [])
        for basis, added, removed in entries:
            if all(env.get(k) == v for k, v in basis.items()):
                env.update(added)
                for k in removed:
                    env.pop(k, None)
                return env
        result = real(env)
        added = {k: v for k, v in result.items() if env.get(k) != v}
        removed = tuple(k for k in env if k not in result)
        if len(entries) < _ENTRIES:
            entries.append(({k: env.get(k) for k in (*added, *removed)}, added, removed))
        return result

    selected_git_env.__wrapped__ = real
    selected_git_env.__doc__ = real.__doc__
    setattr(selected_git_env, _MARK, True)
    return selected_git_env


def install_if_imported() -> bool:
    """Wrap ``selected_git_env`` and rebind its callers' names once the module is imported (idempotent)."""

    compat = sys.modules.get("hermes_cli._subprocess_compat")
    if compat is None:
        return False
    current = compat.selected_git_env
    if getattr(current, _MARK, False):
        wrapper, real = current, current.__wrapped__
    elif current.__module__ == compat.__name__:
        real = current
        wrapper = compat.selected_git_env = _memo_delta(real)
    else:  # a test's stub sits on the module: leave it, its teardown puts the original back
        return False
    for name in _CALLERS:
        caller = sys.modules.get(name)
        if caller is not None and caller.__dict__.get("selected_git_env") is real:
            caller.selected_git_env = wrapper
    return True


@pytest.fixture(autouse=True)
def _git_env_memo():
    """Autouse: one ``pm.ensure("git")`` per process once ``_subprocess_compat`` is imported."""

    install_if_imported()
    yield
