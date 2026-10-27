"""The exit door's admission reads over the receipts table (plan
``LENS_EXTENSIONS_2026-10-27.md`` §3): a rule's previous receipt (the W6 cooldown) and
the turns every monitor began today (the global ``daily_turn_budget``).

A module of its own, opened through ``LensStore.connection()``: ``store.py`` sits near
its ADR 0007 ceiling, and these are queries ``trigger.LensForge.admit`` asks, not
lifecycle the store owns.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

from .store import LensStore, ReceiptOutcome, to_ms

__layer__ = "stores"


def last_rule_receipt_ms(store: LensStore, monitor_id: str, rule_id: str) -> int | None:
    """``started_ms`` of the newest receipt of any Episode of ``rule_id`` that was not itself
    ``cooled`` — so a rule that keeps flapping inside its cooldown is measured from the last
    admission that counted, and is admitted again once the cooldown has passed."""

    if not store.exists():
        return None
    with store.connection() as conn:
        row = conn.execute(
            "SELECT MAX(r.started_ms) FROM receipts r JOIN episodes e ON e.id = r.episode_id "
            "WHERE e.monitor_id = ? AND e.rule_id = ? AND r.outcome != ?",
            (monitor_id, rule_id, ReceiptOutcome.COOLED.value)).fetchone()
    return None if row is None or row[0] is None else int(row[0])


#: The receipt's ``tool_admission`` when it ran (or began) a turn — the model spend a budget counts.
TURN_ADMISSION = "read_only"


def turns_today(store: LensStore, now: datetime) -> int:
    """Turns every monitor began on ``now``'s UTC day: receipts that held a read-only turn.
    A digest is ONE turn: its members' receipts (``digested``) share the leader's."""

    if not store.exists():
        return 0
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    with store.connection() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM receipts WHERE started_ms >= ? AND started_ms < ? AND tool_admission = ? "
            "AND outcome != ?",
            (to_ms(day), to_ms(day + timedelta(days=1)), TURN_ADMISSION, ReceiptOutcome.DIGESTED.value)).fetchone()[0])
