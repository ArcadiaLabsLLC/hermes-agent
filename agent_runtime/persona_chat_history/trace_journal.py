"""The chat-turn trace, paged by TURN: settled turns the event tail no longer covers come from the turn journal.

The chat lane of ``persona_chat_trace`` is a bounded tail of trace EVENTS
(``DEFAULT_PERSONA_CHAT_MESSAGE_TAIL`` = 40 entries). A turn emits a started and
a finished entry per tool call plus progress and thinking rows, so 40 entries
cover a turn or two — while the history beside it covers twenty. The operator
conversation derives its ``tool_call`` rows from those entries, so after a
restart or a chat reopen every earlier turn in the window lost its tools (live
2026-10-02, session ``…b3e699ad0c12``: the 02:43–02:46Z turns had none by
02:47Z), and the oldest turn the tail reached was cut part-way through.

Each turn's tool calls are already durable: the turn journal
(``mission_chat_turns``) persists the turn's ``tool`` elements as it runs. So
for the last ``tail`` SETTLED turns of the session, a turn whose trace entries
are absent or were cut by the tail is answered from its journal record instead:
its trace entries (if any) are dropped and one compact ``tool_finished`` entry
per journalled tool call takes their place. A turn is therefore either wholly
from the trace or wholly from the journal, never half of each. In-flight turns
are left to the trace, which is where their live state is.

The backfilled entries are COMPACT — name, status, summary, files, duration,
exit code and command; never the output / input / result blocks — and the whole
backfill is capped at :data:`TRACE_JOURNAL_BACKFILL_CEILING` entries, newest
turns first, with the overflow accounted (``journal_backfill_capped``) rather
than silently dropped. Each carries ``source: "mission_chat_turn_journal"`` so a
reader can tell a journalled row from a live one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..clock import parse_iso
from ..mission_chat_turns.reads import mission_chat_turn_records
from ..mission_chat_turns.states import TERMINAL_TURN_STATES
from ..serde import safe_assignment_text, safe_assignment_token
from ..transcript_order import TURN_SEQ_CONTENT

__layer__ = "stores"

__all__ = [
    "JOURNAL_TRACE_SOURCE",
    "TRACE_JOURNAL_BACKFILL_CEILING",
    "page_chat_trace_by_turn",
]

JOURNAL_TRACE_SOURCE = "mission_chat_turn_journal"

#: The most journal-sourced entries one instance's trace row may carry.
TRACE_JOURNAL_BACKFILL_CEILING = 200


def _turn_key(value: Any) -> str | None:
    return safe_assignment_token(value) or None


def _journal_entries(record: dict[str, Any], *, persona_id: str, turn_id: str) -> list[dict[str, Any]]:
    started = parse_iso(record.get("started_at") or record.get("updated_at"))
    entries: list[dict[str, Any]] = []
    for index, element in enumerate(
        element for element in record.get("elements") or [] if element.get("kind") == "tool"
    ):
        entry: dict[str, Any] = {
            "kind": "harness_trace",
            "source": JOURNAL_TRACE_SOURCE,
            "task_id": None,
            "persona_id": persona_id,
            "run_id": None,
            "turn_id": turn_id,
            "turn_seq": TURN_SEQ_CONTENT,
            "stage_id": None,
            "event": "tool_finished",
            "tool_name": safe_assignment_text(element.get("name"), limit=120) or "tool",
            "tool_call_id": element.get("tool_call_id"),
            "tool_input": element.get("tool_input"),
            "tool_result": element.get("tool_result"),
            "summary": safe_assignment_text(element.get("summary"), limit=1200),
            "files": list(element.get("files") or [])[:20],
            "status": safe_assignment_token(element.get("status")) or "ok",
            # The journal stamps the turn, not each call: the turn start plus the
            # element's position keeps the calls in their recorded order under any
            # sort, and never lands outside the turn.
            "ts": started + timedelta(microseconds=index) if started is not None else None,
        }
        command = safe_assignment_text(element.get("command"), limit=500)
        if command:
            entry["command"] = command
        for field in ("duration_ms", "exit_code"):
            value = element.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                entry[field] = value
        entries.append(entry)
    return entries


def page_chat_trace_by_turn(
    entries: list[dict[str, Any]],
    *,
    session_id: str,
    persona_id: str,
    cut_turn_ids: set[str],
    tail: int,
    accountant: Any = None,
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    """``entries`` with every settled turn the tail missed or cut answered from the journal."""

    try:
        records = mission_chat_turn_records(session_id=session_id)
    except Exception:  # noqa: BLE001 — an unreadable journal leaves the trace as it was
        return entries
    settled = [
        record
        for record in records
        if safe_assignment_token(record.get("state")) in TERMINAL_TURN_STATES
    ][-max(int(tail), 1):]
    covered = {_turn_key(entry.get("turn_id")) for entry in entries} - {None}
    cut = {_turn_key(turn_id) for turn_id in cut_turn_ids} - {None}
    replace: set[str] = set()
    backfill: list[dict[str, Any]] = []
    budget = TRACE_JOURNAL_BACKFILL_CEILING
    capped = 0
    # Newest settled turn first, so the ceiling spends itself on the turns an
    # operator is most likely to be reading.
    for record in reversed(settled):
        turn_id = _turn_key(record.get("turn_id")) or _turn_key(record.get("client_message_id"))
        if turn_id is None or (turn_id in covered and turn_id not in cut):
            continue
        turn_entries = _journal_entries(record, persona_id=persona_id, turn_id=turn_id)
        if not turn_entries:
            continue
        if len(turn_entries) > budget:
            capped += len(turn_entries)
            continue
        budget -= len(turn_entries)
        replace.add(turn_id)
        backfill.extend(turn_entries)
    if not replace and not capped:
        return entries
    kept = [entry for entry in entries if _turn_key(entry.get("turn_id")) not in replace]
    if accountant is not None:
        accountant.consider(len(backfill) + capped)
        accountant.include(len(backfill))
        if capped:
            accountant.drop("journal_backfill_capped", count=capped, entity_id=entity_id, by_design=True)
    return sorted(kept + backfill, key=_entry_sort_key)


def _entry_sort_key(entry: dict[str, Any]) -> tuple[int, float, str]:
    ts = entry.get("ts")
    if not hasattr(ts, "timestamp"):
        ts = parse_iso(ts)
    try:
        return (1, ts.timestamp(), "")
    except Exception:  # noqa: BLE001 — unparseable stamps sink to the front, stably
        return (0, 0.0, str(entry.get("ts") or ""))
