"""The versioned JSON document reader: a store file read as ``{schema_version, <collection>: {}}``.

D1.08. Two machine-local stores (``workspace_slot_env``, ``workspace_slot_runs``)
read their file the same way and must answer the same on a fault: a missing,
unreadable or corrupt file, a payload that is not an object, or a collection that
is not an object all read as the EMPTY document of the current schema — never a
raise, never the malformed payload handed on to a writer that would persist it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__layer__ = "models"

__all__ = ["read_versioned_document"]


def read_versioned_document(path: Path, *, schema_version: int, collection: str) -> dict[str, Any]:
    """The document at ``path``, or ``{"schema_version": schema_version, collection: {}}`` on any fault."""

    empty: dict[str, Any] = {"schema_version": schema_version, collection: {}}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(payload, dict) or not isinstance(payload.get(collection), dict):
        return empty
    return payload
