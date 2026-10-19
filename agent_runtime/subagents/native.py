"""Isolated compatibility bridge to upstream child records and owner predicates.

All private upstream
dependencies and retirement conditions are recorded in the subagent seam ledger.
"""
import hmac
import json
import time
from pathlib import Path

from agent_runtime import _upstream_doors as upstream
from agent_runtime.redaction import scrub_secret_values
from agent_runtime.skill_lends import child_target, lent_to
from .model import VERSION, TAIL_BYTES, LIVE_OPERATIONS, MUTATIONS, Refusal, SubagentError, validate_request
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


def child_registered(subagent_id: str) -> bool:
    """Is a child with ``subagent_id`` registered in THIS process now (the ``skill_lends`` sweep's test)?"""
    records, lock = upstream.subagent_registry()
    with lock:
        return subagent_id in records


def still_registered(record: dict) -> bool:
    records, lock = upstream.subagent_registry()
    with lock:
        current = records.get(record["subagent_id"])
        return current is not None and current.get("agent") is record.get("agent") and current.get("started_at") == record.get("started_at")


def revalidate_reply(operation, revalidate):
    try:
        revalidate()
    except Exception as exc:
        if operation in MUTATIONS:
            raise SubagentError(Refusal.UNKNOWN) from exc
        raise


def _child_capabilities(**_):
    return {"operations": [op for op in LIVE_OPERATIONS if op != "capabilities"], "tail_bytes": TAIL_BYTES}


def _child_roster(*, owner, records, exact, controllable, **_):
    children = []
    budget = 0
    for record in records[:MAX_CHILDREN]:
        row = {key: record.get(key) for key in FIELDS}
        for key, value in row.items():
            if isinstance(value, str):
                row[key] = scrub_secret_values(value[:4096])
        row["child_ref"] = references.child(owner, record) if exact(record) else None
        row["controllable"] = controllable(record)
        row["skills_lent"] = list(lent_to(child_target(str(record.get("subagent_id")))))
        budget += len(json.dumps(row, ensure_ascii=True))
        if budget > 800 * 1024:
            break
        children.append(row)
    return {"children": children, "truncated": len(records) > len(children)}


def _named_child(owner, records, exact, child_ref):
    """The one record ``child_ref`` names among ``records``; STALE when none (replaced, other generation)."""

    record = next((r for r in records if exact(r) and hmac.compare_digest(references.child(owner, r), child_ref)), None)
    if record is None:
        raise SubagentError(Refusal.STALE)
    return record


def _child_tail(*, owner, records, exact, revalidate, params, **_):
    record = _named_child(owner, records, exact, params["child_ref"])
    # Pin the authorized object through IO; never resolve a recyclable id again.
    tail = read_public_tail(record["agent"])
    revalidate()
    if not still_registered(record) or not exact(record):
        raise SubagentError(Refusal.STALE)
    return {**tail, "child_ref": params["child_ref"], "subagent_id": record["subagent_id"]}


_OBSERVERS = {"capabilities": _child_capabilities, "list": _child_roster, "tail": _child_tail}


def inspect_records(operation, params, *, owner, visible, exact, revalidate, controllable=None):
    validate_request(operation, params)
    generation = references.require_generation(owner, params.get("expected_generation"))
    result = {"version": VERSION, "generation": generation, "observed_at": time.time()}
    records = [record for record in visible if still_registered(record)]
    controllable = controllable or exact
    if observer := _OBSERVERS.get(operation):
        data = observer(owner=owner, records=records, exact=exact, controllable=controllable,
                        revalidate=revalidate, params=params)
    else:
        from .commands import control_records
        data = control_records(operation, params, owner=owner, records=records, exact=controllable, revalidate=revalidate)
    revalidate_reply(operation, revalidate)
    return {**result, **data}


def _native_owner(params: dict):
    """(owner, session, transport, exact, revalidate) for the native session ``params`` names."""
    from hermes_constants import get_hermes_home

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

    return owner, session, transport, exact, revalidate


def _visible_children(session_id, session, transport, exact):
    from hermes_constants import get_hermes_home

    return [record for record in upstream.subagent_visible_records(session_id, transport, session)
            if exact(record) or same_native_profile(record, session.get("agent"), get_hermes_home().resolve())]


def child_record(params: dict) -> dict:
    """The LIVE record ``params["child_ref"]`` names under ``owner_scope`` + ``worker_generation`` on the
    native session ``params["session_id"]`` (``eternia.skills.*``'s child address, p10-work S2).

    STALE when the reference names no registered child of this owner (a replaced worker, another
    generation); UNAVAILABLE for a compute-hosted session, whose children are not in this process.
    """

    child_ref = params.get("child_ref")
    if not isinstance(child_ref, str) or not child_ref or len(child_ref) > 512:
        raise SubagentError(Refusal.INVALID)
    owner, session, transport, exact, revalidate = _native_owner(params)
    if session.get("_compute_host_active") or upstream.subagent_uses_compute(session):
        raise SubagentError(Refusal.UNAVAILABLE)
    records = [r for r in _visible_children(params["session_id"], session, transport, exact) if still_registered(r)]
    record = _named_child(owner, records, exact, child_ref)
    revalidate()
    return record


def steer_child(params: dict, text: str, request_id: str) -> str:
    """Steer the child ``params`` addresses (``eternia.skills.lend``'s announce); the command's status."""
    from .commands import control_records

    owner, session, transport, exact, revalidate = _native_owner(params)
    records = [r for r in _visible_children(params["session_id"], session, transport, exact) if still_registered(r)]
    data = control_records("steer", {"child_ref": params["child_ref"], "request_id": request_id, "text": text},
                           owner=owner, records=records, exact=exact, revalidate=revalidate)
    return str(data.get("status") or "unknown")


def inspect_native(operation: str, params: dict) -> dict:
    validate_request(operation, params)
    session_id = params["session_id"]
    owner, session, transport, exact, revalidate = _native_owner(params)

    if session.get("_compute_host_active") or upstream.subagent_uses_compute(session):
        from .compute import observe

        data = observe(operation, params, owner)
        revalidate_reply(operation, revalidate)
        return data

    return inspect_records(operation, params, owner=owner,
        visible=_visible_children(session_id, session, transport, exact), exact=exact, revalidate=revalidate)
