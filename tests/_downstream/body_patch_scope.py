"""A test body's ``monkeypatch`` entries, told apart from its fixtures', and undone at call end when asked.

``monkeypatch`` is ONE instance per test, shared by every fixture and the body; pytest unwinds it at the
``monkeypatch`` fixture's own teardown, AFTER every fixture that depends on it has torn down. So a patch the
body pushed (a raising resolver, a stubbed home, a counted ``rmtree``) is live through every fixture's
post-yield code (row ``FORK-PATCH-IN-TEARDOWN``; plan ``docs/agent-runtime-harness/planned/p10-suite-2026-10-19.md``
§ A.1-A.3).

Provenance is by stack INDEX RANGE, never by frame or source: ``pytest_pyfunc_call`` takes the base once every
fixture has set up; ``pytest_fixture_setup`` records the range each fixture set up DURING the call (a late
``request.getfixturevalue``) pushed. Everything above the base and outside every late range is the body's.
The counts are recorded on every test (``user_properties`` -> the bundle's ``bp`` field); the undo runs only
when ``HERMES_TEST_BODY_PATCH_UNDO=on`` or the test carries ``pytest.mark.body_patch_undo("on")`` (the mark
wins). Default OFF until stage S-A3.

The ``scoped_monkeypatch_undo`` narrowing (lane CARRY3) moved here unchanged from ``conftest_plugin``.
Pinned by ``tests/tooling/test_session_chain_contract.py`` (the three ``body_patch`` promises),
``tests/test_conftest_pin_tripwire.py`` and ``tests/agent_runtime/test_no_midtest_monkeypatch_undo.py``.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

import pytest
from _pytest.monkeypatch import NOTSET

from tests._downstream.id_markers.reasons import SCOPED_MONKEYPATCH_UNDO_MARK

BODY_PATCH_KNOB = "HERMES_TEST_BODY_PATCH_UNDO"  # "off" (default until S-A3) | "on"
BODY_PATCH_MARK = "body_patch_undo"  # pytest.mark.body_patch_undo("on"|"off"); wins over the env
USER_PROPERTY = "hermes_body_patches"


@dataclass
class CallRecord:
    base_attr: int
    base_item: int
    cwd_free: bool
    syspath_free: bool
    late_attr: list[tuple[int, int]] = field(default_factory=list)
    late_item: list[tuple[int, int]] = field(default_factory=list)
    late_cwd: bool = False
    late_syspath: bool = False

    def forget_late(self) -> None:
        """A narrowed mid-body undo dropped every entry above the base, late fixtures' included."""
        self.late_attr.clear()
        self.late_item.clear()


def _mode(item) -> str:
    marker = item.get_closest_marker(BODY_PATCH_MARK)
    if marker is not None and marker.args:
        return str(marker.args[0]).strip().lower()
    return os.environ.get(BODY_PATCH_KNOB, "off").strip().lower() or "off"


def _narrow_undo(item, mp, record: CallRecord) -> bool:
    """For a ``scoped_monkeypatch_undo`` test, narrow ``mp.undo`` to the entries above the post-setup base.

    Upstream tests that drop a stub with ``monkeypatch.undo()`` mid-body would unwind the fixtures' hermetic
    pins and redden ``_shared_monkeypatch_pin_tripwire``; the mark is applied at collection to every test
    whose body calls ``.undo()`` (``id_markers.hooks.body_calls_monkeypatch_undo``). Upstream's bytes run
    unchanged; what they drop is exactly what they patched.
    """
    if item.get_closest_marker(SCOPED_MONKEYPATCH_UNDO_MARK) is None:
        return False
    base_attr, base_item = record.base_attr, record.base_item
    base_cwd = None if record.cwd_free else mp._cwd
    base_path = None if record.syspath_free else mp._savesyspath

    def body_undo() -> None:
        # A private instance takes the body's tail; leaving the context unwinds it alone.
        with pytest.MonkeyPatch.context() as body:
            body._setattr = mp._setattr[base_attr:]
            del mp._setattr[base_attr:]
            body._setitem = mp._setitem[base_item:]
            del mp._setitem[base_item:]
            if base_cwd is None:
                body._cwd, mp._cwd = mp._cwd, None
            if base_path is None:
                body._savesyspath, mp._savesyspath = mp._savesyspath, None
        record.forget_late()

    mp.undo = body_undo
    return True


def _body_indices(base: int, length: int, late: list[tuple[int, int]]) -> list[int]:
    return [i for i in range(base, length) if not any(lo <= i < hi for lo, hi in late)]


def _undo_stack(stack: list, body: list[int], key, restore) -> None:
    """Undo ``stack``'s body entries in reverse; a body entry under a later late entry hands it its old value."""
    for i in reversed(body):
        target, name, old = stack[i]
        k = key(target, name)
        later = next((j for j in range(i + 1, len(stack)) if key(stack[j][0], stack[j][1]) == k), None)
        if later is None:
            restore(target, name, old)
        else:  # the late fixture's undo now restores the pre-body value; the attribute stays as it set it
            stack[later] = (stack[later][0], stack[later][1], old)
        del stack[i]


def _restore_attr(obj, name, old) -> None:
    if old is NOTSET:
        delattr(obj, name)
    else:
        setattr(obj, name, old)


def _restore_item(mapping, key, old) -> None:
    if old is NOTSET:
        mapping.pop(key, None)
    else:
        mapping[key] = old


def _undo_body(mp, record: CallRecord, *, enforce: bool) -> tuple[int, int, int, int, int, int]:
    """Count the body's entries (always) and undo them (when ``enforce``); returns the six counts."""
    attrs = _body_indices(record.base_attr, len(mp._setattr), record.late_attr)
    items = _body_indices(record.base_item, len(mp._setitem), record.late_item)
    late_attrs = sum(hi - lo for lo, hi in record.late_attr)
    late_items = sum(hi - lo for lo, hi in record.late_item)
    cwd = record.cwd_free and not record.late_cwd and mp._cwd is not None
    syspath = record.syspath_free and not record.late_syspath and mp._savesyspath is not None
    counts = (len(attrs), len(items), late_attrs, late_items, int(cwd), int(syspath))
    if enforce:
        _undo_stack(mp._setattr, attrs, lambda o, n: (id(o), n), _restore_attr)
        _undo_stack(mp._setitem, items, lambda d, k: (id(d), k), _restore_item)
        if syspath:
            sys.path[:] = mp._savesyspath
            mp._savesyspath = None
        if cwd:
            os.chdir(mp._cwd)
            mp._cwd = None
    return counts


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef, request):
    """While the item is in its call phase, note the stack range a (late) fixture's setup pushed."""
    record = getattr(request.node, "_hermes_call", None)
    mp = record and getattr(request.node, "funcargs", {}).get("monkeypatch")
    if mp is None:
        return (yield)
    a0, i0, cwd0, sp0 = len(mp._setattr), len(mp._setitem), mp._cwd, mp._savesyspath
    try:
        return (yield)
    finally:
        record.late_attr.append((a0, len(mp._setattr)))
        record.late_item.append((i0, len(mp._setitem)))
        record.late_cwd |= cwd0 is None and mp._cwd is not None
        record.late_syspath |= sp0 is None and mp._savesyspath is not None


@pytest.hookimpl(wrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """Take the post-setup base, narrow a scoped undo, and at call end count (and maybe undo) the body's patches."""
    mp = getattr(pyfuncitem, "funcargs", {}).get("monkeypatch")
    if mp is None:
        return (yield)
    record = CallRecord(len(mp._setattr), len(mp._setitem), mp._cwd is None, mp._savesyspath is None)
    pyfuncitem._hermes_call = record
    narrowed = _narrow_undo(pyfuncitem, mp, record)
    try:
        return (yield)
    finally:
        del pyfuncitem._hermes_call
        if narrowed:
            del mp.undo
        counts = _undo_body(mp, record, enforce=_mode(pyfuncitem) == "on")
        if any(counts):
            pyfuncitem.user_properties.append((USER_PROPERTY, counts))
