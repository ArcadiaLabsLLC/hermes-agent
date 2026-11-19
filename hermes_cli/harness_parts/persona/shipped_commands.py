"""``persona sort-shipped``: sort the records an install already holds under a shipped agent's id.

Row ``RT-BUNDLED-AGENTS-EXISTING-RECORDS-SORTED`` (owner 2026-11-19). An explicit,
one-time run — never on boot — so the owner sees the plan (``--dry-run``) before
anything is written. The plan and the rules: ``agent_runtime.bundled_agents.sort_existing``.
"""

from __future__ import annotations

from agent_runtime.bundled_agents.sort_existing import apply_sort, plan_sort
from agent_runtime.cli_format import emit_json

__layer__ = "lanes"
__all__ = ["_cmd_persona_sort_shipped"]


def _names(pairs: list[str] | None) -> dict[str, str] | None:
    names: dict[str, str] = {}
    for pair in pairs or []:
        persona_id, _, name = pair.partition("=")
        if not persona_id.strip() or not name.strip():
            return None
        names[persona_id.strip()] = name.strip()
    return names


def _line(entry: dict) -> str:
    action = entry["action"] if "refused" not in entry else f"refused ({entry['refused']})"
    if entry["action"] == "copy":
        return (
            f"{entry['persona_id']}: {action} — '{entry['current_name']}' differs ({', '.join(entry['differences'])}); "
            f"kept as '{entry['copy_name']}' with instances {entry['instances_moved'] or 'none'}, "
            f"the shipped '{entry['shipped_name']}' takes the id (keeps {entry['instances_kept'] or 'no'} own channel)"
        )
    return f"{entry['persona_id']}: {action}" + (f" — {entry['why']}" if entry.get("why") else "")


def _cmd_persona_sort_shipped(args) -> int:
    names = _names(args.names)
    if names is None:
        print("--name takes ID=NAME")
        return 2
    plan = plan_sort(names) if args.dry_run else apply_sort(names)
    if args.json:
        print(emit_json({"dry_run": bool(args.dry_run), "plan": plan}))
    else:
        print("Dry run — nothing written:" if args.dry_run else "Sorted:")
        for entry in plan:
            print(f"  {_line(entry)}")
    return 1 if any("refused" in entry for entry in plan) else 0
