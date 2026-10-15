"""The content-addressed skills-catalog store the hoisted refs resolve against,
and the two verbs that span it and the persisted rows:
``persist_prompt_observability_context`` (a row persisted with its catalogs) and
``skills_catalog_by_hash`` (a hoisted ref resolved from the catalog store, else
from the live rows).

One module for the one concept: ``context_store`` takes the catalog writer by
injection, so this module reads that store's rows without an import cycle.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from utils import atomic_json_write

from .. import paths
from ..persona_assignments import safe_assignment_token
from ..serde import to_jsonable
from .context_store import load_latest_prompt_observability_contexts, persist_context_row
from .hoist import HOISTED_SKILL_LIST_FIELDS, _skills_list_content_hash

__layer__ = "stores"
__all__ = [
    "load_skills_catalog_from_store",
    "persist_prompt_observability_context",
    "skills_catalog_by_hash",
    "_store_skills_catalog",
]


def load_skills_catalog_from_store(content_hash: str) -> list[dict[str, Any]] | None:
    """O(1) read of one catalog from the content-addressed store.

    Integrity-checked: the loaded list must hash back to its own address — a
    corrupt or tampered store file is a typed miss (never fake content), and
    the caller's legacy fallback walk still gets its chance."""

    token = safe_assignment_token(content_hash)
    if not token:
        return None
    path = paths.prompt_observability_catalogs_dir() / f"{token}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    if _skills_list_content_hash(data) != token:
        return None
    return data


def _store_skills_catalog(ref: str, rows: list) -> None:
    """Write one content-addressed catalog iff absent (a content hash is
    immutable, so an existing file is already the right bytes). Compact."""

    path = paths.prompt_observability_catalogs_dir() / f"{ref}.json"
    if path.exists():
        return
    atomic_json_write(
        path,
        to_jsonable(rows),
        indent=None,
        sort_keys=True,
        separators=(",", ":"),
    )


def persist_prompt_observability_context(context: dict[str, Any]) -> None:
    """Persist one observability row, its hoisted skill lists landing in the
    catalog store first (``context_store.persist_context_row`` is the one
    writer; this binds the catalog writer it takes by injection)."""

    persist_context_row(context, store_catalog=_store_skills_catalog)


def skills_catalog_by_hash(
    content_hash: str,
    *,
    materialize: Callable[..., Any] | None = None,
) -> list[dict[str, Any]] | None:
    """On-demand resolve of one content-addressed skills catalog by its hash.

    S8 evicted the ``skills_catalogs`` table from the frame; rows keep only
    ``*_ref`` hashes. C1 (2026-07-17) made the resolve O(1): the catalog bodies
    are stored ONCE, content-addressed, in the persist-time catalog store
    (``prompt_observability_catalogs/<hash>.json``) and read back directly. The
    pre-C1 walk over the newest persisted rows remains as the LEGACY-ROW
    fallback — rows persisted before the store existed still carry inline lists
    (archive-never-delete means they exist) and still resolve. A configured
    agent can have a freshly projected prompt context before its first persisted
    chat row; on that final miss the explicit detail fetch rebuilds the live
    projection once and materializes its immutable catalog bodies. Ordinary
    snapshot reads remain write-free. Returns ``None`` on an honest miss (the
    launcher renders a pending state and retries next frame), never a fake empty
    catalog.

    ``materialize`` is that live-projection builder (``snapshot.build_snapshot``,
    passed by the detail verb). It is a PARAMETER, not an import: this store
    module sits below the snapshot lane that imports it, and a lookup with no
    builder simply has no final rebuild step."""

    token = str(content_hash or "").strip()
    if not token:
        return None
    stored = load_skills_catalog_from_store(token)
    if stored is not None:
        return stored
    for row in load_latest_prompt_observability_contexts():
        if not isinstance(row, dict):
            continue
        for field in HOISTED_SKILL_LIST_FIELDS:
            value = row.get(field)
            if isinstance(value, list) and _skills_list_content_hash(value) == token:
                return value
    if materialize is None:
        return None
    live_catalogs = _materialize_live_skills_catalogs(materialize)
    value = live_catalogs.get(token)
    return value if isinstance(value, list) else None


def _materialize_live_skills_catalogs(build_snapshot: Callable[..., Any]) -> dict[str, list[dict[str, Any]]]:
    """Capture and cache the current live projection's immutable catalogs.

    This runs only behind the explicit on-demand detail verb after the O(1)
    store and legacy-row reads miss.  Capturing through ``build_snapshot``
    guarantees that every body is byte-identical to the hash the live frame
    advertised; caching all captured bodies makes a second hash from the same
    dialog an immediate store hit.
    """

    catalogs: dict[str, list[dict[str, Any]]] = {}
    try:
        build_snapshot(prompt_skills_catalogs=catalogs)
    except Exception:
        return {}
    verified: dict[str, list[dict[str, Any]]] = {}
    for ref, rows in catalogs.items():
        if isinstance(rows, list) and _skills_list_content_hash(rows) == ref:
            _store_skills_catalog(ref, rows)
            verified[ref] = rows
    return verified
