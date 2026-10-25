"""Recovery reads the native session, history and requests under their existing owners."""
from __future__ import annotations
__layer__ = "lanes"

from agent_runtime.gateway import session_execution
from agent_runtime.gateway.recovery_history import checkpoint, history_page


#: The read methods a compute-host child answers on its ``observe`` frame (``ComputeHost._handle_observe``).
OBSERVABLE_METHODS = frozenset({
    "session.recover", "session.recovery.history", "session.recovery.inflight",
    "eternia.subagents.capabilities", "eternia.subagents.list", "eternia.subagents.tail",
    "eternia.subagents.receipt", "eternia.subagents.spawning",
    "session.events.since", "session.retire"})


def handle_observe(host, frame: dict) -> None:
    """The child's ``observe`` frame: one allowed read, answered ``observe.ack`` under the host's transport."""
    def body(server, sid, request_id):
        method = frame.get("method")
        if method not in OBSERVABLE_METHODS:
            raise ValueError("Unsupported observation")
        response = server.handle_request({"jsonrpc": "2.0", "id": request_id,
            "method": method, "params": {**(frame.get("params") or {}), "session_id": sid}})
        host._reply("observe.ack", sid, request_id, response=response)
    from tui_gateway.transport import bind_transport, reset_transport
    token = bind_transport(host._transport)
    try:
        host._guarded(frame, "observe.error", body)
    finally:
        reset_transport(token)


def recover(server, sid, session, execution_id=None):
    with session["history_lock"]:
        state = server._live_session_payload(sid, session, omit_messages=True)
        receipt = session_execution.snapshot(session, execution_id)
        with server._session_db(session) as db:
            key = str(session.get("session_key") or "")
            watermark = db.get_resume_message_watermark(key) if db else 0
        page = checkpoint(sid, 0, include_events=False)
        inflight = state.get("inflight")
        if inflight and receipt and (session.get("native_execution") or {}).get("id") == receipt["id"]:
            turn = session["inflight_turn"]
            state["inflight_position"] = {"execution_id": receipt["id"],
                "revision": turn.get("revision", 0),
                "segment_ends": list(turn.get("segment_ends") or []),
                **{field: len(turn.get(field) or "") for field in ("user", "assistant", "reasoning")}}
            state["inflight"] = {**inflight, "user": "", "assistant": ""}
        return {**state, "execution": receipt, "epoch": page["epoch"],
                "latest_seq": page["latest_seq"], "history": {
                    "session_key": key, "through_row": watermark,
                    "version": int(session.get("history_version", 0))}}


def inflight_page(server, session, params):
    with session["history_lock"]:
        turn = session.get("inflight_turn")
        identity = (session.get("native_execution") or {}).get("id")
        if (not turn or identity != params["execution_id"]
                or turn.get("revision", 0) != params.get("revision", 0)):
            return {"reset": True}
        text = str(turn.get(params["field"]) or "")
        through, offset = params["through"], params.get("offset", 0)
        if len(text) < through or offset > through:
            return {"reset": True}
        chunk = text[offset:min(through, offset + 16384)]
        return {"text": chunk, "offset": offset + len(chunk), "more": offset + len(chunk) < through}


def register(server):
    operations = {"session.recover": lambda s, p: recover(server, p["session_id"], s, p.get("execution_id")),
                  "session.recovery.history": lambda s, p: history_page(server, s, p),
                  "session.recovery.inflight": lambda s, p: inflight_page(server, s, p)}
    def handler(operation):
        def call(rid, params):
            session, error = server._sess_nowait(params, rid)
            if error:
                return error
            sid = params["session_id"]
            try:
                if session.get("_compute_host_active") and server._session_uses_compute_host(session):
                    reply = server._get_compute_host_supervisor().observe(sid, operation, params)
                    return {**reply, "id": rid}
                value = operations[operation](session, params)
                return server._ok(rid, value)
            except (RuntimeError, ValueError) as exc:
                return server._err(rid, 5019, str(exc))
        return call

    for operation in operations:
        server.register_method(operation, server._profile_scoped(handler(operation)))
