"""Read only the native missed-steer fact for a previously authorized child.

The child's captured native transcript path binds its delegation/task index.
No caller-supplied path, goal matching, task ordering or new result store.
"""
import re
from pathlib import Path

__layer__ = "lanes"


def completion_locator(record):
    child = record["agent"]
    path = getattr(child, "_live_transcript_path", None)
    delegation = record.get("delegation_id")
    if not path or not delegation:
        return None
    path = Path(path)
    match = re.fullmatch(r"task-(\d+)\.log", path.name)
    if match is None or path.parent.name != delegation:
        return None
    owners = frozenset(str(record.get(key) or "") for key in ("owner_session_id", "owner_agent_session_id")) - {""}
    return delegation, int(match[1]), owners


def missed_steering(locator):
    from tools.async_delegation import get_durable_delegation

    delegation, index, owners = locator
    try:
        row = get_durable_delegation(delegation)
        if not row or not ({row.get("origin_session"), row.get("origin_session_id")} & owners):
            return None
        result = row.get("result") or {}
        entries = result.get("results", [result])
        entry = next((e for e in entries if e.get("task_index") == index), None)
        if entry is None:
            return None
        return bool(entry.get("missed_steer"))
    except (OSError, ValueError, TypeError):
        return None
