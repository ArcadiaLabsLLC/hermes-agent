"""``persona seat-unseated``: seat the agent instances a workspace's office level does not show.

Eternia row ``MC-AGENTS-A-LEAD-ADDED-LAST-NIGHT-ARE-NOT-ON-THE-OFFICE-LEVEL``: an
instance the argv ``--add-instance`` doors added before they seated it holds its
workspace and stands on no level. An explicit run, never on boot, so the owner
reads ``--dry-run`` first. The scan and the write: ``agent_runtime.agent_create.seat``.
"""

from __future__ import annotations

from agent_runtime.agent_create.seat import seat_unseated
from agent_runtime.cli_format import emit_json

__layer__ = "lanes"
__all__ = ["_cmd_persona_seat_unseated"]


def _line(seat: dict, *, dry_run: bool) -> str:
    if dry_run:
        return f"{seat['instance_id']}: would seat on {seat['workspace_id']}"
    if seat["seated"]:
        return f"{seat['instance_id']}: seated on {seat['workspace_id']} as {seat.get('actor_key')}"
    return f"{seat['instance_id']}: NOT seated on {seat['workspace_id']} ({seat['reason']}{': ' + seat['error'] if seat.get('error') else ''})"


def _cmd_persona_seat_unseated(args) -> int:
    dry_run = bool(args.dry_run)
    seats = [seat.receipt() for seat in seat_unseated(dry_run=dry_run)]
    if args.json:
        print(emit_json({"dry_run": dry_run, "seats": seats}))
    else:
        print("Dry run — nothing written:" if dry_run else "Seated:")
        for seat in seats:
            print(f"  {_line(seat, dry_run=dry_run)}")
        if not seats:
            print("  every instance added to a workspace stands on its level")
    return 1 if any(not seat["seated"] for seat in seats) and not dry_run else 0
