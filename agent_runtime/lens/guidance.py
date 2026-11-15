"""A monitor's plain-language RULES, and the workspace default a monitor without its own follows.

Design ``planned/lens-act-and-safe-investigate.md`` §2 and §7 row 1 (row ``RT-LENS-MONITOR-RULES``,
owner-approved 2026-11-14). Named *guidance* in code because ``rules.py`` is the trigger rules
(threshold, the fired rule); Eternia shows it as "Rules".

Three layers, the first present wins (:func:`effective_guidance`):

=============  ==========================================================================
``source``     where the text lives
=============  ==========================================================================
``monitor``    the monitor manifest's ``guidance`` key, sealed with its revision (``manifest.py``)
``workspace``  the ``guidance_defaults`` row of the monitor's workspace, written over the runtime
               RPC (``runtime.lens.guidance.default.set``), in the Lens store, so it survives a
               serve restart and needs no config file
``shipped``    :data:`SHIPPED_GUIDANCE`, the design's default text
=============  ==========================================================================

A monitor with no workspace (one created before workspace scope) reads the unscoped default, key
``""``. A realm re-key moves a workspace's default with its monitors (``realm_rekey_outside``). The text is TRUSTED operator input (the rules check puts it in the guardian's system prompt,
row ``RT-LENS-RULES-CHECK-BEFORE-INVESTIGATE``), so no persona path writes it: ``lens_propose``'s
closed argument set has no ``guidance`` key, and these writes are console-tier RPC verbs only.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from .manifest import read_guidance
from .store import LensStore, to_ms

__layer__ = "stores"

#: The design's shipped default (§2), used when neither the monitor nor its workspace has rules.
SHIPPED_GUIDANCE = (
    "Investigate only when the change is worth a look. Read; never write, send, buy, delete or post.\n"
    "Act only with the actions listed for this monitor, and only when the action can be undone.\n"
    "Anything else, or anything you are unsure of, goes to the owner."
)

_SCHEMA = """CREATE TABLE IF NOT EXISTS guidance_defaults (
  workspace_id TEXT PRIMARY KEY, text TEXT NOT NULL, updated_ms INTEGER NOT NULL)"""


def rekey_workspace_guidance(connection: Any, pairs: list[tuple[str, str]]) -> None:
    """Move each ``(new, old)`` workspace's default to its new id, inside the realm re-key's own
    transaction (``realm_rekey_outside._rekey_lens``); a store that never held a default has no table."""

    if connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'guidance_defaults'").fetchone():
        connection.executemany("UPDATE OR REPLACE guidance_defaults SET workspace_id = ? WHERE workspace_id = ?", pairs)


def _key(workspace_id: str | None) -> str:
    return workspace_id or ""


def workspace_guidance(store: LensStore, workspace_id: str | None) -> dict[str, Any]:
    """``{workspace_id, text, source: workspace|shipped, updated_at_ms, shipped_text}``."""

    row = None
    if store.exists():
        with store.connection() as conn:
            conn.execute(_SCHEMA)
            row = conn.execute("SELECT text, updated_ms FROM guidance_defaults WHERE workspace_id = ?",
                               (_key(workspace_id),)).fetchone()
    if row is None:
        return {"workspace_id": workspace_id, "text": SHIPPED_GUIDANCE, "source": "shipped",
                "updated_at_ms": None, "shipped_text": SHIPPED_GUIDANCE}
    return {"workspace_id": workspace_id, "text": row[0], "source": "workspace",
            "updated_at_ms": int(row[1]), "shipped_text": SHIPPED_GUIDANCE}


def set_workspace_guidance(store: LensStore, workspace_id: str | None, text: Any) -> dict[str, Any]:
    """Write the workspace default (``text``), or forget it (``None``: back to the shipped text)."""

    with store.connection() as conn:
        conn.execute(_SCHEMA)
        if text is None:
            conn.execute("DELETE FROM guidance_defaults WHERE workspace_id = ?", (_key(workspace_id),))
        else:
            conn.execute("INSERT OR REPLACE INTO guidance_defaults (workspace_id, text, updated_ms) "
                         "VALUES (?, ?, ?)", (_key(workspace_id), read_guidance(text), to_ms(datetime.now(UTC))))
    return workspace_guidance(store, workspace_id)


def effective_guidance(store: LensStore, manifest: dict[str, Any] | None,
                       workspace_id: str | None) -> dict[str, Any]:
    """``{text, source: monitor|workspace|shipped}`` — the rules ``manifest`` runs under."""

    own = (manifest or {}).get("guidance")
    if own is not None:
        return {"text": own, "source": "monitor"}
    default = workspace_guidance(store, workspace_id)
    return {"text": default["text"], "source": default["source"]}


def monitor_guidance(store: LensStore, monitor: dict[str, Any]) -> dict[str, Any]:
    """The effective rules of ``monitor`` (a ``LensStore.get`` summary): its SEALED revision's, the
    one that runs; a never-sealed monitor's draft's. ``draft`` adds the pending next revision's
    effective rules when a draft waits, so a reseal's change is visible before it is sealed."""

    sealed = (monitor.get("sealed") or {}).get("manifest")
    current = effective_guidance(store, sealed if sealed is not None else monitor.get("draft"),
                                 monitor.get("workspace_id"))
    draft = None
    if sealed is not None and monitor.get("draft") is not None:
        draft = effective_guidance(store, monitor["draft"], monitor.get("workspace_id"))
    return {**current, "draft": draft}
