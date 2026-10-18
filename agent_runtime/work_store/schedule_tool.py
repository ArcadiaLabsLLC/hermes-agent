"""``schedule_manage`` — the one fork tool over the serve's scheduler (dispatcher plan §4, B4).

A persona arms a ``PersonaPrompt`` (a prompt that arrives later as one queued turn of a named persona
instance), lists, or disarms; batches and Work assignments are armed by the operator only
(``runtime.schedule.arm``). The tool lives in the opt-in ``schedule`` toolset, never ``harness_core``:
manual by default means a persona schedules only when the operator opted its profile in. It replaces
upstream's ``cronjob`` for the fork: no script, no delivery adapter, no session per run (RT-D1/D6 moot).
"""

from __future__ import annotations

import json
from typing import Any

from .reasons import WorkRefused

__layer__ = "lanes"
__all__ = ["SCHEDULE_MANAGE_SCHEMA", "SCHEDULE_TOOLSET", "handle_schedule_manage"]

SCHEDULE_TOOLSET = "schedule"

SCHEDULE_MANAGE_SCHEMA: dict[str, Any] = {
    "name": "schedule_manage",
    "description": (
        "Schedule a prompt to arrive later as a turn of a persona instance's chat (queued behind any turn "
        "already running there), list armed schedules, or disarm one. Triggers: at (UTC ISO time), every "
        "(minutes), cron (5-field expression + tz), when_idle (fires once the chat root has been idle for "
        "two ticks)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["arm", "list", "disarm"]},
            "key": {"type": "string", "description": "Schedule key (letters, digits, _ . : -); arm joins an existing key."},
            "persona_instance_id": {"type": "string", "description": "arm: the instance whose chat receives the prompt."},
            "prompt": {"type": "string", "description": "arm: the message the turn starts with."},
            "trigger": {
                "type": "object",
                "description": "arm: {kind: at|every|cron|when_idle, at, minutes, expr, tz, root}.",
            },
        },
        "required": ["action"],
    },
}


def handle_schedule_manage(args: dict[str, Any], **kwargs: Any) -> str:
    from .schedule_ops import execute

    op = str(args.get("action") or "")
    params = {"key": args.get("key"), "trigger": args.get("trigger")}
    if op == "arm":
        params["action"] = {"type": "persona_prompt", "persona_instance_id": args.get("persona_instance_id") or "",
                            "prompt": args.get("prompt") or ""}
    who = f"tool:schedule_manage:{kwargs.get('task_id') or '-'}"
    try:
        return json.dumps(execute(op, params, armed_by=who), default=str)
    except WorkRefused as refusal:
        return json.dumps({"error": refusal.reason.value, "detail": refusal.detail})
