"""Apply idle model changes in the existing compute owner and return its receipt."""
from tui_gateway.session_execution import control


def apply(server, frame: dict, session: dict) -> dict:
    with control(session):
        if session.get("running"):
            return {"error": "session busy"}
        params = {**frame.get("params", {}), "session_id": frame["sid"], "key": "model"}
        response = server.handle_request({"jsonrpc": "2.0", "id": frame["request_id"],
                                          "method": "config.set", "params": params})
        if "error" in response:
            return {"error": response["error"]["message"]}
        return {"result": response["result"],
                "session_info": server._session_info(session.get("agent"), session)}


def forward(server, rid, params: dict, session: dict) -> dict:
    sid = params["session_id"]
    with control(session):
        if session.get("running"):
            return server._err(rid, 5032, "session busy")
        ack = server._send_compute_host_control(sid, route_name="config.set.model",
                                                payload={"params": params})
        error = server._compute_host_ack_error(rid, ack, 5001, "Model change was not confirmed")
        if error is not None:
            return error
        server._apply_compute_host_metadata_mirror(session, ack)
        # An acknowledged explicit pick supersedes a formerly queued pick.
        if not ack["result"].get("confirm_required"):
            session.pop("pending_model_switch", None)
        return server._ok(rid, ack["result"])
