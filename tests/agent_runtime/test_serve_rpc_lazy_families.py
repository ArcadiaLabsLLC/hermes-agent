"""The lazy verb families are ONE table that the manifest and the dispatcher both read.

``registry._LAZY_FAMILIES`` is the list; ``method_names()`` and
``dispatch.handle_request`` reach it only through ``ensure_lazy_families``. A
family appended to the table must be visible to BOTH readers without either
being edited (RT-RPC-LAZY-FAMILY-TABLE).
"""

from __future__ import annotations

from agent_runtime.call_authorization import TIER_READ
from agent_runtime.serve_rpc import dispatch, registry
from agent_runtime.serve_rpc.protocol import ok


_NAME = "runtime.test_lazy_family.ping"


def _install_fake_family(monkeypatch):
    def _ensure_fake():
        if _NAME not in registry._METHODS:
            registry.method(_NAME, TIER_READ)(lambda rid, params, ctx: ok(rid, {"pong": True}))

    monkeypatch.setattr(registry, "_LAZY_FAMILIES", registry._LAZY_FAMILIES + (_ensure_fake,))
    monkeypatch.delitem(registry._METHODS, _NAME, raising=False)
    monkeypatch.delitem(registry._METHOD_TIERS, _NAME, raising=False)


def test_a_table_row_reaches_method_names(monkeypatch):
    _install_fake_family(monkeypatch)
    assert _NAME in registry.method_names()
    registry._METHODS.pop(_NAME, None)
    registry._METHOD_TIERS.pop(_NAME, None)


def test_a_table_row_reaches_the_dispatcher(monkeypatch):
    _install_fake_family(monkeypatch)
    frame = dispatch.handle_request({"jsonrpc": "2.0", "id": 1, "method": _NAME, "params": {}})
    registry._METHODS.pop(_NAME, None)
    registry._METHOD_TIERS.pop(_NAME, None)
    assert frame.get("result") == {"pong": True}, frame


def test_every_ensure_function_is_a_table_row():
    ensures = {
        name for name in vars(registry)
        if name.startswith("_ensure_") and name.endswith("_methods")
    }
    assert ensures == {fn.__name__ for fn in registry._LAZY_FAMILIES}
