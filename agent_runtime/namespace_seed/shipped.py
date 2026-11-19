"""The seed's shipped agents: resolved from the build, never copied (row RT-NAMESPACE-SEED-SKIPS-SHIPPED-AGENTS).

Design § 3 "Realms and namespaces" (owner 2026-11-19): a namespace made from another one does not
get a second copy of a shipped agent (Base Agent, Neko Mission Lead). A source record that
REFERENCES one (``origin: "eternia"`` under a shipped id, ``agent_runtime.bundled_agents``) is not
copied; the seed writes this build's own reference in its place, carrying only the source's
install settings (model, provider, budgets) — the definition and SOUL come from the build, so a
changed or stale copy of the definition never travels into the new namespace. The seats placed in
the copied office keep resolving: their persona id is the reference's id.

A source record under a shipped id that is NOT a reference (an install not yet sorted by
``hermes harness persona sort-shipped``) is the user's own and is copied as today.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utils import atomic_json_write

from ..bundled_agents import reference_record, shipped_reference
from ..models import AgentPersona
from ..serde import from_jsonable, to_jsonable

__layer__ = "lanes"

__all__ = ["AGENTS_DIRNAME", "RESOLVED_FROM_BUILD", "ShippedRecord", "read_shipped", "write_references"]

AGENTS_DIRNAME = "agents"
RESOLVED_FROM_BUILD = "resolved from the build"


@dataclass(frozen=True, slots=True)
class ShippedRecord:
    """One shipped agent the seed resolves from the build: where it is written and what."""

    label: str
    destination: Path
    reference: AgentPersona

    def payload(self) -> dict[str, Any]:
        return {"path": self.label, "id": self.reference.id, "name": self.reference.display_name,
                "version": self.reference.bundled_version, "reason": RESOLVED_FROM_BUILD}


def read_shipped(source: Path, destination: Path, label: str) -> ShippedRecord | None:
    """The build's reference for the shipped agent ``source`` references, or ``None`` for any other record."""

    if source.is_symlink() or not source.is_file() or source.suffix != ".json":
        return None
    try:
        record = from_jsonable(AgentPersona, json.loads(source.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError):
        return None
    shipped = shipped_reference(record)
    if shipped is None:
        return None
    # The build's definition over the source's install settings; a local edit stays behind.
    return ShippedRecord(label, destination, reference_record(shipped, settings=record))


def write_references(records: tuple[ShippedRecord, ...]) -> None:
    for record in records:
        record.destination.parent.mkdir(parents=True, exist_ok=True)
        atomic_json_write(record.destination, to_jsonable(record.reference), indent=2, sort_keys=True)
