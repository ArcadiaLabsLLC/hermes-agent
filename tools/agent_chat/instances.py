"""``agent_add_instance`` — a lead agent staffs a workspace with instances of an agent, in one call.

Row ``RT-AGENTS-HAVE-A-TOOL-TO-ADD-AN-INSTANCE`` (review w1118a.53 D8; owner 2026-11-19: "yes agreed it
needs a first class row"). Seen 2026-11-19: Neko Mission Lead Beta, staffing a wave, scripted
``hermes harness persona instance create --add-instance`` in its terminal, picked placement ids by hand,
named the seats itself and left no record of who asked. This tool takes the agent and the workspace
only; ``agent_runtime.agent_create.staff`` reuses an idle instance first, places the rest through
``runtime.agent.place`` (the runtime names each "<agent> · 2"), records the asking instance as each new
one's ``spawned_by``, and holds the asker to its coordinator spawn budget.

A door and nothing else: it resolves WHO is asking from the turn's own session and hands the call down.
"""

from __future__ import annotations

import json

__layer__ = "lanes"
__all__ = ["AGENT_ADD_INSTANCE_SCHEMA", "agent_add_instance"]

AGENT_ADD_INSTANCE_SCHEMA = {
    "name": "agent_add_instance",
    "description": (
        "Add instances of an agent to a workspace, e.g. to staff a wave. Idle instances already there are "
        "reused first; the runtime places and names the rest. Ask for every instance you need in ONE call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "description": "The agent: its id (e.g. 'dev'), its name, or one of its personainst_* handles.",
            },
            "workspace": {
                "type": "string",
                "description": "The workspace id or name. Omit for your own workspace.",
            },
            "count": {
                "type": "integer",
                "description": "How many instances you need in all (1-6, default 1).",
            },
        },
        "required": ["agent"],
    },
}


def agent_add_instance(agent=None, workspace=None, count=None, *, requested_by_session=None) -> str:
    """Staff ``workspace`` with ``count`` instances of ``agent``; the answer is the runtime's, as JSON."""

    from agent_runtime.agent_create.staff import StaffRefused, staff_agent_instances
    from agent_runtime.persona_assignments import chat_session_owner_instance_id
    from agent_runtime.request_actor import request_actor

    session = str(requested_by_session or "").strip() or None
    # The asking agent instance, read off the turn's own chat session — never a param the model fills.
    # MUTATION: pass requested_by=None and test_the_tool_places_a_numbered_instance_that_names_the_asking_instance reddens.
    asker = request_actor(chat_session_owner_instance_id(session))
    wanted = 1 if count is None else count
    try:
        answer = staff_agent_instances(
            agent, workspace=workspace, count=wanted, requested_by=asker, asking_session=session,
        )
    except StaffRefused as exc:
        return json.dumps({"ok": False, "error": str(exc), "reason": exc.reason,
                           **{k: v for k, v in exc.data.items() if v is not None}})
    return json.dumps({"ok": "stopped" not in answer, **answer})
