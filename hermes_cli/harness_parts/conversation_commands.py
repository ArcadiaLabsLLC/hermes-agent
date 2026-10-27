"""``hermes harness conversation``: operator verbs over native conversation routes.

Holds no rule: ``chat-folder migrate`` is ``agent_runtime.conversations.chat_folder_migration``'s door.
"""

from __future__ import annotations

from agent_runtime import paths
from agent_runtime.cli_format import emit_json
from agent_runtime.root_observability import attach_root_observability

__layer__ = "lanes"
__all__ = ["_cmd_conversation_chat_folder_migrate"]


def _cmd_conversation_chat_folder_migrate(args) -> int:
    from agent_runtime.conversations.chat_folder_migration import migrate_chat_folders

    # The envelope names the root it moved: a wrong root answers a well-formed
    # empty plan (counts {}), which is indistinguishable from "nothing to move".
    data = attach_root_observability(
        migrate_chat_folders(root=paths.store_root(), apply=bool(getattr(args, "apply", False)))
    )
    if args.json:
        print(emit_json(data))
    else:
        verb = "applied" if data["applied"] else "would apply (dry run; pass --apply)"
        print(f"chat-folder migrate {verb}: " + (", ".join(
            f"{key}={value}" for key, value in sorted(data["counts"].items())) or "nothing to move"))
    return 0
