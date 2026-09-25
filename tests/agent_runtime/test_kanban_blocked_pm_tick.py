"""The blocked-card PM router rides upstream's ``on_kanban_dispatch_tick`` (lane DOORS-A).

Replaces the gateway watcher test: the same blocked card, routed by a real
``dispatch_once`` tick firing the hook the eternia-harness plugin registers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from agent_runtime import kanban_blocked_pm_tick
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli.plugins import get_plugin_manager

_ENABLED = {
    "kanban": {
        "pm_blocked_hook": {
            "enabled": True, "assignee": "pm", "workspace_kind": "scratch",
            "dispatch_after_create": False,
        }
    }
}


@pytest.fixture
def blocked_card(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "blocked-hook.db"))
    monkeypatch.setattr(kanban_blocked_pm_tick, "_cursors", {})
    from hermes_cli import config as hermes_config

    monkeypatch.setattr(hermes_config, "load_config", lambda: _ENABLED)
    kb.init_db()
    conn = kbc.connect()
    try:
        tid = kb.create_task(conn, title="Implementation complete", assignee="worker")
        assert kb.block_task(conn, tid, reason="review-required: implementation complete, tests green")
    finally:
        conn.close()
    return tid


@pytest.fixture
def plugin_hook_registered():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_pm_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mgr = get_plugin_manager()
    saved = {k: list(v) for k, v in mgr._hooks.items()}
    mgr._hooks.setdefault("on_kanban_dispatch_tick", []).append(module.route_blocked_kanban_cards)
    try:
        yield
    finally:
        mgr._hooks = saved


def _pm_rows():
    conn = kbc.connect()
    try:
        return conn.execute(
            "SELECT title, assignee, body, idempotency_key FROM tasks WHERE created_by = 'kanban-blocked-hook'"
        ).fetchall()
    finally:
        conn.close()


def test_a_dispatch_tick_routes_the_blocked_card_to_pm(blocked_card, plugin_hook_registered):
    conn = kbc.connect()
    try:
        kbd.dispatch_once(conn, spawn_fn=lambda *a, **k: None)
    finally:
        conn.close()

    rows = _pm_rows()
    assert len(rows) == 1
    assert rows[0]["assignee"] == "pm"
    assert rows[0]["title"] == f"PM: auto-route blocked card {blocked_card}"
    assert blocked_card in rows[0]["body"]
    assert rows[0]["idempotency_key"].startswith(f"pm-blocked-hook-{blocked_card}-")


def test_a_dry_run_tick_routes_nothing(blocked_card, plugin_hook_registered):
    """Positive control: the same card and hook, a dry-run tick -> no PM card."""
    conn = kbc.connect()
    try:
        kbd.dispatch_once(conn, dry_run=True, spawn_fn=lambda *a, **k: None)
    finally:
        conn.close()
    assert _pm_rows() == []
