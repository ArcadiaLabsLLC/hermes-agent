"""The per-test tool-registry scope (plan process-global-state-reset S3).

Killing mutation: make ``restore_tool_registry`` skip ``restore_registration``
-> ``test_z2_a_registration_by_the_previous_test_is_gone`` and the two direct
cases red.
"""

from __future__ import annotations

from tests._downstream.tool_registry_scope import mark_tool_registry, restore_tool_registry
from tools.registry import registry

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
