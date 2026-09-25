"""The available and used skill rows a turn reports, with their publishability and receipts.

Separate because it reads the turn's trace and each skill's files, on top of
the resolver's reach answer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from ..persona_assignments import safe_assignment_text, safe_assignment_token
from .skills_resolver import (
    _SkillObservabilityResolver,
    _installed_skill_catalog,
    _skill_candidate_content_hash,
)

__layer__ = "stores"
__all__ = [
    "available_skills_context",
    "used_skills_context",
    "_chat_metadata",
]


def available_skills_context(
    *,
    accessible_skills: list[dict[str, Any]] | None = None,
    limit: int = 160,
    skill_resolver: _SkillObservabilityResolver | None = None,
) -> list[dict[str, Any]]:
    """Redaction-safe installed skill catalog for Mission Control.

    This deliberately exposes names and frontmatter descriptions only. It never
    returns SKILL.md bodies or referenced files.
    """

    accessible_by_name = {
        safe_assignment_token(item.get("name")): item
        for item in accessible_skills or []
        if isinstance(item, dict) and safe_assignment_token(item.get("name"))
    }
    rows: list[dict[str, Any]] = []
    shared_by_name: dict[str, dict[str, Any]] = {}
    realm_rows: list[dict[str, Any]] = []
    if skill_resolver is not None:
        # Hoisted to once-per-build: the build-scoped resolver memoizes both
        # walks, so every projected persona shares one shared-catalog walk + one
        # realm publish-state read instead of repeating both per persona.
        shared_by_name = skill_resolver.shared_catalog()
        realm_rows = skill_resolver.realm_publish_states()
    else:
        try:
            from ..skills_inventory import build_realm_publish_states, build_shared_catalog

            _, _, catalog = build_shared_catalog()
            shared_by_name = {
                str(item.get("slug") or ""): item
                for item in catalog
                if isinstance(item, dict)
            }
            realm_rows = build_realm_publish_states()
        except Exception:
            pass
    installed = _installed_skill_catalog()
    from agent_runtime.skill_resolution import (
        resolve_skills,
        skill_runtime_compatibility,
    )

    installed_names = [
        safe_assignment_token(item.get("name"))
        for item in installed
        if isinstance(item, dict) and safe_assignment_token(item.get("name"))
    ]
    resolutions = (
        skill_resolver.resolve(installed_names)
        if skill_resolver is not None
        else resolve_skills(installed_names)
    )
    if isinstance(installed, list):
        for skill in installed:
            if not isinstance(skill, dict):
                continue
            name = safe_assignment_token(skill.get("name"))
            if not name:
                continue
            accessible = accessible_by_name.get(name)
            status = "accessible" if accessible else "available"
            if accessible and isinstance(accessible.get("status"), str):
                status = safe_assignment_token(accessible.get("status")) or status
            resolution = resolutions.get(name)
            if resolution is None:
                continue
            selected = resolution.candidate
            compatibility = skill_runtime_compatibility(
                selected, surface="mission_chat", root_node_mode=False
            )
            shared = shared_by_name.get(name)
            realm_sync = _skill_realm_sync(name, realm_rows) if shared else []
            # A skill resolved from a profile-local / external root is
            # STRUCTURALLY unable to reach a realm — realm publish reads the
            # shared root only. Such a row previously carried an empty
            # ``realm_sync`` list, which reads as "no realms configured" rather
            # than "cannot travel": a silent omission. Say it, with a typed
            # reason. Only the CHEAP source-kind verdict is computed here; the
            # installer-ownership / promotability classification hashes package
            # trees and belongs to the on-demand ``skills inventory`` /
            # ``skills publishable`` surfaces, never this per-persona build.
            publishable, publishable_reason = _skill_publishability(
                selected.source_kind if selected else None
            )
            # Assigned rows already carry their resolver receipt; canonical
            # shared rows reuse the shared catalog's content hash. Avoid hashing
            # every unassigned profile-local package during every snapshot.
            content_hash = (
                accessible.get("content_hash")
                if accessible
                else shared.get("content_hash") if shared else None
            )
            if content_hash is None and skill_resolver is None:
                content_hash = _skill_candidate_content_hash(selected)
            rows.append(
                {
                    "name": name,
                    "kind": "skill",
                    "status": status,
                    "load_state": (
                        safe_assignment_token(accessible.get("load_state"))
                        if accessible
                        else "catalog_only"
                    )
                    or ("assigned_not_loaded" if accessible else "catalog_only"),
                    "hash_tracked": content_hash is not None,
                    "source": "installed_skill_catalog",
                    "category": safe_assignment_token(skill.get("category")) or "skills",
                    "description": safe_assignment_text(skill.get("description"), limit=220) or "",
                    "loadable": bool(
                        resolution.status == "resolved"
                        and compatibility.get("compatible")
                    ),
                    "resolution_status": resolution.status,
                    "source_kind": selected.source_kind if selected else None,
                    "content_hash": content_hash,
                    "core_install_state": (
                        "current" if resolution.status == "resolved" else resolution.status
                    ),
                    "realm_sync": realm_sync,
                    "shared_catalog": shared is not None,
                    "publishable": publishable,
                    "publishable_reason": publishable_reason,
                    "compatibility": compatibility,
                }
            )
    if not rows:
        for name, item in accessible_by_name.items():
            rows.append(
                {
                    "name": name,
                    "kind": "skill",
                    "status": safe_assignment_token(item.get("status")) or "accessible",
                    "hash_tracked": bool(item.get("hash_tracked")),
                    "source": safe_assignment_token(item.get("source")) or "accessible_skills",
                    "category": "skills",
                    "description": "",
                    "loadable": True,
                }
            )
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("name", "")).lower()):
        name = safe_assignment_token(row.get("name"))
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return deduped


def _skill_publishability(source_kind: str | None) -> tuple[bool, str]:
    """``(publishable, typed_reason)`` for one resolved skill's source root.

    Delegates the vocabulary to :mod:`agent_runtime.skill_publishability` so
    this row and the ``skills_inventory/v1`` rows can never disagree about what
    "publishable" means. An UNRESOLVED skill (no candidate) is reported as
    not publishable with an explicit ``unresolved`` reason rather than being
    silently defaulted either way.
    """

    from ..skill_publishability import (
        REASON_EXTERNAL_DIR_ONLY,
        REASON_PROFILE_LOCAL_ONLY,
        REASON_SHARED_ROOT,
        REASON_UNKNOWN_ROOT,
    )

    if source_kind is None:
        return False, "unresolved"
    return (
        source_kind == "shared_core",
        {
            "shared_core": REASON_SHARED_ROOT,
            "profile_local": REASON_PROFILE_LOCAL_ONLY,
            "external": REASON_EXTERNAL_DIR_ONLY,
        }.get(source_kind, REASON_UNKNOWN_ROOT),
    )


def _skill_realm_sync(
    skill_name: str, realms: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for realm in realms:
        mode = str(realm.get("skill_publish_mode") or "all")
        selection = {str(item) for item in realm.get("skill_selection") or []}
        published = mode == "all" or skill_name in selection
        state = str(realm.get("sync_state") or "")
        drift = {str(item) for item in realm.get("skills_drift") or []}
        if not published:
            status = "not_published"
        elif not state:
            status = "unknown"
        elif skill_name in drift:
            status = "drifted"
        elif state == "in_sync":
            status = "in_sync"
        else:
            status = "unknown"
        rows.append(
            {
                "realm_id": safe_assignment_token(realm.get("realm_id")),
                "name": safe_assignment_text(realm.get("name"), limit=120),
                "status": status,
            }
        )
    return rows


def used_skills_context(
    *,
    final_model_input: dict[str, Any] | None = None,
    trace_events: Iterable[dict[str, Any]] | None = None,
    queued_skills: Iterable[str] | None = None,
    required_preload_skills: Iterable[str] | None = None,
    root_registries: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Redaction-safe list of skills actually loaded/read during this turn.

    ``root_registries`` is chat-turn-prep CP-5's shared walk. Every row below
    resolves ONE name, and resolving a name walks every skill root, so without a
    shared map a turn naming a dozen used/queued skills pays a dozen full walks
    — inside the span the CP-9 read measured at 157–547 ms. Passing the turn's
    map makes them all read the snapshot the preload lane already took. Optional
    and defaulted, so the two out-of-turn callers (the persisted record and the
    snapshot item) keep their present behaviour exactly.
    """
    names: list[str] = []
    for entry in _list_used_skill_entries(final_model_input):
        _append_used_skill_name(names, _extract_skill_name(entry))
    for entry in trace_events or ():
        if not isinstance(entry, dict):
            continue
        tool_name = safe_assignment_token(entry.get("tool_name") or entry.get("tool")).lower()
        if tool_name != "skill_view":
            continue
        if not _skill_trace_event_counts_as_used(entry):
            continue
        _append_used_skill_name(names, _extract_skill_name(entry))
    required = {
        token
        for item in required_preload_skills or ()
        if (token := safe_assignment_token(item))
    }
    rows = [
        {
            "name": name,
            "kind": "skill",
            "status": "used",
            "source": "skill_view_trace",
            **_resolved_skill_receipt(name, root_registries=root_registries),
        }
        for name in names
    ]
    for skill in queued_skills or ():
        token = safe_assignment_token(skill)
        if not token or token in names:
            continue
        rows.append(
            {
                "name": token,
                "kind": "skill",
                "status": "used",
                "source": (
                    "required_preload"
                    if token in required
                    else "queued_next_turn_skill"
                ),
                **_resolved_skill_receipt(token, root_registries=root_registries),
            }
        )
    return rows


def _resolved_skill_receipt(
    name: str, *, root_registries: dict[str, Any] | None = None
) -> dict[str, Any]:
    from agent_runtime.skill_resolution import resolve_skill, skill_package_content_hash

    # CP-5: one shared registry snapshot per root per turn, not one per NAME.
    resolution = resolve_skill(name, _root_registries=root_registries)
    selected = resolution.candidate
    content_hash = (
        skill_package_content_hash(selected.skill_dir, selected.skill_md)
        if selected
        else None
    )
    return {
        "resolution_status": resolution.status,
        "source_kind": selected.source_kind if selected else None,
        "content_hash": content_hash,
        "hash_tracked": content_hash is not None,
        # SIZE, beside the hash, because the hash answers "which bytes" and this
        # answers "how many". A ``required_preload`` row on this list means the
        # whole of that ``SKILL.md`` was pasted into this turn, and until now the
        # turn record said which version rode along without ever saying what it
        # cost. Additive and cheap: the path is already resolved above, so this
        # is one ``stat`` on a file the hash just read. ``None`` when the skill
        # did not resolve, matching ``content_hash`` rather than inventing a 0.
        "skill_md_bytes": _skill_md_bytes(selected),
    }


def _skill_md_bytes(candidate: Any | None) -> int | None:
    """Bytes of the resolved ``SKILL.md`` — the preload's per-turn cost."""

    if candidate is None:
        return None
    try:
        return int(Path(candidate.skill_md).stat().st_size)
    except (OSError, TypeError, ValueError):
        return None


def _list_used_skill_entries(final_model_input: dict[str, Any] | None) -> list[Any]:
    if not isinstance(final_model_input, dict):
        return []
    entries = final_model_input.get("used_skills")
    if isinstance(entries, list):
        return entries
    trace = final_model_input.get("skill_trace")
    if isinstance(trace, list):
        return trace
    return []


def _skill_trace_event_counts_as_used(entry: dict[str, Any]) -> bool:
    status = safe_assignment_token(entry.get("status")).lower()
    if status in {"failed", "error", "errored", "blocked"}:
        return False
    step = safe_assignment_token(entry.get("step")).lower()
    if step and step not in {"tool_finished", "completed", "finished"}:
        return False
    return True


def _append_used_skill_name(names: list[str], value: str | None) -> None:
    token = safe_assignment_token(value)
    if token and token not in names:
        names.append(token)


def _extract_skill_name(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return None
    for key in ("skill_name", "skill", "identifier", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("input", "invocation", "tool_input", "result", "metadata"):
        nested = entry.get(key)
        if isinstance(nested, dict):
            name = _extract_skill_name(nested)
            if name:
                return name
    command = entry.get("command_label")
    if isinstance(command, str):
        lowered = command.strip()
        for prefix in ("skill_view ", "skills view "):
            if lowered.lower().startswith(prefix):
                return lowered[len(prefix) :].strip().split()[0]
    return None


def _chat_metadata(
    *,
    session_db: Any | None,
    session_id: str | None,
    task_id: str | None = None,
) -> dict[str, Any]:
    safe_id = safe_assignment_text(session_id, limit=200)
    if not safe_id:
        return {}
    title = None
    source = None
    if session_db is not None:
        try:
            title = safe_assignment_text(session_db.get_session_title(safe_id), limit=160)
        except Exception:
            title = None
        try:
            raw = session_db.get_session(safe_id)
        except Exception:
            raw = None
        if isinstance(raw, dict):
            if not title:
                title = safe_assignment_text(raw.get("title"), limit=160)
            source = safe_assignment_token(raw.get("source"))
    if not title and safe_assignment_text(task_id, limit=160):
        title = "Mission run"
        source = source or "task_bound"
    data: dict[str, Any] = {
        "id": safe_id,
        "title": title,
        "name": title,
    }
    if source:
        data["source"] = source
    return data
