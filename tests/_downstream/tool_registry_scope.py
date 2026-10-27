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

One registration is kept: an entry registered by a module FIRST imported during the
test. Tool files register at import, and an import never runs twice, so removing that
entry would leave the tool unregistered for the rest of the process. "Registered by"
is the module whose body was executing when ``register`` ran -- recorded at register
time by a ``sys.monitoring`` start event on ``ToolRegistry.register``'s code, which
adds no frame to the call (the registry reads its caller with ``sys._getframe``) --
or, as before, the handler's own module (FORK-REGISTRY-SCOPE-HANDLER-MODULE: a
registrar whose handlers live in an already-imported module lost its tools after
the first test).
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


# name -> the modules whose module body was on the stack at that name's latest register.
_import_registrars: dict[str, frozenset[str]] = {}
_monitored_code = None


def _on_register_start(code, _offset):
    frame = sys._getframe(1)
    if frame.f_code is not code:
        return None
    name = frame.f_locals.get("name")
    modules = set()
    outer = frame.f_back
    while outer is not None:
        if outer.f_code.co_name == "<module>":
            modules.add(outer.f_globals.get("__name__", ""))
        outer = outer.f_back
    if isinstance(name, str):
        _import_registrars[name] = frozenset(modules)
    return None


def _watch_register(registry) -> None:
    """Record, per registration, which module bodies were executing (3.12+; idempotent)."""
    global _monitored_code
    monitoring = getattr(sys, "monitoring", None)
    code = getattr(getattr(type(registry), "register", None), "__code__", None)
    if monitoring is None or code is None or code is _monitored_code:
        return
    tool_id = next((i for i in (4, 3) if monitoring.get_tool(i) is None), None)
    if tool_id is None:
        return
    monitoring.use_tool_id(tool_id, "eternia-tool-registry-scope")
    monitoring.register_callback(tool_id, monitoring.events.PY_START, _on_register_start)
    monitoring.set_local_events(tool_id, code, monitoring.events.PY_START)
    _monitored_code = code


def _registered_by_a_first_import(name: str, current, imported_before: frozenset) -> bool:
    if getattr(current.handler, "__module__", None) not in imported_before:
        return True
    registrars = _import_registrars.get(name, ())
    return any(m in sys.modules and m not in imported_before for m in registrars)


def _registry():
    module = sys.modules.get("tools.registry")
    return getattr(module, "registry", None) if module is not None else None


@contextmanager
def _home_resolves_to_a_path():
    """Coerce a str-returning ``get_hermes_home`` stub to a Path while the registry lists.

    The listing resolves the current profile scope through ``hermes_constants.get_hermes_home``.
    The teardown restore now runs after ``monkeypatch`` is undone, but a restore that runs while a
    test's stub is live (a direct ``restore_tool_registry`` call) still meets an upstream stub like
    ``lambda: str(tmp_path)`` (``tests/gateway/test_routing_save_fast_path.py``), which reds with
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
    if registry is not None:
        _watch_register(registry)
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
        if previous is None and _registered_by_a_first_import(name, current, imported_before):
            continue  # registered by a first import: process-lifetime, see module docstring
        if registry.restore_registration(name, current, previous, scope=None):
            undone.append(name)
    return undone


_MARK_KEY = pytest.StashKey[RegistryMark]()


@pytest.fixture(autouse=True)
def _tool_registry_scope(request):
    """Mark the slot at setup; the restore is :func:`pytest_runtest_teardown_tool_registry`."""
    request.node.stash[_MARK_KEY] = mark_tool_registry()


@pytest.hookimpl(specname="pytest_runtest_teardown", wrapper=True)
def pytest_runtest_teardown_tool_registry(item, nextitem):  # pytest hook
    """Restore AFTER every function fixture, ``monkeypatch`` included.

    The restore reads the registry, which resolves the Hermes home (``Path.resolve`` ->
    ``os.getcwd``). As a fixture teardown it ran before ``monkeypatch`` undid a test's
    process-wide patch, so a test patching ``os.getcwd`` to raise errored in teardown
    (``tests/tools/test_terminal_task_cwd.py``, lane r-state 2026-10-18).
    """
    try:
        return (yield)
    finally:
        mark = item.stash.get(_MARK_KEY, None)
        if mark is not None:
            del item.stash[_MARK_KEY]
            restore_tool_registry(mark)
