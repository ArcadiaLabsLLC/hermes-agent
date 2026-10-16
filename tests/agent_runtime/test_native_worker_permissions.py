"""D2.07 S1a: the native worker binds the serve's per-turn permission mode, fail closed.

No process: the gateway's per-turn ``worker_app_functions.bind`` / ``reset`` seam is
called directly, as ``tui_gateway.prompt_turn._prepare_turn_input`` calls it.
Owner ruling 2026-10-15: read-only unless allowed.
"""
from __future__ import annotations

import importlib.util
import logging
import threading
from pathlib import Path

import pytest

from agent_runtime.conversations import worker_app_functions, worker_permissions
from agent_runtime.tool_blocks import blocked_tools_for
from agent_runtime.tool_permissions import extra_blocked_tools_for_permission_mode


class _Server:
    def __init__(self):
        self.methods = {}

    def register_method(self, name, handler):
        self.methods[name] = handler


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setattr(worker_permissions, "_doors_installed", lambda: True)
    monkeypatch.setattr(worker_permissions, "_pending", {})
    server = _Server()
    worker_permissions.register(server)
    return server.methods[worker_permissions.METHOD]


def _session(execution_id="x-1", key="key-1", source="eternia_intelligence"):
    return {"source": source, "session_key": key, "history_lock": threading.RLock(),
            "native_execution": {"id": execution_id}}


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_under_test_perm", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_read_only_turn_binds_the_read_only_block_until_reset(handler):
    reply = handler("r1", {"session_id": "sid-1", "execution_id": "x-1", "permission_mode": "read_only"})
    assert reply["result"] == {"bound": True}

    token = worker_app_functions.bind("sid-1", _session())
    try:
        expected = frozenset(extra_blocked_tools_for_permission_mode("read_only"))
        assert "terminal" in expected
        assert blocked_tools_for("key-1") == expected
        assert blocked_tools_for("sid-1") == expected
        refusal = _plugin().refuse_tool_call(tool_name="terminal", session_id="key-1")
        assert refusal and refusal.get("action") == "block"
    finally:
        worker_app_functions.reset(token)
    assert blocked_tools_for("key-1") == frozenset()


def test_a_wide_turn_binds_nothing(handler):
    handler("r1", {"session_id": "sid-1", "execution_id": "x-1", "permission_mode": "bounded"})
    token = worker_app_functions.bind("sid-1", _session())
    try:
        assert blocked_tools_for("key-1") == frozenset()
    finally:
        worker_app_functions.reset(token)


def test_a_mode_for_another_execution_fails_closed_to_read_only(handler, caplog):
    handler("r1", {"session_id": "sid-1", "execution_id": "y-2", "permission_mode": "bounded"})
    with caplog.at_level(logging.WARNING, logger=worker_permissions.__name__):
        token = worker_app_functions.bind("sid-1", _session(execution_id="x-1"))
    try:
        assert blocked_tools_for("key-1") == frozenset(extra_blocked_tools_for_permission_mode("read_only"))
        assert any("permission_bind_missing" in record.getMessage() for record in caplog.records)
    finally:
        worker_app_functions.reset(token)


def test_a_block_without_the_plugin_doors_refuses_the_turn(handler, monkeypatch):
    monkeypatch.setattr(worker_permissions, "_doors_installed", lambda: False)
    handler("r1", {"session_id": "sid-1", "execution_id": "x-1", "permission_mode": "read_only"})
    with pytest.raises(RuntimeError, match="tool-block doors"):
        worker_app_functions.bind("sid-1", _session())
    assert blocked_tools_for("key-1") == frozenset()


def test_a_direct_tui_session_is_never_touched(handler):
    handler("r1", {"session_id": "sid-1", "execution_id": "x-1", "permission_mode": "read_only"})
    token = worker_app_functions.bind("sid-1", _session(source="tui"))
    try:
        assert blocked_tools_for("key-1") == frozenset()
    finally:
        worker_app_functions.reset(token)
