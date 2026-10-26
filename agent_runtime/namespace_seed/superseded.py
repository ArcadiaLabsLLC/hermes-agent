"""``SEEDED_INTO.json`` — a seed SOURCE tells a reader where its data went (row ``RT-BASE-ROOT-STALE-AFTER-SEED``).

Plan ``docs/agent-runtime-harness/planned/naming-and-address-map-2026-10-25.md`` ruling 1: the base root
holds an install only. After ``hermes namespace seed <acct> --from base`` the base root still holds full
copies of realms, workspaces, slots, persona records, ``state.db`` files and logs that nothing writes any
more, and they read as live (the 2026-10-25 Neko trial audit searched them first). So every seed records
itself in the SOURCE root: ``<source root>/SEEDED_INTO.json`` names each namespace seeded from it, when,
and what was copied. Nothing is moved or deleted: the marker only tells a reader the live data is elsewhere.

One entry per target namespace, merged by id, so writing it twice is a no-op (idempotent). A namespace
seeded before this marker existed gets its entry from ``hermes namespace list`` (:func:`backfill`), which
already reads every manifest's ``seeded_from``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

__layer__ = "lanes"

MARKER_NAME = "SEEDED_INTO.json"
MARKER_SCHEMA = 1
NOTE = ("This root's data stores were copied into the namespaces below and are no longer written here; "
        "read the namespace, not this root. Install code (venvs, bin, installs) stays live.")


def marker_path(source_root: Path) -> Path:
    return Path(source_root) / MARKER_NAME


def read_marker(source_root: Path) -> dict[str, Any] | None:
    try:
        record = json.loads(marker_path(source_root).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) and isinstance(record.get("seeded_into"), list) else None


def record_seed(source_root: Path, *, namespace: str, namespaces_dir: Path, seeded_at: str,
                copied: Iterable[str] = ()) -> bool:
    """Add (or keep) *namespace*'s entry in the source's marker. True when the file changed."""

    record = read_marker(source_root) or {"schema": MARKER_SCHEMA, "note": NOTE, "seeded_into": []}
    entries = [row for row in record["seeded_into"] if isinstance(row, dict)]
    if any(row.get("namespace") == namespace for row in entries):
        return False
    tops = sorted({str(rel).replace("\\", "/").split("/", 1)[0] for rel in copied if str(rel)})
    entries.append({"namespace": namespace, "root": str(Path(namespaces_dir) / namespace), "seeded_at": seeded_at,
                    "copied_top_level": tops})
    out = {**record, "schema": MARKER_SCHEMA, "note": NOTE,
           "seeded_into": sorted(entries, key=lambda row: str(row.get("namespace")))}
    target = marker_path(source_root)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)
    return True


def backfill(source_root: Path, namespaces_dir: Path, rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Record every listed namespace whose manifest says ``seeded_from: base``; the ids newly recorded."""

    added = []
    for row in rows:
        manifest = row.get("manifest") or {}
        if manifest.get("seeded_from") != "base":
            continue
        try:
            changed = record_seed(source_root, namespace=str(row["id"]), namespaces_dir=namespaces_dir,
                                  seeded_at=str(manifest.get("seeded_at") or ""), copied=manifest.get("seeded") or ())
        except OSError:
            continue  # a read-only base root reports, it never fails the listing
        if changed:
            added.append(str(row["id"]))
    return added
