"""``hermes harness conversation``: operator verbs over native conversation routes.

Holds no rule: ``chat-folder migrate`` is ``agent_runtime.conversations.chat_folder_migration``'s door.
"""

from __future__ import annotations

from agent_runtime import paths
from agent_runtime.cli_format import emit_json

__layer__ = "lanes"
__all__ = ["_cmd_conversation_chat_folder_migrate"]


def _cmd_conversation_chat_folder_migrate(args) -> int:
    from agent_runtime.conversations.chat_folder_migration import migrate_chat_folders

    data = migrate_chat_folders(root=paths.store_root(), apply=bool(getattr(args, "apply", False)))
    if args.json:
        print(emit_json(data))
    else:
        verb = "applied" if data["applied"] else "would apply (dry run; pass --apply)"
        print(f"chat-folder migrate {verb}: " + (", ".join(
            f"{key}={value}" for key, value in sorted(data["counts"].items())) or "nothing to move"))
    return 0
