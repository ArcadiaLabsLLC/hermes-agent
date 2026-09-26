"""Native session binding for the existing read-only skills service."""
from __future__ import annotations

import json

__layer__ = "wiring"


def install() -> None:
    from tui_gateway import server
    from tui_gateway.contracts.base import JsonValue, Result
    from tui_gateway.contracts.common import SessionParams
    from tui_gateway.contracts.registry import method

    class InspectParams(SessionParams):
        skill_id: str | None = None

    class InspectResult(Result):
        data: dict[str, JsonValue]

    for operation in ("list", "detail", "history"):
        name = "eternia.skills." + operation
        method(name, params=InspectParams, result=InspectResult)

        def inspect(rid, params, operation=operation):
            snapshot = server.handle_request({"jsonrpc": "2.0", "id": rid,
                "method": "session.activate", "params": {
                    "session_id": params["session_id"], "omit_messages": True}})
            if "error" in snapshot:
                return snapshot
            try:
                data = _inspect(operation, snapshot["result"], params.get("skill_id"))
                if len(json.dumps(data, ensure_ascii=True)) > 900 * 1024:
                    return {"jsonrpc": "2.0", "id": rid, "error": {
                        "code": 4130, "message": "This skill exceeds the document limit."}}
                return {"jsonrpc": "2.0", "id": rid, "result": {"data": data}}
            except (OSError, ValueError):
                return {"jsonrpc": "2.0", "id": rid, "error": {
                    "code": 4090, "message": "Skill information is unavailable."}}

        server.register_method(name, inspect)


def _inspect(operation: str, snapshot: dict, skill_id: str | None) -> dict:
    from agent.runtime_cwd import reset_session_cwd, set_session_cwd
    from agent_runtime.skill_activity import skill_load_history
    from hermes_constants import get_hermes_home
    from hermes_state_registry import acquire, release_or_close
    from tools.skills_tool import skill_inspection_reader

    info = snapshot["info"]
    token = set_session_cwd(info["cwd"])
    try:
        tools = info.get("tools") or {}
        can_load = any("skill_view" in names for names in tools.values() if isinstance(names, list))
        reader = skill_inspection_reader()
        if operation == "list":
            return {"skills": reader.catalog(can_load=can_load)}
        if operation == "detail":
            if not isinstance(skill_id, str) or not skill_id or len(skill_id) > 512:
                raise ValueError("invalid skill")
            return {"skill": reader.detail(skill_id, can_load=can_load)}
        key = info.get("stored_session_id") or snapshot.get("stored_session_id")
        if not key:
            return {"loaded": [], "historyComplete": False}
        db = acquire(get_hermes_home() / "state.db")
        try:
            messages = db.get_messages_as_conversation(key, include_ancestors=True)
            return {"loaded": skill_load_history(messages),
                    "historyComplete": not bool(snapshot.get("running") or info.get("running"))}
        finally:
            release_or_close(db)
    finally:
        reset_session_cwd(token)
