"""The Kanban blocked-card PM router, riding upstream's ``on_kanban_dispatch_tick``.

Registered by the eternia-harness plugin. Upstream fires the hook once per dispatcher
tick, AFTER the board's dispatch lock is released; this observer scans the ticking
board's ``task_events`` past its cursor for committed ``blocked`` events and routes each
through :func:`hermes_cli.kanban_blocked_pm.handle_blocked_event`. It replaces the
gateway watcher that polled every board on its own 5 s loop
(``DownstreamGatewayMixin._kanban_blocked_pm_hook_watcher``, deleted 2026-09-24, lane
DOORS-A): latency is now ``kanban.dispatch_interval_seconds``.

Enablement is unchanged: ``kanban.pm_blocked_hook.enabled`` (default off), overridden by
``HERMES_KANBAN_PM_BLOCKED_HOOK``. Best-effort throughout — upstream swallows observer
failures, and this logs them.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Per-board ``task_events`` cursor, keyed by resolved DB path (two slugs can share one).
_cursors: dict[str, int] = {}
_state = threading.local()


def _hook_settings() -> Optional[tuple[Any, bool]]:
    """``(BlockedPmHookConfig, dispatch_after_create)`` when enabled, else None."""

    from hermes_cli.config import load_config
    from hermes_cli.kanban_blocked_pm import BlockedPmHookConfig

    env_override = os.environ.get("HERMES_KANBAN_PM_BLOCKED_HOOK", "").strip().lower()
    cfg = load_config()
    kanban_cfg = cfg.get("kanban", {}) if isinstance(cfg, dict) else {}
    hook_cfg = kanban_cfg.get("pm_blocked_hook", {}) if isinstance(kanban_cfg, dict) else {}
    if not isinstance(hook_cfg, dict):
        hook_cfg = {}
    enabled = bool(hook_cfg.get("enabled", False))
    if env_override in {"1", "true", "yes", "on"}:
        enabled = True
    elif env_override in {"0", "false", "no", "off"}:
        enabled = False
    if not enabled:
        return None
    pm_config = BlockedPmHookConfig(
        pm_assignee=str(hook_cfg.get("assignee") or "pm"),
        workspace_kind=str(hook_cfg.get("workspace_kind") or "scratch"),
        workspace_path=hook_cfg.get("workspace_path"),
        priority=int(hook_cfg.get("priority", 100) or 100),
    )
    return pm_config, bool(hook_cfg.get("dispatch_after_create", True))


def _db_key(kb: Any, slug: str) -> str:
    try:
        meta = kb.read_board_metadata(slug) or {}
        db_path = meta.get("db_path")
        return str(Path(db_path).expanduser().resolve()) if db_path else str(kb.kanban_db_path(slug).resolve())
    except Exception:
        return f"slug:{slug}"


def route_blocked_events(board: Optional[str] = None) -> list[str]:
    """Route the ticking board's unseen ``blocked`` events. Returns ``slug:task->pm:action`` lines."""

    settings = _hook_settings()
    if settings is None:
        return []
    pm_config, dispatch_after_create = settings

    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect, kanban_db_dispatch
    from hermes_cli.kanban_blocked_pm import handle_blocked_event, unseen_blocked_events

    slug = board or kb.get_current_board() or kb.DEFAULT_BOARD
    key = _db_key(kb, slug)
    outputs: list[str] = []
    created_any = False
    conn = kanban_db_connect.connect(board=slug)
    try:
        cursor = int(_cursors.get(key, 0) or 0)
        events = unseen_blocked_events(conn, after_event_id=cursor)
        if not events:
            max_row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM task_events").fetchone()
            _cursors[key] = max(cursor, int(max_row["m"] or 0))
            return outputs
        for event in events:
            result = handle_blocked_event(conn, event, pm_config)
            _cursors[key] = max(_cursors.get(key, 0), int(event.id))
            if result.created_pm_task_id:
                created_any = True
                outputs.append(f"{slug}:{event.task_id}->{result.created_pm_task_id}:{result.action}")
        if created_any and dispatch_after_create:
            # dispatch_once fires this hook again; the re-entry guard below makes it a no-op.
            kanban_db_dispatch.dispatch_once(conn, board=slug, max_spawn=1)
    finally:
        conn.close()
    return outputs


def on_kanban_dispatch_tick(board: Optional[str] = None, dry_run: bool = False, **_kwargs: Any) -> None:
    """``on_kanban_dispatch_tick`` observer. Never raises; a dry-run tick routes nothing."""

    if dry_run or getattr(_state, "active", False):
        return
    _state.active = True
    try:
        for item in route_blocked_events(board):
            logger.info("kanban blocked PM hook routed %s", item)
    except Exception as exc:
        logger.warning("kanban blocked PM hook: board %s tick failed: %s", board, exc)
    finally:
        _state.active = False
