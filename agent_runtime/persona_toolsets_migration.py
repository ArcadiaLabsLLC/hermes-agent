"""One-shot startup strip of the legacy persona-level ``toolsets`` key from ``<store>/agents/*.json``.

Ruling R2 of the tool-visibility split (``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md``
§6, applied 2026-10-08): ``AgentPersona.toolsets`` is deleted, the root-config key is
refused at load (``config.persona_records``), and the STORE rows — the live carrier of the
list (Neko's row held it; the root config did not) — are migrated once. A row that still
carries the key already loads without it (``serde.from_jsonable`` keeps only declared
fields); this rewrite makes the disk agree, so a realm publish, a backup or a hand read
of the row can no longer show a list that admits nothing.

Same shape as ``local_llama_adapter.legacy_id_migration``: the report is written to
``<store>/migrations/persona_toolsets_legacy_key.json`` and its presence makes the next
start a single stat. Every stripped row is logged at WARNING with the list it carried.
Fail-open: a row that cannot be read or written is reported, never raised.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils import atomic_json_write

__layer__ = "stores"

logger = logging.getLogger(__name__)

MARKER_NAME = "persona_toolsets_legacy_key.json"
LEGACY_KEY = "toolsets"


def marker_path(store_root: Path) -> Path:
    return store_root / "migrations" / MARKER_NAME


def migrate_legacy_persona_toolsets_once() -> dict[str, Any] | None:
    """Strip the key for the active store unless its marker says it already ran.

    Returns the report when it ran, ``None`` when the marker was already there."""

    from . import paths

    store_root = paths.store_root()
    if marker_path(store_root).exists():
        return None
    report = strip_legacy_persona_toolsets(store_root)
    if store_root.is_dir():  # never create a store for a home that has none
        marker = marker_path(store_root)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def strip_legacy_persona_toolsets(store_root: Path) -> dict[str, Any]:
    """Rewrite every ``agents/*.json`` row carrying ``toolsets`` without it."""

    stripped: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    agents = Path(store_root) / "agents"
    for path in sorted(agents.glob("*.json")) if agents.is_dir() else ():
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, dict) or LEGACY_KEY not in row:
                continue
            carried = row.pop(LEGACY_KEY)
            # The store's own writer shape (``store.base._write_model``).
            atomic_json_write(path, row, indent=2, sort_keys=True)
        except Exception as exc:
            errors.append({"path": str(path), "error": type(exc).__name__})
            logger.warning("persona_toolsets_strip_failed path=%s error=%s", path, type(exc).__name__)
            continue
        stripped.append({"path": str(path), "persona_id": str(row.get("id") or path.stem), "toolsets": carried})
        logger.warning("persona_toolsets_stripped path=%s persona=%s toolsets=%s", path, row.get("id"), carried)
    return {
        "schema": "hermes.agent_runtime.persona_toolsets_migration/v1",
        "ran_at": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "stripped": stripped,
        "errors": errors,
    }
