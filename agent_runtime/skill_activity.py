"""Evidence of skill loads, never a claim about the model's ongoing reasoning."""
import json

__layer__ = "policy"


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
    """Native preload snapshots and successful tool calls are load evidence.

    Unchanged envelope stubs refer to an earlier snapshot, not another load.
    This is also the operator composer's chat activity source; never infer
    active instructions from a client draft or a prose mention.
    """
    from .runtime_hud.envelopes import extract_runtime_context_envelope, extract_skill_preload_envelope

    calls, loaded = {}, {}
    for message in messages:
        if message.get("role") == "user":
            content, _ = extract_runtime_context_envelope(message.get("content"))
            _, preload = extract_skill_preload_envelope(content)
            if preload and preload.get("delivery", "snapshot") == "snapshot":
                for name in preload["skills"]:
                    loaded[name] = {"id": name, "count": loaded.get(name, {}).get("count", 0) + 1}
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

