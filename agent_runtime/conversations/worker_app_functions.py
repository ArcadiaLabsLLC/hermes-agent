"""Native-worker transport for the Launcher's existing app-function tools."""
from __future__ import annotations

from contextlib import nullcontext, suppress
from dataclasses import dataclass

from agent_runtime import launcher_app_functions as app
from agent_runtime.launcher_client_requests import resolve_response

__layer__ = "lanes"
METHOD = "eternia.launcher"
_SESSION_STATE_KEY = "_launcher_app_function_binding"


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
        self.closed = False

    def close(self):
        self.closed = True
        app.forget_launcher_connection(self)

    def emit(self, frame):
        from tui_gateway import server_requests

        if self.closed:
            resolve_response({"id": frame["id"], "error": {
                "code": -32000, "message": "The Launcher connection is unavailable."}}, self)
            return
        timeout = app.LIST_TIMEOUT_SECONDS if frame["method"] == app.LIST_METHOD else app.CALL_TIMEOUT_SECONDS
        result = server_requests.send(METHOD, self.sid, {"request": frame}, timeout=timeout)
        reply = (result or {}).get("reply")
        if not isinstance(reply, dict):
            reply = {"error": {"code": -32000, "message": "The Launcher connection is unavailable."}}
        resolve_response({**reply, "id": frame["id"]}, self)


@dataclass(frozen=True)
class SessionBinding:
    """Worker-owned connection; the gateway's session record owns its lifetime."""
    sid: str
    link: app.LauncherLink

    @property
    def closed(self) -> bool:
        return self.link.sink.closed


def close(session, *, expected=None):
    """Release only this record's connection, including failed/abandoned builds."""
    if session is None:
        return
    with session.get("history_lock") or nullcontext():
        held = session.get(_SESSION_STATE_KEY)
        if isinstance(held, SessionBinding) and (expected is None or held is expected):
            session.pop(_SESSION_STATE_KEY)
            held.link.sink.close()


def _binding(sid, session):
    if session is None:
        return None, False
    with session.get("history_lock") or nullcontext():
        held = session.get(_SESSION_STATE_KEY)
        if not enabled(session) or session.get("_closing") or session.get("_finalized"):
            if isinstance(held, SessionBinding):
                session.pop(_SESSION_STATE_KEY)
                held.link.sink.close()
            return None, False
        if isinstance(held, SessionBinding):
            if held.sid != sid:
                return None, False  # A foreign sid cannot retarget this record.
            if not held.closed:
                return held, False
        held = SessionBinding(sid, app.LauncherLink(_Sink(sid), app.ORIGIN_LOCAL))
        session[_SESSION_STATE_KEY] = held
        return held, True


def bind(sid, session):
    binding, _ = _binding(sid, session)
    return app.bind_launcher_link(binding.link if binding else None)


def reset(token):
    app.reset_launcher_link(token)


def create_agent(factory, sid, session, **kwargs):
    """Snapshot tools before the first prompt; later turns retain that prefix."""
    if not enabled(session):
        close(session)
        return factory(**kwargs)
    install()
    binding, created = _binding(sid, session)
    if binding is None:
        raise RuntimeError("The Launcher app-function session is closed or unavailable.")
    token = app.bind_launcher_link(binding.link)
    try:
        names = app.refresh_app_function_tools(app.current_launcher_link())
        if binding.closed:
            raise RuntimeError("The Launcher app-function session is closed.")
        if names:
            toolsets = kwargs.get("enabled_toolsets")
            kwargs["enabled_toolsets"] = list(dict.fromkeys([*(toolsets if toolsets is not None else ["all"]), app.APP_FUNCTIONS_TOOLSET]))
        agent = factory(**kwargs)
        if binding.closed:
            with suppress(Exception):
                agent.close()
            raise RuntimeError("The Launcher app-function session is closed.")
        return agent
    except BaseException:
        # A failed replacement must not retire the still-live agent's connection.
        if created or session.get("agent") is None:
            close(session, expected=binding)
        if binding.closed:
            app.forget_launcher_connection(binding.link.sink)
        raise
    finally:
        reset(token)
