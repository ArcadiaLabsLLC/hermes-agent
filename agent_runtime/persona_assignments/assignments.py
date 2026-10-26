"""The persona-assignment STORE, retired — its residual rows archived once, with a report.

RT-FULL-PERSONAASSIGNMENTSTORE (ruled go 2026-10-25: the live namespace store's
residual census is 0; a stale base root still held 47 rows). The store's mint side
went at S70, its read side's consumers at AX2; what was kept was the operator's
settle path (``persona assignments``, ``persona instance close|archive``, the
chat-delete unbind), and those verbs are retired with it.

:func:`retire_persona_assignment_store` is the one door that touches the rows left
on disk: every ``persona_assignments/*.json`` MOVES, bytes intact, into
``persona_assignments_archive/retired_store/`` (archive, never delete), the empty
live directory is removed, and ``migrations/persona_assignment_store_retired.json``
records each row's id, persona, instance and state. Idempotent: a root with no live
directory is one stat. Fail-open per row: a row that will not move is reported
under ``held`` and left where it was.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from typing import Any

from agent_runtime import paths

__layer__ = "stores"
__all__ = ["REPORT_NAME", "retire_persona_assignment_store"]

logger = logging.getLogger(__name__)

REPORT_NAME = "persona_assignment_store_retired.json"


def _row_summary(raw: Any, name: str) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {"file": name, **{key: row.get(key) for key in ("id", "persona_id", "persona_instance_id", "state")}}


def retire_persona_assignment_store() -> dict[str, Any] | None:
    """Archive every residual assignment row and report it; ``None`` when there was nothing to do."""

    live = paths.persona_assignments_dir()
    if not live.is_dir():
        return None
    archive = paths.persona_assignments_archive_dir() / "retired_store"
    archived: list[dict[str, Any]] = []
    held: list[dict[str, str]] = []
    for source in sorted(live.glob("*.json")):
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except Exception:
            raw = None
        target = archive / source.name
        try:
            if target.exists():
                held.append({"file": source.name, "reason": "archive_target_exists"})
                continue
            archive.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except OSError as exc:
            held.append({"file": source.name, "reason": type(exc).__name__})
            continue
        archived.append(_row_summary(raw, source.name))
        logger.warning("persona_assignment_row_archived file=%s state=%s", source.name, archived[-1]["state"])
    try:
        live.rmdir()  # only when empty: anything held, or a non-row file, keeps it
    except OSError:
        pass
    report = {
        "schema": "hermes.agent_runtime.persona_assignment_store_retired/v1",
        "ran_at": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "archive_dir": str(archive),
        "archived": archived,
        "held": held,
    }
    marker = paths.store_root() / "migrations" / REPORT_NAME
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        previous = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else None
        runs = (previous.get("runs") if isinstance(previous, dict) else None) or []
        marker.write_text(json.dumps({"runs": [*runs, report]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        logger.warning("persona assignment retirement report not written", exc_info=True)
    return report
