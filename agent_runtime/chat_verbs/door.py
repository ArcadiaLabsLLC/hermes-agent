"""Run a CLI-owned chat verb through ``mission_chat_door`` and hand back its row.

The ``persona_open_chat`` discipline: the argparse handler IS the one
implementation, so the method builds that handler's namespace and reads the row
off ``args.payload_sink`` — never ``redirect_stdout``, which rebinds
``sys.stdout`` process-globally on a serve whose stdout is the frame protocol.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

__layer__ = "lanes"
__all__ = ["COORDINATOR_ARGS_CLOSED", "caller_requester", "run_cli_chat_verb"]

#: The coordinator-budget flags, closed: a method caller is never a coordinator
#: grant, so these read as the argparse defaults of a caller who passed none.
COORDINATOR_ARGS_CLOSED = {
    "coordinator_id": None,
    "coordinator_max_spawns": None,
    "coordinator_spawns_used": 0,
    "coordinator_may_kill_own": None,
    "coordinator_no_kill_own": None,
    "coordinator_may_kill_others": None,
}


def caller_requester(params: dict, caller: Any | None) -> str:
    """``requested_by``: the param, else the device the transport proved, else
    the argparse default ``"cli"`` (the ``persona_open_chat`` rule)."""
    from ..persona_open_chat import _caller_device_id, _text

    return _text(params, "requested_by") or _caller_device_id(caller) or "cli"


def run_cli_chat_verb(verb: str, **fields: Any) -> dict:
    """The handler's last row; a typed refusal row when the door is unbound or
    the handler exited without one (asserted, never assumed)."""
    from ..mission_chat_door import MissionChatDoorUnbound, run_chat_verb
    from ..serde import to_jsonable

    args = SimpleNamespace(json=True, **fields)
    try:
        exit_code, row = run_chat_verb(verb, args)
    except MissionChatDoorUnbound as exc:
        return {"ok": False, "error_kind": "mission_chat_door_unbound", "error": str(exc)}
    if not isinstance(row, dict):
        return {"ok": False, "error_kind": "chat_verb_payload_missing",
                "error": f"the {verb} handler exited without a payload", "exit_code": exit_code}
    row = dict(to_jsonable(row))
    if exit_code != 0 and row.get("ok") is True:
        row["ok"] = False
    return row
