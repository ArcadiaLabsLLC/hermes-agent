"""Each test leaves the process-global tool registry the way it found it (plan S3).

Plan ``docs/agent-runtime-harness/planned/process-global-state-reset-2026-10-15.md``.
``tools.registry.registry`` is upstream's process singleton: a test (or a plugin load
it drove) that registered or replaced a tool used to leave that entry for every later
test in the bundle (L6.30: 585 leaked registrations). This fixture marks the
process-global slot before the test and, after it, removes what the test added and
puts back what it replaced, through the registry's own per-name API
(``snapshot_registration`` / ``restore_registration``) -- no upstream edit. When the
upstream ``ToolRegistry.snapshot()/restore()`` door lands
(``docs/agent-runtime-harness/upstream-prs/registry-snapshot-restore-body.md``), the
mark and restore below switch to it.

One registration is kept: an entry whose handler's module was FIRST imported during
the test. Tool files register at import, and an import never runs twice, so removing
that entry would leave the tool unregistered for the rest of the process.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest


@dataclass(frozen=True)
class RegistryMark:
    """The process-global slot and the imported modules, as one test found them."""

    entries: dict = field(default_factory=dict)
    modules: frozenset = frozenset()


def _registry():
    module = sys.modules.get("tools.registry")
    return getattr(module, "registry", None) if module is not None else None


@contextmanager
def _home_resolves_to_a_path():
    """Coerce a str-returning ``get_hermes_home`` stub to a Path while the registry lists.

    The listing resolves the current profile scope through ``hermes_constants.get_hermes_home``,
    and this fixture tears down while the test's ``monkeypatch`` is still active (it is set up
    first). An upstream test that stubs that function with ``lambda: str(tmp_path)``
    (``tests/gateway/test_routing_save_fast_path.py``) then reds every teardown with
    ``'str' object has no attribute 'expanduser'``. The stub's home is kept; only its type is.
    """
    module = sys.modules.get("hermes_constants")
    current = getattr(module, "get_hermes_home", None) if module is not None else None
    if current is None:
        yield
        return
    module.get_hermes_home = lambda: Path(current())
    try:
        yield
    finally:
        module.get_hermes_home = current


def _global_entries(registry) -> dict:
    with _home_resolves_to_a_path():
        names = registry.get_all_tool_names()
    return {
        name: entry
        for name in names
        if (entry := registry.snapshot_registration(name, scope=None)) is not None
    }


def mark_tool_registry() -> RegistryMark:
    registry = _registry()
    entries = _global_entries(registry) if registry is not None else {}
    return RegistryMark(entries=entries, modules=frozenset(sys.modules))


def restore_tool_registry(mark: RegistryMark) -> list[str]:
    """Undo what the test did to the process-global slot since ``mark``; the names undone.

    Added entries are removed and replaced entries put back. A builtin the test
    deregistered is not re-added: ``restore_registration`` only swaps a present entry.
    """

    registry = _registry()
    if registry is None:
        return []
    before = mark.entries
    imported_before = mark.modules
    undone: list[str] = []
    for name, current in _global_entries(registry).items():
        previous = before.get(name)
        if current is previous:
            continue
        if previous is None and getattr(current.handler, "__module__", None) not in imported_before:
            continue  # registered by a first import: process-lifetime, see module docstring
        if registry.restore_registration(name, current, previous, scope=None):
            undone.append(name)
    return undone


@pytest.fixture(autouse=True)
def _tool_registry_scope():
    mark = mark_tool_registry()
    yield
    restore_tool_registry(mark)
