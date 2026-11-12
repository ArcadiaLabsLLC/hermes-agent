"""The realm re-key's journal, read side (``realm_rekey/<old realm id>.json``).

Apart from ``agent_runtime.realm_rekey`` (which writes it) so that the snapshot's realm row can read
:func:`rekeyed_from` without importing the operation (RT-REKEY-ID-MAP-FOR-ETERNIA).
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from . import paths

__layer__ = "stores"
__all__ = ["JOURNAL_DIRNAME", "RekeyState", "read_rekey_journal", "rekey_journal_path", "rekeyed_from"]

JOURNAL_DIRNAME = "realm_rekey"


class RekeyState(str, Enum):
    OWED = "owed"
    RUNNING = "running"
    DONE = "done"


def rekey_journal_path(realm_id: str) -> Path:
    return paths.store_root() / JOURNAL_DIRNAME / f"{paths.safe_path_token(realm_id)}.json"


def read_rekey_journal(realm_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(rekey_journal_path(realm_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def rekeyed_from(realm_id: str) -> dict[str, Any] | None:
    """``{realm_id, workspaces, agents, at}`` for a realm that is the local copy a finished re-key made — the
    ids it had while it was the team's, old -> new, and when it took its own (from that moment it has its own
    agents) — else ``None``. A read of the journals, which are filed under the OLD realm id."""
    directory = paths.store_root() / JOURNAL_DIRNAME
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            journal = json.loads(path.read_text(encoding="utf-8"))
            found = journal["map"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if journal.get("state") == RekeyState.DONE.value and found.get("realm_new") == realm_id:
            return {"realm_id": found["realm_old"], "workspaces": dict(found.get("workspaces") or {}),
                    "agents": dict(found.get("agents") or {}), "at": journal.get("done_at")}
    return None
