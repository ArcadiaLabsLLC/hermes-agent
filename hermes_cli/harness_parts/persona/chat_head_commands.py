"""``hermes harness persona chat-head migrate`` — the operator's one-time chat move (plan §2.3).

Dry-run by default; ``--apply`` writes. The verb itself is
``agent_runtime.chat_head_migration.migrate_chat_heads``; this is its argv door.
"""

from __future__ import annotations

import json

from agent_runtime.chat_head_migration import MigrateRefused, migrate_chat_heads
from agent_runtime.serde import safe_assignment_token

__layer__ = "lanes"
__all__ = ["_cmd_persona_chat_head_migrate"]


def _cmd_persona_chat_head_migrate(args) -> int:
    instance_id = safe_assignment_token(getattr(args, "instance", None)) or None
    try:
        data = migrate_chat_heads(instance_id=instance_id, apply=bool(getattr(args, "apply", False)))
    except MigrateRefused as exc:
        data = {"ok": False, "error_kind": exc.reason, "applied": False}
    if getattr(args, "json", False):
        print(json.dumps(data, sort_keys=True))
    else:
        mode = "applied" if data.get("applied") else "dry run (pass --apply to move)"
        print(f"chat-head migrate: {mode}")
        if "error_kind" in data:
            print(f"  refused: {data['error_kind']}")
        for row in data.get("instances", []):
            detail = row.get("reason") or f"{len(row.get('session_ids', []))} sessions -> {row.get('target_home')}"
            print(f"  {row['instance_id']}: {row['status']} ({detail})")
    return 0 if data.get("ok") else 2
