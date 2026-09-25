"""The content-addressed skills-catalog store the hoisted refs resolve against.

Separate because it is its own directory on disk with its own read verb
(``skills_catalog_by_hash``) the harness CLI calls.
"""

from __future__ import annotations

import json
from typing import Any

from utils import atomic_json_write

from .. import paths
from ..persona_assignments import safe_assignment_token
from ..serde import to_jsonable
from .hoist import _skills_list_content_hash

__layer__ = "stores"
__all__ = [
    "load_skills_catalog_from_store",
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
