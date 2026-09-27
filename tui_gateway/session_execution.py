"""Execution evidence on native sessions; SessionDB remains the durable owner."""
from __future__ import annotations

import json
import threading
from contextlib import nullcontext

_TERMINAL = frozenset({"complete", "interrupted", "error"})


def checkpoint_guard(session: dict):
    return session["history_lock"] if session.get("native_execution") else nullcontext()


def publish(sessions: dict, frame: dict, write):
    params = frame.get("params") or {}
    session = sessions.get(params.get("session_id")) if isinstance(params, dict) else None
    if session is None:
        return write(frame)
    with checkpoint_guard(session):
        stamp(session, frame)
        return write(frame)


def control(session: dict):
    """Fence provider interrupt against a later admission without holding history."""
    return session.setdefault("execution_control_lock", threading.RLock())


def _store(session, record):
    from tui_gateway import server

    with server._session_db(session) as db:
        if db is None:
            raise RuntimeError("Execution storage is unavailable")
        def merge(raw):
            prior = json.loads(raw) if raw else {}
            value = {**prior, **record}
            if prior.get("status") in _TERMINAL:
                value["status"] = prior["status"]
            value["cancel_requested"] = bool(prior.get("cancel_requested") or record["cancel_requested"])
            return json.dumps(value, separators=(",", ":"))
        return json.loads(db.update_meta("native_execution:" + record["id"], merge))


def admit(session: dict, execution_id: str | None) -> None:
    """Called inside the native turn claim, before any provider work."""
    if not execution_id:
        session.pop("native_execution", None)
        return
    from tui_gateway import server

    with server._session_db(session) as db:
        if db is None:
            raise RuntimeError("Execution storage is unavailable")
        key = "native_execution:" + execution_id
        record = {"id": execution_id, "session_key": session["session_key"],
                  "status": "running", "cancel_requested": False}
        def create(raw):
            if raw is not None:
                raise ValueError("Execution already admitted; recover its outcome instead of replaying it")
            return json.dumps(record, separators=(",", ":"))
        db.update_meta(key, create)
    session["native_execution"] = record


def submitted(session: dict) -> None:
    record = session.get("native_execution")
    user = session.get("_submit_user_row") or {}
    if record is not None and isinstance(user.get("_row_id"), int):
        record = {**record, "user_row_id": user["_row_id"]}
        session["native_execution"] = _store(session, record)


def uncertain(session: dict, execution_id: str) -> None:
    with session["history_lock"]:
        record = session.get("native_execution")
        if record is None or record["id"] != execution_id or record["status"] in _TERMINAL:
            return
        record = {**record, "status": "unknown"}
        session["native_execution"] = _store(session, record)


def stamp(session: dict, frame: dict) -> None:
    """The native event and terminal receipt share the history lock."""
    record = session.get("native_execution")
    if record is None or frame.get("method") != "event":
        return
    params = frame.get("params") or {}
    # Relayed compute events already carry their execution identity.
    if params.get("execution_id", record["id"]) != record["id"]:
        return
    params["execution_id"] = record["id"]
    payload = params.get("payload") or {}
    from tui_gateway.inflight_recovery import record as record_inflight
    record_inflight(session, params.get("type"), payload)
    status = payload.get("status")
    if params.get("type") == "message.complete" and status in _TERMINAL:
        record = {**record, "status": status}
        session["native_execution"] = _store(session, record)


def snapshot(session: dict, execution_id: str | None) -> dict | None:
    live = session.get("native_execution")
    if live is not None and (not execution_id or live["id"] == execution_id):
        return dict(live)
    if not execution_id:
        return None
    from tui_gateway import server

    with server._session_db(session) as db:
        if db is None:
            raise RuntimeError("Execution storage is unavailable")
        raw = db.get_meta("native_execution:" + execution_id)
        if raw is None:
            return None
        record = json.loads(raw)
        key = str(session.get("session_key") or "")
        if record["session_key"] != key and record["session_key"] not in db.get_compression_lineage(key):
            raise ValueError("Execution belongs to another session")
    if record["status"] not in _TERMINAL:
        record["status"] = "unknown"
    return record


def request_stop(session: dict, expected: str) -> bool:
    """Latch intent without manufacturing an outcome. Caller holds control + history."""
    record = session.get("native_execution")
    if record is None or record["id"] != expected or record["status"] in _TERMINAL:
        return False
    record = {**record, "cancel_requested": True}
    session["native_execution"] = _store(session, record)
    return session["native_execution"]["status"] not in _TERMINAL


def interrupt(sid: str, session: dict, expected: str) -> bool:
    from tui_gateway import server

    with control(session):
        with session["history_lock"]:
            if not request_stop(session, expected):
                return False
        server._interrupt_session_turn(sid, session, expected_execution_id=expected)
        return True


def adopt(session: dict, record: dict | None) -> bool:
    """A compute child adopts the parent's admitted receipt, never admits twice."""
    if record is None:
        session.pop("native_execution", None)
        return True
    evidence = snapshot(session, record["id"])
    if evidence is None:
        raise RuntimeError("Execution receipt is unavailable")
    if evidence["status"] in _TERMINAL:
        raise ValueError("Execution already settled")
    session["native_execution"] = {**evidence, "status": "running"}
    return not evidence["cancel_requested"]
