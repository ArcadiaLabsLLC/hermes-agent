"""Isolated compatibility bridge to upstream child records and owner predicates.

Read-only; controls retain their own later approval. All private upstream
dependencies and retirement conditions are recorded in the subagent seam ledger.
"""
import hmac
import json
import time
from pathlib import Path

from agent_runtime import _upstream_doors as upstream
from agent_runtime.redaction import scrub_secret_values
from .model import VERSION, TAIL_BYTES, Refusal, SubagentError, validate_request
from .output import read_public_tail
from .references import references

__layer__ = "lanes"

FIELDS = ("subagent_id", "parent_id", "depth", "goal", "delegation_id", "model",
          "started_at", "status", "tool_count", "last_tool", "accepting_steer")
MAX_CHILDREN = 256


def has_live_ancestor(record, parents):
    return not parents or any(upstream.subagent_is_descendant(record.get("agent"), parent) for parent in parents)


def same_native_profile(record, parent, home):
    child = record.get("agent")
    child_db = getattr(getattr(child, "_session_db", None), "db_path", None)
    parent_db = getattr(getattr(parent, "_session_db", None), "db_path", None)
    logs_dir = getattr(child, "logs_dir", None)
    return bool(child_db and parent_db and logs_dir and
                Path(child_db).resolve() == Path(parent_db).resolve() and
                Path(logs_dir).resolve().parent == home)


def registry_snapshot() -> list[dict]:
    records, lock = upstream.subagent_registry()
    with lock:
        return [dict(record) for record in records.values()]


def still_registered(record: dict) -> bool:
    records, lock = upstream.subagent_registry()
    with lock:
        current = records.get(record["subagent_id"])
        return current is not None and current.get("agent") is record.get("agent") and current.get("started_at") == record.get("started_at")


def inspect_records(operation, params, *, owner, visible, exact, revalidate):
    validate_request(operation, params)
    generation = references.require_generation(owner, params.get("expected_generation"))
    result = {"version": VERSION, "generation": generation, "observed_at": time.time()}
    if operation == "capabilities":
        return {**result, "operations": ["list", "tail"], "tail_bytes": TAIL_BYTES}
    records = [record for record in visible if still_registered(record)]
    if operation == "list":
        children = []
        budget = 0
        for record in records[:MAX_CHILDREN]:
            row = {key: record.get(key) for key in FIELDS}
            for key, value in row.items():
                if isinstance(value, str):
                    row[key] = scrub_secret_values(value[:4096])
            row["child_ref"] = references.child(owner, record) if exact(record) else None
            budget += len(json.dumps(row, ensure_ascii=True))
            if budget > 800 * 1024:
                break
            children.append(row)
        revalidate()
        return {**result, "children": children, "truncated": len(records) > len(children)}
    record = next((r for r in records if exact(r) and hmac.compare_digest(
        references.child(owner, r), params["child_ref"])), None)
    if record is None:
        raise SubagentError(Refusal.STALE)
    # Pin the authorized object through IO; never resolve a recyclable id again.
    tail = read_public_tail(record["agent"])
    revalidate()
    if not still_registered(record) or not exact(record):
        raise SubagentError(Refusal.STALE)
    return {**result, **tail, "child_ref": params["child_ref"], "subagent_id": record["subagent_id"]}


def inspect_native(operation: str, params: dict) -> dict:
    from hermes_constants import get_hermes_home

    validate_request(operation, params)
    session_id = params["session_id"]
    transport, session = upstream.subagent_session_authority(session_id)
    if session is None or transport is None:
        raise SubagentError(Refusal.WRONG_OWNER)
    owner = (params["owner_scope"], params["worker_generation"], str(get_hermes_home().resolve()),
             session_id, id(session), id(transport))

    def exact(record):
        return (record.get("owner_session_id") == session_id and
                record.get("owner_session_record") is session and
                upstream.subagent_transport_matches(record, transport))

    def revalidate():
        current_transport, current_session = upstream.subagent_session_authority(session_id)
        if current_transport is not transport or current_session is not session:
            raise SubagentError(Refusal.WRONG_OWNER)

    if session.get("_compute_host_active") or upstream.subagent_uses_compute(session):
        from .compute import observe

        data = observe(operation, params, owner)
        revalidate()
        return data

    visible = [record for record in upstream.subagent_visible_records(session_id, transport, session)
               if exact(record) or same_native_profile(record, session.get("agent"), get_hermes_home().resolve())]
    return inspect_records(operation, params, owner=owner,
        visible=visible, exact=exact, revalidate=revalidate)
