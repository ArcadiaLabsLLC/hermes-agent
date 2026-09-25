"""The persisted per-lane observability rows, their index and retention.

Separate because it owns one store: ``persist_prompt_observability_context`` is
the only writer of the per-lane index (program rule 13).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from .. import paths
from ..persona_assignments import safe_assignment_text, safe_assignment_token
from ..serde import to_jsonable
from .catalog_store import _store_skills_catalog
from .context_budget import (
    _context_budget,
    _context_budget_needs_refresh,
    _profile_prompt_skills_need_snapshot,
    _profile_snapshot_skill_names,
)
from .hoist import _skills_list_content_hash
from .skills_context import _chat_metadata, available_skills_context, used_skills_context
from .spans import PROMPT_OBSERVABILITY_TIMINGS_KEY

__layer__ = "stores"
__all__ = [
    "PROMPT_OBSERVABILITY_RETAIN_PER_LANE",
    "persist_prompt_observability_context",
    "load_live_prompt_observability_contexts",
    "load_persisted_context_row",
    "load_latest_prompt_observability_contexts",
    "_context_row_key",
    "_filter_live_chat_contexts",
    "_merge_latest_contexts",
]


# --------------------------------------------------------------------------- #
# C1/C2 record-once store (2026-07-17, console-chat plan stages C1+C2).
#
# C1 — the persisted per-turn RECORD carries one copy of each fact: the two
# byte-identical alias key-pairs (57.8% of every pre-C1 file) are gone from the
# built row, and the two canonical skill lists leave the row as content-hash
# refs into a persist-time catalog store. ``final_model_input`` STAYS in the
# row, compact (operator ruling 2026-07-17 §7.2). Writes are compact JSON.
#
# C2 — the live dir is bounded and reads are roster-keyed: the persist
# chokepoint (ONE owner) maintains a latest-pointer index mapping
# (persona_instance_id, session_id) -> newest context ids and enforces per-lane
# retention (newest K live; older rows MOVE to the archive dir —
# archive-never-delete, accounted via ``archived_count``). The frame build
# resolves the live roster's lanes through the index and reads exactly those
# rows; an absent/corrupt index or a dangling pointer falls back to the legacy
# glob path with typed accounting. The READ path never writes — the heal
# happens at the next persist (emit-path projections are READ-ONLY).
# --------------------------------------------------------------------------- #

#: C2 retention: newest K rows per (persona_instance_id, session_id) lane stay
#: live; older rows move to ``prompt_observability_archive/``.
PROMPT_OBSERVABILITY_RETAIN_PER_LANE = 2


#: C1 persisted-row shape: (canonical inline field, legacy alias field,
#: persisted ref field). The alias is normalized into the canonical value when
#: a legacy-shaped input carries only the alias — data is never dropped.
_PERSIST_REF_FIELDS = (
    ("available_skills", "skills_catalog", "available_skills_ref"),
    ("accessible_skills", "skills", "accessible_skills_ref"),
)


def persist_prompt_observability_context(context: dict[str, Any]) -> None:
    """THE persist chokepoint (one owner): ref-transform, compact write,
    latest-pointer index, and retention happen here and nowhere else.

    The caller's dict is NEVER mutated — the live ``chat.final`` wire echo
    still carries the built row with its inline canonical lists (slimming that
    echo is stage C3's lane, not this one)."""

    context_id = safe_assignment_token(context.get("context_id"))
    if not context_id:
        return
    # Deep JSON copy (to_jsonable rebuilds every dict/list) — mutations below
    # cannot touch the caller's object.
    row = to_jsonable(context)
    # chat-turn-prep Stage 6 item 2: the builder's own sub-spans ride the built
    # object to the turn handler, which folds them onto the turn record's
    # ``profile_timing``. They are dropped HERE, at the one persist chokepoint,
    # so no lane can leak a second unversioned copy of a timing the ledger
    # already carries onto an operator-facing context row — including the
    # snapshot lane, which builds rows through the same function with no handler
    # in between.
    row.pop(PROMPT_OBSERVABILITY_TIMINGS_KEY, None)
    for canonical_field, alias_field, ref_field in _PERSIST_REF_FIELDS:
        value = row.pop(canonical_field, None)
        alias = row.pop(alias_field, None)
        if not isinstance(value, list):
            value = alias if isinstance(alias, list) else None
        if value is None:
            # No list, no ref — an absent catalog is honest absence, never a
            # fake empty one. A re-persisted ref-shaped row keeps its refs.
            continue
        ref = _skills_list_content_hash(value)
        _store_skills_catalog(ref, value)
        row[ref_field] = ref
    root = paths.prompt_observability_dir()
    root.mkdir(parents=True, exist_ok=True)
    atomic_json_write(
        root / f"{context_id}.json",
        row,
        indent=None,
        sort_keys=True,
        separators=(",", ":"),
    )
    _index_and_retain_after_persist(row, context_id=context_id)


def _lane_key_for_row(row: dict[str, Any]) -> tuple[str, str]:
    """The (instance, session) retention/index lane a persisted row belongs to."""

    return (
        safe_assignment_token(row.get("persona_instance_id")) or "",
        safe_assignment_text(row.get("session_id"), limit=200) or "",
    )


def _load_prompt_observability_index() -> dict[str, Any] | None:
    """The latest-pointer index, or ``None`` when absent/corrupt.

    ``None`` is the typed fallback signal: readers glob instead, and the next
    persist rebuilds the index (its one owner). Never raises."""

    path = paths.prompt_observability_index_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return None
    return data


def _archived_context_count() -> int:
    archive = paths.prompt_observability_archive_dir()
    if not archive.exists():
        return 0
    return sum(1 for _ in archive.glob("*.json"))


def _rebuild_prompt_observability_index() -> dict[str, Any]:
    """Full index rebuild from the live dir (the heal path; persist-time only).

    Parses every live row once — the one-time O(dir) cost that makes every
    subsequent frame read roster-sized — orders each lane newest-first by file
    mtime, and recounts the archive. Unreadable/mis-named files are counted
    (typed, never silent) and left alone: nothing here deletes."""

    root = paths.prompt_observability_dir()
    unreadable = 0
    files: list[tuple[float, str, dict[str, Any]]] = []
    if root.exists():
        for path in root.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                unreadable += 1
                continue
            context_id = safe_assignment_token(data.get("context_id")) if isinstance(data, dict) else None
            if not context_id or path.name != f"{context_id}.json":
                unreadable += 1
                continue
            files.append((mtime, context_id, data))
    lanes: dict[tuple[str, str], dict[str, Any]] = {}
    for _mtime, context_id, data in sorted(files, key=lambda item: item[0], reverse=True):
        key = _lane_key_for_row(data)
        entry = lanes.setdefault(
            key,
            {
                "instance_id": key[0],
                "session_id": key[1],
                "persona_id": safe_assignment_token(data.get("persona_id")) or "",
                "context_ids": [],
            },
        )
        entry["context_ids"].append(context_id)
    return {
        "schema_version": 1,
        "archived_count": _archived_context_count(),
        "unreadable_count": unreadable,
        "entries": list(lanes.values()),
    }


def _index_and_retain_after_persist(row: dict[str, Any], *, context_id: str) -> None:
    """Update the latest-pointer index for this persist and enforce retention.

    One owner: only this persist-time hook moves rows out of the live dir or
    writes the index. An absent/corrupt index is healed here by a full rebuild
    (which also folds in any pre-index legacy rows, so the first persist after
    landing performs the one-time bounded-store sweep)."""

    index = _load_prompt_observability_index()
    if index is None:
        index = _rebuild_prompt_observability_index()
    entries = [entry for entry in index.get("entries", []) if isinstance(entry, dict)]
    key = _lane_key_for_row(row)
    entry = next(
        (
            candidate
            for candidate in entries
            if (
                str(candidate.get("instance_id") or ""),
                str(candidate.get("session_id") or ""),
            )
            == key
        ),
        None,
    )
    if entry is None:
        entry = {
            "instance_id": key[0],
            "session_id": key[1],
            "persona_id": "",
            "context_ids": [],
        }
        entries.append(entry)
    known = [str(item) for item in entry.get("context_ids", []) if str(item or "").strip()]
    entry["context_ids"] = [context_id] + [item for item in known if item != context_id]
    entry["persona_id"] = (
        safe_assignment_token(row.get("persona_id")) or str(entry.get("persona_id") or "")
    )
    archived = int(index.get("archived_count") or 0)
    root = paths.prompt_observability_dir()
    archive_dir = paths.prompt_observability_archive_dir()
    for candidate in entries:
        ids = [str(item) for item in candidate.get("context_ids", []) if str(item or "").strip()]
        keep = ids[:PROMPT_OBSERVABILITY_RETAIN_PER_LANE]
        for stale_id in ids[PROMPT_OBSERVABILITY_RETAIN_PER_LANE:]:
            source = root / f"{stale_id}.json"
            try:
                if source.exists():
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    os.replace(source, archive_dir / f"{stale_id}.json")
                    archived += 1
            except OSError:
                # The move failed — keep the row indexed AND live rather than
                # losing track of it. Retention retries on the next persist.
                keep.append(stale_id)
        # Dangling-pointer heal: a kept id whose live file vanished outside the
        # chokepoint (sabotage/manual deletion) is dropped here — the READ path
        # reported the typed miss and fell back; THIS is where the index heals
        # (its one owner). An id that was legitimately archived is not "kept".
        candidate["context_ids"] = [
            item for item in keep if (root / f"{item}.json").exists()
        ]
    # A lane with no live rows left has nothing to point at — prune the entry
    # (its archived rows remain fetchable by id; the index only maps LIVE rows).
    index["entries"] = [entry for entry in entries if entry.get("context_ids")]
    index["archived_count"] = archived
    atomic_json_write(
        paths.prompt_observability_index_path(),
        index,
        indent=None,
        sort_keys=True,
        separators=(",", ":"),
    )


def load_live_prompt_observability_contexts(
    *,
    built_keys: set[tuple[str, str, str]],
    live_instance_ids: set[str],
    live_session_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Roster-keyed frame read (C2): read EXACTLY the live lanes' newest rows.

    Resolves the live roster's (instance, session) lanes through the
    latest-pointer index and reads one file per live lane, instead of the
    legacy glob+stat+parse of the newest 50 files (4.51 MB measured) on every
    full core. The index is a cache, never authority: an absent/corrupt index
    or a pointer at a missing/corrupt file degrades to the legacy glob path
    with typed accounting in the returned receipt — and this READ path never
    writes (the heal happens at the next persist, the index's one owner).

    Returns ``(rows, receipt)`` — rows newest-first (the legacy ordering
    contract), receipt = {source, index_status, files_read, index_misses,
    stale_lanes, archived_count}."""

    receipt: dict[str, Any] = {
        "source": "index",
        "index_status": "hit",
        "files_read": 0,
        "index_misses": 0,
        "stale_lanes": 0,
        "archived_count": 0,
    }
    index = _load_prompt_observability_index()
    if index is None:
        receipt["source"] = "glob_fallback"
        receipt["index_status"] = "absent_or_corrupt"
        rows = load_latest_prompt_observability_contexts()
        receipt["files_read"] = len(rows)
        receipt["archived_count"] = _archived_context_count()
        return rows, receipt
    receipt["archived_count"] = int(index.get("archived_count") or 0)
    root = paths.prompt_observability_dir()
    targets: list[Path] = []
    for entry in index.get("entries", []):
        if not isinstance(entry, dict):
            continue
        instance_id = safe_assignment_token(entry.get("instance_id")) or ""
        session_id = safe_assignment_text(entry.get("session_id"), limit=200) or ""
        persona_id = safe_assignment_token(entry.get("persona_id")) or ""
        is_live = _context_identity_is_live(
            key=(instance_id, session_id, persona_id),
            built_keys=built_keys,
            live_instance_ids=live_instance_ids,
            live_session_ids=live_session_ids,
        )
        if not is_live:
            # Counted, never silently skipped: these lanes' rows stay on disk
            # and feed the frame's ``chat_contexts_ref`` eviction accounting.
            receipt["stale_lanes"] += 1
            continue
        newest = next(
            (
                token
                for token in (
                    safe_assignment_token(item) for item in entry.get("context_ids", [])
                )
                if token
            ),
            None,
        )
        if newest:
            targets.append(root / f"{newest}.json")
    loaded: list[tuple[float, str, dict[str, Any]]] = []
    for path in targets:
        try:
            mtime = path.stat().st_mtime
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            receipt["index_misses"] += 1
            continue
        receipt["files_read"] += 1
        if isinstance(data, dict) and safe_assignment_token(data.get("context_id")):
            loaded.append((mtime, path.name, data))
    if receipt["index_misses"]:
        # A pointer aimed at a deleted/corrupt file: typed miss, and the frame
        # still gets CORRECT output via the legacy glob. Heal at next persist.
        receipt["source"] = "glob_fallback"
        receipt["index_status"] = "miss"
        receipt["stale_lanes"] = 0
        rows = load_latest_prompt_observability_contexts()
        receipt["files_read"] += len(rows)
        return rows, receipt
    # Newest-first with the file name as a stable tiebreak — the same recency
    # order the legacy glob path produced, so the frame section stays
    # deterministic across both read modes.
    loaded.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in loaded], receipt


def load_persisted_context_row(context_id: str) -> dict[str, Any] | None:
    """One persisted observability row by id — live dir first, then the C2
    archive. Archive-never-delete means retention MOVES rows; the fetch lane
    (``harness prompt-context show``) must keep resolving them. Honest ``None``
    on absence/corruption, never a fabricated row."""

    token = safe_assignment_token(context_id)
    if not token:
        return None
    for root in (paths.prompt_observability_dir(), paths.prompt_observability_archive_dir()):
        path = root / f"{token}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None


def load_latest_prompt_observability_contexts() -> list[dict[str, Any]]:
    root = paths.prompt_observability_dir()
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            import json

            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict) and safe_assignment_token(data.get("context_id")):
            rows.append(data)
        if len(rows) >= 50:
            break
    return rows


def _context_row_key(item: dict[str, Any]) -> tuple[str, str, str]:
    """The (instance, session, persona) identity a chat-context row folds on."""

    return (
        safe_assignment_token(item.get("persona_instance_id")) or "",
        safe_assignment_text(item.get("session_id"), limit=200) or "",
        safe_assignment_token(item.get("persona_id")) or "",
    )


def _filter_live_chat_contexts(
    chat_contexts: list[dict[str, Any]],
    *,
    built_keys: set[tuple[str, str, str]],
    live_instance_ids: set[str],
    live_session_ids: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """Keep only chat-context rows tied to a LIVE persona instance's current
    session (S8); return ``(kept, evicted_count)``.

    A row is live when it was freshly BUILT this frame for a roster instance
    (``built_keys``) OR its persona_instance_id / session_id resolves to a live
    instance. Purely-historical/stale rows (a departed instance, a closed
    session) are evicted from the frame — their persisted files stay on disk and
    the Context peek, which only ever selects a LIVE roster agent, never requests
    them (so the eviction is honest, never a fake-empty)."""

    kept: list[dict[str, Any]] = []
    evicted = 0
    for row in chat_contexts:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        key = _context_row_key(row)
        inst_id = safe_assignment_token(row.get("persona_instance_id"))
        sess_id = safe_assignment_text(row.get("session_id"), limit=200)
        is_live = _context_identity_is_live(
            key=key,
            built_keys=built_keys,
            live_instance_ids=live_instance_ids,
            live_session_ids=live_session_ids,
        )
        if is_live:
            kept.append(row)
        else:
            evicted += 1
    return kept, evicted


def _context_identity_is_live(
    *,
    key: tuple[str, str, str],
    built_keys: set[tuple[str, str, str]],
    live_instance_ids: set[str],
    live_session_ids: set[str],
) -> bool:
    """Resolve a persisted context against the current-session roster.

    A long-lived persona instance can accumulate many historical sessions.
    Instance identity alone therefore cannot make a row live: freshly built
    keys are the authority for that instance's current session. Session-only
    legacy rows remain supported when their session is current.
    """

    if key in built_keys:
        return True
    instance_id, session_id, _persona_id = key
    if instance_id:
        current_sessions = {
            built_session
            for built_instance, built_session, _ in built_keys
            if built_instance == instance_id
        }
        if current_sessions:
            return session_id in current_sessions
        return instance_id in live_instance_ids and not session_id
    return bool(session_id and session_id in live_session_ids)


def _merge_latest_contexts(
    contexts: list[dict[str, Any]],
    *,
    session_db: Any | None = None,
    disk_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge persisted rows (newest-first) over the freshly built contexts.

    ``disk_rows`` lets the C2 roster-keyed loader supply exactly the live
    lanes' rows; when omitted (legacy callers/tests) the newest-50 glob load
    is used."""

    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    key_for = _context_row_key

    built_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in contexts:
        built_by_key.setdefault(key_for(item), item)

    if disk_rows is None:
        disk_rows = load_latest_prompt_observability_contexts()
    for item in disk_rows:
        key = key_for(item)
        if key in seen:
            continue
        _backfill_derived_fields(item, built_by_key.get(key), session_db=session_db)
        merged.append(item)
        seen.add(key)
    for item in contexts:
        key = key_for(item)
        if key in seen:
            continue
        merged.append(item)
        seen.add(key)
    return merged


def _backfill_derived_fields(
    item: dict[str, Any],
    built: dict[str, Any] | None,
    *,
    session_db: Any | None = None,
) -> None:
    """Repair persisted contexts that predate the current row shape.

    Persisted observability rows are written at chat time, so rows captured
    before newer fields existed lack them. Backfill skills from the freshly
    built context (correct per-persona set) or the profile snapshot, and
    recompute the budget from the row's own model selection + final input.

    C1 shape rules: the alias keys (``skills`` ≡ accessible, ``skills_catalog``
    ≡ available) are READ from legacy rows for normalization but never written
    back — one copy of each fact. A row carrying ``accessible_skills_ref`` /
    ``available_skills_ref`` was persisted by the C1 chokepoint and is correct
    by construction: its skills are present BY REF, so the legacy re-inflation
    paths must not fabricate inline lists over them.
    """
    if built:
        # Same rationale for the runtime situational HUD: persisted chat rows
        # never compute one, so prefer the freshly built projection.
        built_situational = built.get("situational_hud")
        if isinstance(built_situational, dict) and built_situational and not item.get("situational_hud"):
            item["situational_hud"] = built_situational
        for key in (
            "used_skills",
            "accessible_skills",
            "available_skills",
            "chat_id",
            "chat_title",
            "chat_name",
            "chat",
        ):
            value = built.get(key)
            if value is not None and value != []:
                item[key] = value
    if not item.get("chat_id") or not item.get("chat_title"):
        chat = _chat_metadata(
            session_db=session_db,
            session_id=safe_assignment_text(item.get("session_id"), limit=200),
            task_id=safe_assignment_text(item.get("task_id"), limit=160),
        )
        if chat:
            item["chat_id"] = chat.get("id")
            item["chat_title"] = chat.get("title")
            item["chat_name"] = chat.get("name")
            item["chat"] = chat
    # Legacy alias normalization (READ then retire): rows persisted before C1
    # may carry only the alias keys. Fold them into the canonical fields and
    # drop them — the frame carries one copy of each fact.
    if not item.get("accessible_skills") and item.get("skills"):
        item["accessible_skills"] = item.get("skills")
    if not item.get("available_skills") and item.get("skills_catalog"):
        item["available_skills"] = item.get("skills_catalog")
    item.pop("skills", None)
    item.pop("skills_catalog", None)
    if item.get("used_skills") is None:
        item["used_skills"] = used_skills_context(
            final_model_input=item.get("final_model_input")
        )
    # C1 ref-shaped rows carry their skills by content-hash ref — present, not
    # missing. Re-inflating them from the profile snapshot / installed catalog
    # would overwrite the recorded truth with a re-derivation.
    has_accessible_ref = bool(safe_assignment_token(item.get("accessible_skills_ref")))
    has_available_ref = bool(safe_assignment_token(item.get("available_skills_ref")))
    if not has_accessible_ref and (
        not item.get("accessible_skills") or _profile_prompt_skills_need_snapshot(item)
    ):
        profile = safe_assignment_token(item.get("profile"))
        names = _profile_snapshot_skill_names(profile) if profile else []
        if names:
            item["accessible_skills"] = [
                {
                    "name": safe_assignment_token(name) or name,
                    "kind": "skill",
                    "status": "loaded",
                    "hash_tracked": False,
                    "source": "profile_skills_snapshot",
                }
                for name in names[:80]
            ]
            item["available_skills"] = available_skills_context(
                accessible_skills=item["accessible_skills"]
            )
    if item.get("available_skills") is None and not has_available_ref:
        item["available_skills"] = available_skills_context(
            accessible_skills=item.get("accessible_skills") or []
        )
    if _context_budget_needs_refresh(item):
        budget = _context_budget(item.get("model_selection"), item.get("final_model_input"))
        if budget is not None:
            item["context_budget"] = budget
