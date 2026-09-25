"""Evidence of skill loads, never a claim about the model's ongoing reasoning."""
import json


def object_value(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def skill_load_evidence(tool: str, arguments, *, result=None, finished=False) -> dict | None:
    args = object_value(arguments)
    name = args.get("name")
    if tool != "skill_view" or not isinstance(name, str) or not name or args.get("file_path"):
        return None
    data = object_value(result)
    status = "loading"
    if finished:
        status = "loaded" if data.get("success") is True else "failed"
    return {"id": name, "status": status}


def skill_load_history(messages: list[dict]) -> list[dict]:
    """Join tool results to their actual calls; prose mentions are not evidence."""
    calls, loaded = {}, {}
    for message in messages:
        for call in message.get("tool_calls") or ():
            function = call.get("function", {})
            evidence = skill_load_evidence(function.get("name"), function.get("arguments"))
            if evidence:
                calls[call.get("id")] = evidence["id"]
        name = calls.get(message.get("tool_call_id"))
        if name and message.get("role") == "tool":
            evidence = skill_load_evidence("skill_view", {"name": name},
                                           result=message.get("content"), finished=True)
            if evidence["status"] == "loaded":
                loaded[name] = {"id": name, "count": loaded.get(name, {}).get("count", 0) + 1}
    return list(loaded.values())


def with_skill_evidence(update, tool: str, arguments, *, result=None, finished=False):
    """ACP's metadata envelope carries the same client-neutral load evidence."""
    evidence = skill_load_evidence(tool, arguments, result=result, finished=finished)
    if evidence:
        update.field_meta = {**(update.field_meta or {}), "hermesSkill": evidence}
    return update
