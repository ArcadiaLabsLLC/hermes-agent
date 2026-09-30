"""Native-worker transport for the Launcher's existing app-function tools."""
from __future__ import annotations

from agent_runtime import launcher_app_functions as app

__layer__ = "lanes"
METHOD = "eternia.launcher"


def declare_contracts():
    from tui_gateway.contracts import registry
    from tui_gateway.contracts.base import JsonValue, Result
    from tui_gateway.contracts.server_requests import ServerRequestParams

    if METHOD in registry.SERVER_REQUESTS:
        return

    class LauncherRequest(ServerRequestParams):
        request: dict[str, JsonValue]

    class LauncherReply(Result):
        reply: dict[str, JsonValue]

    registry.server_request(METHOD, params=LauncherRequest, result=LauncherReply)


def install():
    from tui_gateway.contract_seam import pydantic_contracts_enabled

    if pydantic_contracts_enabled():
        declare_contracts()


def enabled(session):
    return (session or {}).get("source") == "eternia_intelligence"


class _Sink:
    def __init__(self, sid):
        self.sid = sid

    def emit(self, frame):
        from tui_gateway import server_requests

        timeout = app.LIST_TIMEOUT_SECONDS if frame["method"] == app.LIST_METHOD else app.CALL_TIMEOUT_SECONDS
        result = server_requests.send(METHOD, self.sid, {"request": frame}, timeout=timeout)
        reply = (result or {}).get("reply")
        if not isinstance(reply, dict):
            reply = {"error": {"code": -32000, "message": "The Launcher connection is unavailable."}}
        app.resolve_response({**reply, "id": frame["id"]}, self)


def bind(sid, session):
    link = app.LauncherLink(_Sink(sid), app.ORIGIN_LOCAL) if enabled(session) else None
    return app.bind_launcher_link(link)


def reset(token):
    app.reset_launcher_link(token)


def create_agent(factory, sid, session, **kwargs):
    """Snapshot tools before the first prompt; later turns retain that prefix."""
    if not enabled(session):
        return factory(**kwargs)
    install()
    token = bind(sid, session)
    try:
        names = app.refresh_app_function_tools(app.current_launcher_link())
        if names:
            toolsets = kwargs.get("enabled_toolsets")
            kwargs["enabled_toolsets"] = list(dict.fromkeys([*(toolsets if toolsets is not None else ["all"]), app.APP_FUNCTIONS_TOOLSET]))
        return factory(**kwargs)
    finally:
        reset(token)
