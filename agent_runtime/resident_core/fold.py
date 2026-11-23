"""The resident core's folds: one stream frame applied to a copy of the core.

A Python port of the rules Eternia folds the same frames by, so the serve's
resident core and Eternia's held core move together:

* a ``patch`` frame's rows — Eternia ``lib/core/services/hermes/runtime/data/
  mission_read_model_patch.dart`` (``applyMissionPatchRow``);
* a ``persona_chat_turn`` overlay — ``mission_read_model_turn_fold.dart``
  (``applyMissionPersonaChatTurn``);
* a sequenced ``running_work`` section — the same file's
  ``applyMissionRunningWorkSection``.

Every function takes a WORKING core (a shallow copy of the resident one) and
writes only by copy-on-write down the levels it touches, so the resident core a
reader was handed is never moved under it. Each returns ``None`` on a clean
apply or the typed hazard Eternia would resync on, spelled the same way.

Two differences from Eternia, both because this core is a hermes core and not a
parsed one: the ``scope`` fold re-derives the ``active`` flag on every
``workspaces[]`` / ``realms[]`` row (Eternia derives them while it parses), and a
``running_work`` section is stored as hermes ships it (Eternia stamps its own
``measured_at`` beside it).
"""

from __future__ import annotations

from typing import Any

from agent_runtime.state_patches.models import (
    OFFICE_ACTOR_ENTITY,
    OFFICE_CONFLICT_ENTITY,
    OFFICE_SURFACE_ENTITY,
    PATCH_OP_REFRESH,
    PATCH_OP_REMOVE,
    PATCH_OP_UPSERT,
    PERSONA_ENTITY,
    SCOPE_ENTITY,
)

__layer__ = "lanes"

__all__ = [
    "apply_patch_row",
    "apply_persona_chat_turn",
    "apply_running_work_section",
]

#: ``office_store.models.ARCHIVED_LEDGER_CAP``: the store keeps the LAST this-many keys.
_ARCHIVED_LEDGER_CAP = 5000

#: The entities addressed as a top-level keyed table (Dart ``_entitySection``).
_ENTITY_SECTION = {"persona_instance": "persona_instances", "incident": "incidents"}

_SCOPE_FIELDS = frozenset({"active_workspace_id", "active_realm_id"})
_OFFICE_SURFACE_FIELDS = frozenset({"folders", "revision", "updated_at"})


def _is_oversize(value: Any) -> bool:
    return isinstance(value, dict) and value.get("oversize") is True and "bytes" in value


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def apply_patch_row(working: dict[str, Any], patch: dict[str, Any]) -> str | None:
    """One op entry ``{entity, id, op, changed?, created?}`` applied to ``working``."""

    entity = _text(patch.get("entity"))
    row_id = _text(patch.get("id"))
    op = _text(patch.get("op"))
    if not entity or not row_id:
        return f"patch_malformed:{entity}/{row_id}"
    handler = _NESTED_HANDLERS.get(entity)
    if handler is not None:
        return handler(working, row_id, op, patch)
    section = _ENTITY_SECTION.get(entity)
    if section is None:
        return f"patch_unknown_entity:{entity}"
    if op == PATCH_OP_REMOVE:
        table = working.get(section)
        if isinstance(table, dict):
            working[section] = {key: row for key, row in table.items() if key != row_id}
        return None
    if op == PATCH_OP_REFRESH:
        return f"patch_refresh:{entity}/{row_id}"
    if op != PATCH_OP_UPSERT:
        return f"patch_unknown_op:{op}"
    changed = patch.get("changed")
    if not isinstance(changed, dict) or not changed:
        return f"patch_malformed:{entity}/{row_id}"
    if any(_is_oversize(value) for value in changed.values()):
        return f"patch_oversize:{entity}/{row_id}"
    table = working.get(section)
    if not isinstance(table, dict):
        return f"patch_without_target:{entity}/{row_id}"
    row = table.get(row_id)
    created = patch.get("created") is True
    if not isinstance(row, dict) and not created:
        return f"patch_without_target:{entity}/{row_id}"
    next_row = {} if created or not isinstance(row, dict) else dict(row)
    next_row.update({str(key): value for key, value in changed.items()})
    next_table = dict(table)
    next_table[row_id] = next_row
    working[section] = next_table
    return None


def _apply_scope(working: dict[str, Any], row_id: str, op: str, patch: dict[str, Any]) -> str | None:
    """The two scope pointers, then every row's ``active`` flag re-derived from them."""

    if op == PATCH_OP_REFRESH:
        return f"patch_refresh:{SCOPE_ENTITY}/{row_id}"
    if op != PATCH_OP_UPSERT:
        return f"patch_unsupported_op:{SCOPE_ENTITY}/{op}"
    changed = patch.get("changed")
    if not isinstance(changed, dict) or not changed:
        return f"patch_malformed:{SCOPE_ENTITY}/{row_id}"
    for key, value in changed.items():
        if str(key) not in _SCOPE_FIELDS:
            return f"patch_unknown_field:{SCOPE_ENTITY}/{key}"
        if _is_oversize(value):
            return f"patch_oversize:{SCOPE_ENTITY}/{row_id}"
    for key, value in changed.items():
        working[str(key)] = value
    for section, pointer in (("workspaces", "active_workspace_id"), ("realms", "active_realm_id")):
        rows = working.get(section)
        if isinstance(rows, list):
            active = working.get(pointer)
            working[section] = [
                {**row, "active": row.get("id") == active} if isinstance(row, dict) else row
                for row in rows
            ]
    return None


def _apply_office_surface(working: dict[str, Any], row_id: str, op: str, patch: dict[str, Any]) -> str | None:
    if op == PATCH_OP_REFRESH:
        return f"patch_refresh:{OFFICE_SURFACE_ENTITY}/{row_id}"
    if op != PATCH_OP_UPSERT:
        return f"patch_unknown_op:{op}"
    changed = patch.get("changed")
    if not isinstance(changed, dict) or not changed:
        return f"patch_malformed:{OFFICE_SURFACE_ENTITY}/{row_id}"
    for key in changed:
        if str(key) not in _OFFICE_SURFACE_FIELDS:
            return f"patch_unknown_field:{OFFICE_SURFACE_ENTITY}/{key}"
    if any(_is_oversize(value) for value in changed.values()):
        return f"patch_oversize:{OFFICE_SURFACE_ENTITY}/{row_id}"
    offices = working.get("offices")
    office = offices.get(row_id) if isinstance(offices, dict) else None
    if not isinstance(offices, dict) or not isinstance(office, dict):
        return f"patch_without_target:{OFFICE_SURFACE_ENTITY}/{row_id}"
    working["offices"] = {**offices, row_id: {**office, **{str(key): value for key, value in changed.items()}}}
    return None


def _split_actor_id(row_id: str) -> tuple[str, str] | None:
    split = row_id.find("/")
    if split <= 0 or split == len(row_id) - 1:
        return None
    return row_id[:split], row_id[split + 1 :]


def _apply_office_actor(working: dict[str, Any], row_id: str, op: str, patch: dict[str, Any]) -> str | None:
    """Replace, insert (in ``actor_key`` order) or splice out one actor of
    ``offices[<workspace_id>].actors``, deriving ``actor_count`` and the archive
    ledger on the ops that move the list's length (Dart ``_applyOfficeActorPatch``)."""

    address = _split_actor_id(row_id)
    if address is None:
        return f"patch_malformed:{OFFICE_ACTOR_ENTITY}/{row_id}"
    workspace_id, actor_key = address
    replacement: dict[str, Any] | None = None
    if op == PATCH_OP_REFRESH:
        return f"patch_refresh:{OFFICE_ACTOR_ENTITY}/{row_id}"
    if op == PATCH_OP_UPSERT:
        changed = patch.get("changed")
        if not isinstance(changed, dict) or not changed:
            return f"patch_malformed:{OFFICE_ACTOR_ENTITY}/{row_id}"
        if any(_is_oversize(value) for value in changed.values()):
            return f"patch_oversize:{OFFICE_ACTOR_ENTITY}/{row_id}"
        replacement = {str(key): value for key, value in changed.items()}
    elif op != PATCH_OP_REMOVE:
        return f"patch_unknown_op:{op}"
    offices = working.get("offices")
    office = offices.get(workspace_id) if isinstance(offices, dict) else None
    actors = office.get("actors") if isinstance(office, dict) else None
    if not isinstance(offices, dict) or not isinstance(office, dict) or not isinstance(actors, list):
        return None if op == PATCH_OP_REMOVE else f"patch_without_target:{OFFICE_ACTOR_ENTITY}/{row_id}"
    next_actors = list(actors)
    index = next(
        (at for at, row in enumerate(next_actors) if isinstance(row, dict) and _text(row.get("actor_key")) == actor_key),
        -1,
    )
    derives = op == PATCH_OP_REMOVE or index < 0
    if derives:
        held_count = _int_or_none(office.get("actor_count"))
        held_truncated = _int_or_none(office.get("actors_truncated")) or 0
        if held_truncated > 0 or (held_count is not None and held_count != len(actors)):
            return f"patch_truncated_base:{OFFICE_ACTOR_ENTITY}/{row_id}"
    if op == PATCH_OP_REMOVE:
        if index >= 0:
            del next_actors[index]
    elif index >= 0:
        next_actors[index] = replacement
    else:
        at = 0
        while at < len(next_actors):
            row = next_actors[at]
            key = _text(row.get("actor_key")) if isinstance(row, dict) else ""
            if key > actor_key:
                break
            at += 1
        next_actors.insert(at, replacement)
    next_office = {**office, "actors": next_actors}
    if derives:
        next_office["actor_count"] = len(next_actors)
    ledger = _folded_archive_ledger(office.get("archived_actor_keys"), actor_key, archived=op == PATCH_OP_REMOVE)
    if ledger is not None:
        next_office["archived_actor_keys"] = ledger
    working["offices"] = {**offices, workspace_id: next_office}
    return None


def _folded_archive_ledger(held: Any, actor_key: str, *, archived: bool) -> list[Any] | None:
    ledger = list(held) if isinstance(held, list) else []
    present = any(_text(key) == actor_key for key in ledger)
    if archived:
        if present:
            return None
        ledger.append(actor_key)
        return ledger[-_ARCHIVED_LEDGER_CAP:]
    if not present:
        return None
    return [key for key in ledger if _text(key) != actor_key]


def _apply_office_conflict(working: dict[str, Any], row_id: str, op: str, patch: dict[str, Any]) -> str | None:
    if op == PATCH_OP_REFRESH:
        return f"patch_refresh:{OFFICE_CONFLICT_ENTITY}/{row_id}"
    if op != PATCH_OP_REMOVE:
        return f"patch_unknown_op:{op}"
    address = _split_actor_id(row_id)
    if address is None:
        return f"patch_malformed:{OFFICE_CONFLICT_ENTITY}/{row_id}"
    workspace_id, actor_key = address
    offices = working.get("offices")
    office = offices.get(workspace_id) if isinstance(offices, dict) else None
    held = office.get("conflict_actor_keys") if isinstance(office, dict) else None
    if not isinstance(held, list) or not any(_text(key) == actor_key for key in held):
        return None
    next_keys = [key for key in held if _text(key) != actor_key]
    working["offices"] = {**offices, workspace_id: {**office, "conflict_actor_keys": next_keys}}
    return None


def _apply_persona(working: dict[str, Any], row_id: str, op: str, patch: dict[str, Any]) -> str | None:
    """A row of the ``agents`` list, keyed by ``persona_id``: a ``created`` upsert
    replaces or inserts among the persona rows (before the persona-instance rows),
    a subset upsert merges onto a held row."""

    if op == PATCH_OP_REFRESH:
        return f"patch_refresh:{PERSONA_ENTITY}/{row_id}"
    if op != PATCH_OP_UPSERT:
        return f"patch_unknown_op:{op}"
    changed = patch.get("changed")
    if not isinstance(changed, dict) or not changed:
        return f"patch_malformed:{PERSONA_ENTITY}/{row_id}"
    if any(_is_oversize(value) for value in changed.values()):
        return f"patch_oversize:{PERSONA_ENTITY}/{row_id}"
    agents = working.get("agents")
    if not isinstance(agents, list):
        return f"patch_without_target:{PERSONA_ENTITY}/{row_id}"
    created = patch.get("created") is True
    rows = list(agents)
    index = next(
        (at for at, row in enumerate(rows) if isinstance(row, dict) and _text(row.get("persona_id")) == row_id),
        -1,
    )
    if index < 0 and not created:
        return f"patch_without_target:{PERSONA_ENTITY}/{row_id}"
    held = rows[index] if index >= 0 else None
    row = {} if created or not isinstance(held, dict) else dict(held)
    row.update({str(key): value for key, value in changed.items()})
    if index >= 0:
        rows[index] = row
    else:
        at = 0
        while at < len(rows):
            other = rows[at]
            if (
                not isinstance(other, dict)
                or other.get("runtime_agent_kind") == "persona_instance"
                or _text(other.get("persona_id")) > row_id
            ):
                break
            at += 1
        rows.insert(at, row)
    working["agents"] = rows
    return None


_NESTED_HANDLERS = {
    OFFICE_ACTOR_ENTITY: _apply_office_actor,
    OFFICE_SURFACE_ENTITY: _apply_office_surface,
    SCOPE_ENTITY: _apply_scope,
    OFFICE_CONFLICT_ENTITY: _apply_office_conflict,
    PERSONA_ENTITY: _apply_persona,
}


def apply_running_work_section(working: dict[str, Any], frame: dict[str, Any]) -> str | None:
    """A ``running_work`` frame's section replaces the core's, whole."""

    section = frame.get("running_work")
    if not isinstance(section, dict):
        return "running_work_section_malformed"
    working["running_work"] = section
    return None


def apply_persona_chat_turn(working: dict[str, Any], frame: dict[str, Any]) -> str | None:
    """One root's turn rows: its channel (superseding the instance's other channel
    when the id is new), its instance row, its history row (removed when
    ``null``), ``running_work``, and every ``evicted_roots`` history row removed."""

    root = frame.get("root_chat_session_id")
    instance_id = frame.get("persona_instance_id")
    channel = frame.get("operator_channel")
    instance = frame.get("persona_instance")
    running_work = frame.get("running_work")
    history = frame.get("persona_chat_history")
    evicted_raw = frame.get("evicted_roots")
    channel_id = channel.get("channel_id") if isinstance(channel, dict) else None
    if (
        not isinstance(root, str)
        or not root
        or (evicted_raw is not None and (not isinstance(evicted_raw, list) or not all(isinstance(item, str) for item in evicted_raw)))
        or not isinstance(instance_id, str)
        or not instance_id
        or not isinstance(channel_id, str)
        or not channel_id
        or not isinstance(instance, dict)
        or not isinstance(running_work, dict)
        or (history is not None and not isinstance(history, dict))
    ):
        return f"turn_fold_malformed:{root if isinstance(root, str) and root else '?'}"
    evicted = set(evicted_raw or ())
    held_channels = working.get("operator_channels")
    channels = dict(held_channels) if isinstance(held_channels, dict) else {}
    if channel_id not in channels:
        owner = channel.get("persona_instance_id") or instance_id
        channels = {
            key: held
            for key, held in channels.items()
            if not (isinstance(held, dict) and held.get("persona_instance_id") == owner)
        }
    channels[channel_id] = channel
    working["operator_channels"] = channels
    held_instances = working.get("persona_instances")
    working["persona_instances"] = {**(held_instances if isinstance(held_instances, dict) else {}), instance_id: instance}
    held_history = working.get("persona_chat_history")
    working["persona_chat_history"] = _with_history_row(
        held_history if isinstance(held_history, list) else [], root=root, row=history, evicted=evicted
    )
    working["running_work"] = running_work
    return None


def _with_history_row(rows: list[Any], *, root: str, row: dict[str, Any] | None, evicted: set[str]) -> list[Any]:
    """``rows`` with the root's row replaced in place, inserted in creation order
    (newest ``created_at`` first, session id breaking ties) when absent, or removed
    when ``row`` is ``None``; every ``evicted`` session's row dropped."""

    kept: list[Any] = []
    replaced = False
    for existing in rows:
        session = existing.get("session_id") if isinstance(existing, dict) else None
        if isinstance(session, str) and session != root and session in evicted:
            continue
        if isinstance(existing, dict) and session == root:
            if row is not None and not replaced:
                kept.append(row)
            replaced = True
            continue
        kept.append(existing)
    if replaced or row is None:
        return kept
    key = _creation_key(row, root)
    at = len(kept)
    for index, held in enumerate(kept):
        if not isinstance(held, dict):
            continue
        session = held.get("session_id")
        if key > _creation_key(held, session if isinstance(session, str) else ""):
            at = index
            break
    kept.insert(at, row)
    return kept


def _creation_key(row: dict[str, Any], session: str) -> tuple[bool, str, str]:
    created = row.get("created_at")
    created = created if isinstance(created, str) else None
    return (created is not None, created or "", session)
