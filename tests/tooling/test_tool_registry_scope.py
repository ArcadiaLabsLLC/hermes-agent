"""The per-test tool-registry scope (plan process-global-state-reset S3).

Killing mutation: make ``restore_tool_registry`` skip ``restore_registration``
-> ``test_z2_a_registration_by_the_previous_test_is_gone`` and the two direct
cases red. Killing mutation for the ordering: restore in the fixture's teardown
again -> ``test_the_restore_runs_after_monkeypatch_is_undone`` errors in teardown.
"""

from __future__ import annotations

import json
import os
import sys

from tests._downstream.tool_registry_scope import mark_tool_registry, restore_tool_registry
from tools.registry import registry

import pytest

pytestmark = pytest.mark.gate

_THROWAWAY = "r_isolation_throwaway_tool"
_SCHEMA = {"name": _THROWAWAY, "description": "x", "parameters": {"type": "object", "properties": {}}}


def _handler(_args, **_kwargs):
    return "{}"


def _other_handler(_args, **_kwargs):
    return "{}"


def test_an_added_tool_is_removed():
    mark = mark_tool_registry()
    registry.register(_THROWAWAY, "r_isolation_set", _SCHEMA, _handler)
    assert registry.snapshot_registration(_THROWAWAY) is not None

    assert restore_tool_registry(mark) == [_THROWAWAY]
    assert registry.snapshot_registration(_THROWAWAY) is None


def test_a_replaced_tool_is_put_back():
    registry.register(_THROWAWAY, "r_isolation_set", _SCHEMA, _handler)
    original = registry.snapshot_registration(_THROWAWAY)
    mark = mark_tool_registry()
    registry.register(_THROWAWAY, "r_isolation_set", _SCHEMA, _other_handler)
    assert registry.snapshot_registration(_THROWAWAY) is not original

    restore_tool_registry(mark)
    assert registry.snapshot_registration(_THROWAWAY) is original


def test_z1_leave_a_registration_behind():
    registry.register(_THROWAWAY, "r_isolation_set", _SCHEMA, _handler)


def test_z2_a_registration_by_the_previous_test_is_gone():
    # Runs after test_z1 in file order: the autouse fixture undid its registration.
    assert registry.snapshot_registration(_THROWAWAY) is None


def test_restore_survives_a_str_returning_home_stub(monkeypatch, tmp_path):
    # Upstream tests stub get_hermes_home with ``lambda: str(tmp_path)``; the fixture's
    # teardown runs while that stub is active. Killing mutation: drop
    # ``_home_resolves_to_a_path`` from ``_global_entries`` -> AttributeError here.
    import hermes_constants

    mark = mark_tool_registry()
    registry.register(_THROWAWAY, "r_isolation_set", _SCHEMA, _handler)
    monkeypatch.setattr(hermes_constants, "get_hermes_home", lambda: str(tmp_path))

    assert restore_tool_registry(mark) == [_THROWAWAY]
    assert hermes_constants.get_hermes_home() == str(tmp_path)


def test_the_restore_runs_after_monkeypatch_is_undone(monkeypatch, tmp_path):
    # The restore resolves the Hermes home; a home not on disk yet takes the lenient
    # Path.resolve, which reaches os.getcwd. A test's process-wide patch of it must be
    # undone before the restore reads.
    def _boom():
        raise FileNotFoundError

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "not-created"))
    monkeypatch.setattr(os, "getcwd", _boom)


_REGISTRAR = "r_isolation_cross_module_registrar"
_REGISTRAR_SOURCE = f"""
from json import dumps
from tools.registry import registry

registry.register({_THROWAWAY!r}, "r_isolation_set", {_SCHEMA!r}, dumps)
"""


def test_a_first_import_registrar_with_a_handler_elsewhere_keeps_its_tool(monkeypatch, tmp_path):
    # FORK-REGISTRY-SCOPE-HANDLER-MODULE. The registrar module is first imported in
    # this test; its handler lives in ``json``, imported long before. Killing
    # mutation: drop the registrar clause from ``_registered_by_a_first_import``
    # -> the restore removes the tool and this reds.
    (tmp_path / f"{_REGISTRAR}.py").write_text(_REGISTRAR_SOURCE)
    monkeypatch.syspath_prepend(str(tmp_path))
    mark = mark_tool_registry()
    try:
        __import__(_REGISTRAR)
        assert registry.snapshot_registration(_THROWAWAY).handler is json.dumps

        assert restore_tool_registry(mark) == []
        assert registry.snapshot_registration(_THROWAWAY) is not None
    finally:
        sys.modules.pop(_REGISTRAR, None)
        registry.deregister(_THROWAWAY)


def test_the_same_registration_from_a_test_body_is_removed():
    # The negative twin of the positive control above: same handler, same name, no import.
    mark = mark_tool_registry()
    registry.register(_THROWAWAY, "r_isolation_set", _SCHEMA, json.dumps)

    assert restore_tool_registry(mark) == [_THROWAWAY]
    assert registry.snapshot_registration(_THROWAWAY) is None
