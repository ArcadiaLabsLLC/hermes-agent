"""``schedule_manage`` — the one fork tool over the serve's scheduler (dispatcher plan §4, B4).

A persona arms a ``PersonaPrompt`` (a prompt that arrives later as one queued turn of a named persona
instance) or a ``RunTask`` (a board task run again and again by the agent it names — owner 2026-11-12:
"agents should also be able to schedule it for you", ``RT-SCHEDULE-RUN-TASK-REPEATS``), lists, or disarms;
batches and frozen Work assignments are armed by the operator only (``runtime.schedule.arm``). An arm goes
through ``schedule_ops.execute``, so the record it stores is the one the RPC stores. The tool lives in the opt-in ``schedule`` toolset, never ``harness_core``:
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
        "already running there), or schedule a board task to be run by an agent (run_task: the task is read "
        "afresh at each run and stays open between runs of a repeating schedule), list armed schedules, or "
        "disarm one. Triggers: at (UTC ISO time), every "
        "(minutes), cron (5-field expression + tz), when_idle (fires once the chat root has been idle for "
        "two ticks). A schedule here delivers a message to an agent's chat; a cron job (cronjob_manage, "
        "where you hold it) runs a standalone job with its own session and delivery target."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["arm", "list", "disarm"]},
            "key": {"type": "string", "description": "Schedule key (letters, digits, _ . : -); arm joins an existing key."},
            "persona_instance_id": {"type": "string", "description": "arm: the instance whose chat receives the prompt."},
            "prompt": {"type": "string", "description": "arm: the message the turn starts with."},
            "run_task": {
                "type": "object",
                "description": "arm, instead of prompt: {workspace_id, slot, task_id, persona_instance_id, "
                               "goal_mode: none|until_done} — run that board task with that agent.",
            },
            "replace": {"type": "boolean", "description": "arm: overwrite the schedule already under the key."},
            "trigger": {
                "type": "object",
                "description": "arm: {kind: at|every|cron|when_idle, at, minutes, expr, tz, root}.",
            },
        },
        "required": ["action"],
    },
}


def _arm_action(args: dict[str, Any]) -> dict[str, Any]:
    """The action an arm names: ``run_task`` when the call carries one, else the prompt."""

    instance = args.get("persona_instance_id") or ""
    task = args.get("run_task")
    if isinstance(task, dict):
        return {**task, "type": "run_task", "persona_instance_id": task.get("persona_instance_id") or instance}
    return {"type": "persona_prompt", "persona_instance_id": instance, "prompt": args.get("prompt") or ""}


def handle_schedule_manage(args: dict[str, Any], **kwargs: Any) -> str:
    from .schedule_ops import execute

    op = str(args.get("action") or "")
    params = {"key": args.get("key"), "trigger": args.get("trigger")}
    if op == "arm":
        params["action"] = _arm_action(args)
        params["replace"] = args.get("replace") is True
    who = f"tool:schedule_manage:{kwargs.get('task_id') or '-'}"
    try:
        return json.dumps(execute(op, params, armed_by=who), default=str)
    except WorkRefused as refusal:
        return json.dumps({"error": refusal.reason.value, "detail": refusal.detail})
