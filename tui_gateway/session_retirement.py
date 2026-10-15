"""Release a settled native session, never infer that uncertain work has ended."""
from __future__ import annotations

from tui_gateway import session_execution


def eligible(server, sid, session, execution_id):
    live = session.get("native_execution")
    if live is not None and live["id"] != execution_id:
        return False
    if not server._session_is_lru_evictable(sid, session, require_dead_transport=False):
        return False
    if any(session.get(key) for key in (
            "queued_prompt", "queued_prompts", "_compute_host_turn_id", "_compute_host_open_request")):
        return False
    if any(thread is not None and thread.is_alive() for thread in (
            session.get("_run_thread"), session.get("_agent_build_thread"))):
        return False
    if server._pending_approval_request_payload(str(session.get("session_key") or "")):
        return False
    if execution_id is None:
        with server._session_db(session) as db:
            if db is None or db.get_messages(str(session.get("session_key") or ""), limit=1):
                return False
    evidence = session_execution.snapshot(session, execution_id)
    return (evidence is None and execution_id is None or evidence is not None
            and evidence["id"] == execution_id and evidence["status"] in {"complete", "interrupted", "error"})


def retire(server, sid, session, execution_id):
    with session_execution.control(session):
        with session["history_lock"]:
            if not eligible(server, sid, session, execution_id):
                return {"status": "protected"}
        if session.get("_compute_host_active") and server._session_uses_compute_host(session):
            reply = server._get_compute_host_supervisor().observe(sid, "session.retire", {
                "session_id": sid, "execution_id": execution_id})
            if reply.get("result", {}).get("status") != "retired":
                return {"status": "protected"}
        with server._session_resume_lock, server._sessions_lock, session["history_lock"]:
            if server._sessions.get(sid) is not session or not eligible(server, sid, session, execution_id):
                return {"status": "protected"}
            claimed = server._pop_session_by_id(sid)
    server._teardown_popped_session(claimed, end_reason="idle_timeout")
    return {"status": "retired"}


def register(server):
    def call(rid, params):
        with server._sessions_lock:
            if params["session_id"] not in server._sessions:
                return server._ok(rid, {"status": "retired"})
        session, error = server._sess_nowait(params, rid)
        if error:
            return error
        try:
            return server._ok(rid, retire(server, params["session_id"], session, params.get("execution_id")))
        except (RuntimeError, ValueError):
            return server._ok(rid, {"status": "protected"})

    server.register_method("session.retire", server._profile_scoped(call))
