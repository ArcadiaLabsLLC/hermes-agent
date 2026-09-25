"""Which instance a channel is: channel keys, the canonical instance, recency, the merged trace, and the ancestry graph."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

from ..models import PersonaInstance
from ..persona_assignments.identity import persona_instance_id_for
from ..persona_chat_history.history_rows import _canonical_persona_id
from ..serde import safe_assignment_text, safe_assignment_token

from .vocabulary import (
    _CHAT_INSTANCE_MODES,
    _first_text,
    _parse_time,
    _safe_instance_id,
    _safe_session,
)

if TYPE_CHECKING:  # the builder imports this module; annotation only
    from .summary import _OperatorChannelBuilder

__layer__ = "stores"


def _operator_conversation_relationships(
    builders: Iterable["_OperatorChannelBuilder"],
) -> dict[str, tuple[str, str | None]]:
    """Resolve conversation ancestry from the persisted instance graph.

    ``PersonaInstance.steered_by`` is the authority.  The conversation wire has
    one parent field, so it follows the store's primary-parent convention (the
    first entry, mirrored by ``spawned_by``).  A missing/out-of-roster parent or
    a cycle degrades to a standalone thread; no persona id is promoted to root
    by convention.
    """

    instances_by_id: dict[str, PersonaInstance] = {}
    channel_by_instance_id: dict[str, str] = {}
    canonical_instances: dict[str, PersonaInstance] = {}
    for builder in builders:
        history = builder._bound_history() or _latest_history(builder.history_rows)
        trace = _merged_trace(builder.trace_rows)
        canonical = _canonical_instance(builder.instances, history=history)
        if canonical is None:
            continue
        persona_id = _first_text(
            getattr(canonical, "persona_id", None),
            history.get("persona_id") if history else None,
            trace.get("persona_id") if trace else None,
        )
        persona_id = _canonical_persona_id(persona_id) or persona_id or "unknown"
        canonical_id = _first_text(
            getattr(canonical, "id", None),
            history.get("persona_instance_id") if history else None,
            trace.get("persona_instance_id") if trace else None,
            persona_instance_id_for(persona_id),
        )
        session_id = _first_text(
            history.get("session_id") if history else None,
            trace.get("session_id") if trace else None,
            getattr(canonical, "session_id", None),
        )
        channel_id = f"{persona_id}::{session_id or canonical_id}"
        canonical_instances[canonical_id] = canonical
        for instance in builder.instances:
            instance_id = _safe_instance_id(instance)
            if not instance_id:
                continue
            instances_by_id[instance_id] = instance
            channel_by_instance_id[instance_id] = channel_id

    relationships: dict[str, tuple[str, str | None]] = {}
    for canonical_id, instance in canonical_instances.items():
        instance_id = _safe_instance_id(instance)
        if not instance_id:
            continue
        own_channel_id = channel_by_instance_id[instance_id]
        parent_ids = [
            parent_id
            for raw in list(getattr(instance, "steered_by", None) or [])
            if (parent_id := safe_assignment_text(raw, limit=160))
        ]
        primary_parent_id = parent_ids[0] if parent_ids else None
        parent_thread_id = channel_by_instance_id.get(primary_parent_id or "")
        root_thread_id = own_channel_id
        cursor = primary_parent_id
        seen = {instance_id}
        ancestry_valid = True
        while cursor:
            if cursor in seen:
                ancestry_valid = False
                break
            seen.add(cursor)
            parent_channel_id = channel_by_instance_id.get(cursor)
            parent = instances_by_id.get(cursor)
            if parent_channel_id is None or parent is None:
                ancestry_valid = False
                break
            root_thread_id = parent_channel_id
            next_parents = [
                parent_id
                for raw in list(getattr(parent, "steered_by", None) or [])
                if (parent_id := safe_assignment_text(raw, limit=160))
            ]
            cursor = next_parents[0] if next_parents else None
        if not ancestry_valid:
            root_thread_id = own_channel_id
            parent_thread_id = None
        relationships[canonical_id] = (root_thread_id, parent_thread_id)
    return relationships


def _channel_key_for_instance(instance: PersonaInstance) -> str:
    mode = safe_assignment_token(getattr(instance, "mode", None))
    session_id = _safe_session(getattr(instance, "session_id", None))
    persona_id = _canonical_persona_id(getattr(instance, "persona_id", None)) or "unknown"
    if session_id and mode in _CHAT_INSTANCE_MODES:
        return f"session:{session_id}"
    task_id = safe_assignment_text(getattr(instance, "current_task_id", None), limit=160)
    if task_id:
        return f"task:{task_id}:{persona_id}:{_safe_instance_id(instance)}"
    return f"instance:{_safe_instance_id(instance) or persona_instance_id_for(persona_id)}"


def _canonical_instance(
    instances: list[PersonaInstance],
    *,
    history: dict[str, Any] | None,
) -> PersonaInstance | None:
    if not instances:
        return None
    history_instance = safe_assignment_text(
        (history or {}).get("persona_instance_id"), limit=160
    )
    if history_instance:
        for instance in instances:
            if _safe_instance_id(instance) == history_instance:
                return instance
    canonical_profile = [
        instance
        for instance in instances
        if (_safe_instance_id(instance) or "").startswith("personainst_profile_")
    ]
    if canonical_profile:
        return _newest_instance(canonical_profile)
    return _newest_instance(instances)


def _newest_instance(instances: list[PersonaInstance]) -> PersonaInstance:
    return sorted(instances, key=_instance_recency, reverse=True)[0]


def _source_instance_ids_conflict(
    source_instance_ids: list[str],
    *,
    instances: list[PersonaInstance],
    history_rows: list[dict[str, Any]],
    trace_rows: list[dict[str, Any]],
) -> bool:
    if len(source_instance_ids) <= 1:
        return False
    rows = [
        *history_rows,
        *(row for row in trace_rows if not row.get("_mirrored_to_root")),
    ]
    sessions = {
        session
        for session in [
            *(_safe_session(getattr(instance, "session_id", None)) for instance in instances),
            *(_safe_session(row.get("session_id")) for row in rows),
        ]
        if session
    }
    if len(sessions) > 1:
        return True
    personas = {
        persona
        for persona in [
            *(
                _canonical_persona_id(getattr(instance, "persona_id", None))
                for instance in instances
            ),
            *(_canonical_persona_id(row.get("persona_id")) for row in rows),
        ]
        if persona
    }
    if len(personas) > 1:
        return True
    if any(item.startswith("personainst_operator_") for item in source_instance_ids):
        return False
    # Reaching here means one persona and at most one session. Within that,
    # id multiplicity contributed ONLY by history/trace row attribution is not
    # a projection collision: a pre-per-instance-session chat row can sit on
    # the persona's canonical session while naming the placement-backed sibling
    # that answered it (live evidence 2026-08-31: the neko_supervisor canonical
    # channel carried a 2026-07-20 history row attributed to
    # personainst_neko_supervisor_agent_47a47348). Nothing mints that shape
    # anymore — sessions are per-instance — so warning on it is a permanent,
    # operator-unactionable false positive (the canonical singleton cannot be
    # retired). Two live instance ROWS folding onto one channel remain the
    # genuine collision.
    instance_ids = {
        instance_id
        for instance_id in (_safe_instance_id(instance) for instance in instances)
        if instance_id
    }
    return len(instance_ids) > 1


def _instance_recency(instance: PersonaInstance) -> tuple[int, str]:
    for value in (
        getattr(instance, "updated_at", None),
        getattr(instance, "last_heartbeat_at", None),
    ):
        parsed = _parse_time(value)
        if parsed is not None:
            return (1, parsed.isoformat())
    return (0, _safe_instance_id(instance) or "")


def _latest_history(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return sorted(rows, key=lambda row: _row_recency(row), reverse=True)[0]


def _row_recency(row: dict[str, Any]) -> tuple[int, str]:
    for key in ("updated_at", "created_at"):
        parsed = _parse_time(row.get(key))
        if parsed is not None:
            return (1, parsed.isoformat())
    return (0, str(row.get("session_id") or ""))


def _merged_trace(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    first = next((row for row in rows if not row.get("_mirrored_to_root")), rows[0])
    entries_by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        for entry in list(row.get("entries") or []):
            if not isinstance(entry, dict):
                continue
            entries_by_key[_trace_entry_key(entry)] = entry
    entries = sorted(entries_by_key.values(), key=_trace_entry_sort_key)
    return {
        "persona_instance_id": first.get("persona_instance_id"),
        "persona_id": first.get("persona_id"),
        "task_id": first.get("task_id"),
        "session_id": first.get("session_id"),
        "entries": entries,
    }


def _trace_entry_key(entry: dict[str, Any]) -> str:
    return "|".join(
        str(entry.get(key) or "")
        for key in ("ts", "event", "tool_name", "summary", "run_id", "status")
    )


def _trace_entry_sort_key(entry: dict[str, Any]) -> tuple[int, str]:
    parsed = _parse_time(entry.get("ts"))
    if parsed is not None:
        return (1, parsed.isoformat())
    return (0, str(entry.get("ts") or ""))
