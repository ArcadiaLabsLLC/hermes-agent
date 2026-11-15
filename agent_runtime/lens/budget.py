"""Lens's token budgets: the limits the owner edits, and what each Episode and day spent.

Design ``planned/lens-act-and-safe-investigate.md`` §3 and §6 (owner RULED 2026-11-14: "the
budget limits should be easily editable"). Three scopes of limit, each read and written over
``runtime.lens.budget.get`` / ``runtime.lens.budget.set`` and stored in the Lens store, so an
edit survives a serve restart and needs no config file:

===========  ============================================  =========================================
scope        keys                                          applies to
===========  ============================================  =========================================
``monitor``  ``episode_tokens``, ``episode_calls``,        one monitor (wins over its workspace's)
             ``daily_tokens``
``workspace`` the same three                               every monitor of that workspace with no
                                                           limit of its own on that key
``lens``     ``daily_tokens``, ``daily_turns``             every Lens turn, all monitors
===========  ============================================  =========================================

A key with no stored value falls back: monitor -> workspace -> the root config's
``agent_runtime.lens.<config key>`` (``settings.py``) -> the built-in default. Writing ``null``
clears a stored value. A new limit takes effect from the next Episode; a running turn keeps the
ceiling it was armed with.

Spend is one ``episode_spend`` row per forged turn (the digest's leader carries a digest's),
written when the turn ends, from the turn's own provider usage (``turn_token_budget``). The
day's totals are sums over those rows on the UTC day the turn started.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, UTC
from typing import Any

from .settings import lens_setting, lens_setting_bounds
from .store import LensStore, to_ms
from .wire_value import WireError, WireRefusal, bounded_int, checked_object, opaque_id

__layer__ = "stores"

__all__ = ["BudgetScope", "add_budget_tables", "budget_view", "episode_limits", "record_spend", "set_limits",
           "spend_today"]

_TABLES = """
CREATE TABLE IF NOT EXISTS budget_limits (
  scope TEXT PRIMARY KEY, body TEXT NOT NULL, updated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS episode_spend (
  episode_id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL, started_ms INTEGER NOT NULL,
  tokens_used INTEGER NOT NULL, token_limit INTEGER, calls_used INTEGER NOT NULL, call_limit INTEGER,
  stopped_by TEXT);
CREATE INDEX IF NOT EXISTS episode_spend_by_day ON episode_spend (started_ms, monitor_id);
"""


class BudgetScope:
    MONITOR = "monitor"
    WORKSPACE = "workspace"
    LENS = "lens"


#: wire key -> settings key, per scope (the wire names say what the limit bounds).
_MONITOR_KEYS = {"episode_tokens": "episode_token_budget", "episode_calls": "episode_call_budget",
                 "daily_tokens": "monitor_daily_token_budget"}
_LENS_KEYS = {"daily_tokens": "daily_token_budget", "daily_turns": "daily_turn_budget"}
_SCOPE_KEYS = {BudgetScope.MONITOR: _MONITOR_KEYS, BudgetScope.WORKSPACE: _MONITOR_KEYS,
               BudgetScope.LENS: _LENS_KEYS}


def add_budget_tables(conn: sqlite3.Connection) -> None:
    """The two budget tables, on every store open (``LensStore._db``)."""

    conn.executescript(_TABLES)


def _scope_key(scope: str, ident: str | None) -> str:
    return scope if scope == BudgetScope.LENS else f"{scope}:{ident}"


def _stored_limits(store: LensStore, scope: str, ident: str | None) -> dict[str, int]:
    if not store.exists() or (scope != BudgetScope.LENS and ident is None):
        return {}
    with store.connection() as conn:
        row = conn.execute("SELECT body FROM budget_limits WHERE scope = ?", (_scope_key(scope, ident),)).fetchone()
    return {} if row is None else dict(json.loads(row[0]))


def _config(key: str) -> int:
    return lens_setting(key)


def _resolved_limits(keys: dict[str, str], layers: list[tuple[str, dict[str, int]]]) -> dict[str, dict[str, Any]]:
    """Each key's value and where it came from (the first layer holding it, else config)."""

    out = {}
    for wire, setting in keys.items():
        for source, stored in layers:
            if wire in stored:
                out[wire] = {"value": stored[wire], "source": source}
                break
        else:
            out[wire] = {"value": _config(setting), "source": "config"}
    return out


def _monitor_workspace(store: LensStore, monitor_id: str) -> str | None:
    return store.get(monitor_id).get("workspace_id")


def monitor_limits(store: LensStore, monitor_id: str) -> dict[str, dict[str, Any]]:
    """The monitor's three effective limits, each ``{value, source: monitor|workspace|config}``."""

    workspace_id = _monitor_workspace(store, monitor_id)
    return _resolved_limits(_MONITOR_KEYS, [(BudgetScope.MONITOR, _stored_limits(store, BudgetScope.MONITOR, monitor_id)),
                                     (BudgetScope.WORKSPACE, _stored_limits(store, BudgetScope.WORKSPACE, workspace_id))])


def lens_limits(store: LensStore) -> dict[str, dict[str, Any]]:
    return _resolved_limits(_LENS_KEYS, [(BudgetScope.LENS, _stored_limits(store, BudgetScope.LENS, None))])


def _day_bounds(now: datetime) -> tuple[int, int]:
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return to_ms(day), to_ms(day + timedelta(days=1))


def spend_today(store: LensStore, now: datetime, *, monitor_id: str | None = None) -> int:
    """Tokens Lens turns that started on ``now``'s UTC day spent (one monitor's, or all)."""

    if not store.exists():
        return 0
    start, end = _day_bounds(now)
    sql, args = "SELECT COALESCE(SUM(tokens_used), 0) FROM episode_spend WHERE started_ms >= ? AND started_ms < ?", [
        start, end]
    if monitor_id is not None:
        sql, args = sql + " AND monitor_id = ?", [*args, monitor_id]
    with store.connection() as conn:
        return int(conn.execute(sql, args).fetchone()[0])


def over_daily_tokens(store: LensStore, monitor_id: str, now: datetime) -> bool:
    """True when the monitor's or all Lens's tokens today already fill their daily limit."""

    monitor_cap = monitor_limits(store, monitor_id)["daily_tokens"]["value"]
    lens_cap = lens_limits(store)["daily_tokens"]["value"]
    return (spend_today(store, now, monitor_id=monitor_id) >= monitor_cap
            or spend_today(store, now) >= lens_cap)


def episode_limits(store: LensStore, monitor_id: str, now: datetime) -> tuple[int, int]:
    """``(token_limit, call_limit)`` the next Episode's turn is armed with: the Episode's own limit,
    never more than what the monitor and all Lens have left today."""

    limits = monitor_limits(store, monitor_id)
    left_monitor = limits["daily_tokens"]["value"] - spend_today(store, now, monitor_id=monitor_id)
    left_lens = lens_limits(store)["daily_tokens"]["value"] - spend_today(store, now)
    tokens = max(0, min(limits["episode_tokens"]["value"], left_monitor, left_lens))
    return tokens, limits["episode_calls"]["value"]


def record_spend(store: LensStore, *, episode_id: str, monitor_id: str, started_ms: int,
                 summary: dict[str, Any]) -> None:
    """The turn's spend (``TurnTokenBudget.summary``), once per Episode."""

    with store.connection() as conn:
        conn.execute("INSERT OR REPLACE INTO episode_spend (episode_id, monitor_id, started_ms, tokens_used, "
                     "token_limit, calls_used, call_limit, stopped_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (episode_id, monitor_id, int(started_ms), int(summary.get("tokens_used") or 0),
                      summary.get("token_limit"), int(summary.get("calls_used") or 0), summary.get("call_limit"),
                      summary.get("stopped_by")))


# --- the wire -----------------------------------------------------------------


def _scope_param(params: dict[str, Any]) -> tuple[str, str | None]:
    """``(scope, id)`` of a set: a monitor's id, a workspace's (else the active one), or Lens."""

    scope = params.get("scope")
    if scope not in _SCOPE_KEYS:
        raise WireError(WireRefusal.UNKNOWN_ENUM, "scope")
    if scope == BudgetScope.MONITOR:
        if params.get("monitor_id") is None:
            raise WireError(WireRefusal.MISSING_KEY, "monitor_id")
        return scope, opaque_id(params["monitor_id"])
    if scope == BudgetScope.WORKSPACE:
        from .store_scope import active_workspace_id

        ident = params.get("workspace_id")
        ident = active_workspace_id() if ident is None else opaque_id(ident)
        if ident is None:
            raise WireError(WireRefusal.MISSING_KEY, "workspace_id")
        return scope, ident
    return scope, None


def _limit_values(scope: str, limits: Any) -> dict[str, int | None]:
    keys = _SCOPE_KEYS[scope]
    checked = checked_object(limits, (), keys)
    out: dict[str, int | None] = {}
    for wire, value in checked.items():
        if value is None:
            out[wire] = None
            continue
        minimum, maximum = lens_setting_bounds(keys[wire])
        try:
            out[wire] = bounded_int(value, minimum=minimum, maximum=maximum)
        except WireError:
            raise WireError(WireRefusal.INVALID_INTEGER, wire) from None
    return out


def set_limits(store: LensStore, params: dict[str, Any]) -> dict[str, Any]:
    """``runtime.lens.budget.set``: merge ``limits`` into the scope's stored values (``null`` clears)."""

    m = checked_object(params, {"scope", "limits"}, {"monitor_id", "workspace_id"})
    scope, ident = _scope_param(m)
    values = _limit_values(scope, m["limits"])
    if scope == BudgetScope.MONITOR:
        store.get(ident)  # monitor_not_found before anything is written
    stored = _stored_limits(store, scope, ident)
    for wire, value in values.items():
        if value is None:
            stored.pop(wire, None)
        else:
            stored[wire] = value
    with store.connection() as conn:
        if stored:
            conn.execute("INSERT OR REPLACE INTO budget_limits (scope, body, updated_ms) VALUES (?, ?, ?)",
                         (_scope_key(scope, ident), json.dumps(stored, sort_keys=True), to_ms(datetime.now(UTC))))
        else:
            conn.execute("DELETE FROM budget_limits WHERE scope = ?", (_scope_key(scope, ident),))
    view = {BudgetScope.MONITOR: {"monitor_id": ident}, BudgetScope.WORKSPACE: {"workspace_id": ident},
            BudgetScope.LENS: {}}[scope]
    return budget_view(store, view, datetime.now(UTC))


def _bounds(keys: dict[str, str]) -> dict[str, list[int]]:
    return {wire: list(lens_setting_bounds(setting)) for wire, setting in keys.items()}


def budget_view(store: LensStore, params: dict[str, Any], now: datetime) -> dict[str, Any]:
    """``runtime.lens.budget.get``: the Lens-wide limits and today's spend, plus the workspace's and
    (with ``monitor_id``) the monitor's effective limits, sources and today's spend."""

    m = checked_object(params or {}, (), {"monitor_id", "workspace_id"})
    from .store_scope import active_workspace_id

    lens = lens_limits(store)
    from .store_admission import turns_today

    out: dict[str, Any] = {
        "lens": {"limits": lens, "today": {"tokens": spend_today(store, now), "turns": turns_today(store, now)},
                 "bounds": _bounds(_LENS_KEYS)},
    }
    monitor_id = None if m.get("monitor_id") is None else opaque_id(m["monitor_id"])
    workspace_id = (opaque_id(m["workspace_id"]) if m.get("workspace_id") is not None
                    else _monitor_workspace(store, monitor_id) if monitor_id is not None
                    else active_workspace_id())
    out["workspace"] = {"workspace_id": workspace_id,
                        "limits": _resolved_limits(_MONITOR_KEYS, [(BudgetScope.WORKSPACE,
                                                             _stored_limits(store, BudgetScope.WORKSPACE, workspace_id))]),
                        "bounds": _bounds(_MONITOR_KEYS)}
    if monitor_id is not None:
        out["monitor"] = {"monitor_id": monitor_id, "limits": monitor_limits(store, monitor_id),
                          "today": {"tokens": spend_today(store, now, monitor_id=monitor_id)},
                          "bounds": _bounds(_MONITOR_KEYS)}
    return out
