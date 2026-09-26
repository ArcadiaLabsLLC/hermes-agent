"""Live presentation facts only. Full tool results remain in native history."""
from __future__ import annotations

from agent_runtime.skill_activity import skill_load_evidence

__layer__ = "policy"

_TEXT = frozenset({"message.delta", "reasoning.delta", "thinking.delta",
                   "reasoning.available", "message.interim", "message.complete"})
_FIELDS = {
    "message.complete": ("status", "usage", "warning"),
    "tool.start": ("tool_id", "name"),
    "tool.complete": ("tool_id", "name"),
    "request.cancel": ("id", "request_id"),
    "session.usage": ("usage",),
    "session.info": ("usage", "model", "provider"),
    "notice": ("message",),
}
_CHARS = 16 * 1024  # bounded even after JSON escaping non-ASCII characters


def event_frames(frame: dict):
    params = frame["params"]
    kind, payload = params.get("type"), params.get("payload") or {}
    if kind not in _TEXT and kind not in _FIELDS:
        return
    if kind == "message.complete" and isinstance(payload.get("reasoning"), str) and payload["reasoning"]:
        yield from event_frames({"params": {**params, "type": "reasoning.available",
                                           "payload": {"text": payload["reasoning"]}}})
    selected = {key: payload[key] for key in _FIELDS.get(kind, ()) if key in payload}
    projected = {"method": "event", "params": {"session_id": params.get("session_id"),
                 "type": kind, "payload": selected}}
    if kind in {"tool.start", "tool.complete"}:
        evidence = skill_load_evidence(payload.get("name"), payload.get("args"),
                                       result=payload.get("result"), finished=kind == "tool.complete")
        if evidence:
            projected["skill_load"] = {"call_id": payload.get("tool_id"), **evidence}
    text = payload.get("text")
    if kind not in _TEXT or not isinstance(text, str):
        yield projected
        return
    for start in range(0, max(1, len(text)), _CHARS):
        part = {**selected, "text": text[start:start + _CHARS],
                "part_first": start == 0, "part_last": start + _CHARS >= len(text)}
        yield {**projected, "params": {**projected["params"], "payload": part}}
