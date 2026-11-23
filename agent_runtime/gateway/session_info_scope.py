"""A chat's ``session.info`` is built under that chat's own profile scope, whoever asks for it.

Upstream's ``tui_gateway/server.py::_session_info`` reads profile-owned state (the route's reasoning catalog via
``route_supported_efforts``, config, credentials) through ``get_hermes_home()`` and ``get_secret()``. About thirty
callers reach it (``session.info``/resume RPCs, ``config.set``, slash commands, model switch, ``broadcast_session_info``,
the end-of-turn settled emit) and the RPC dispatcher binds no profile scope for them; the turn's settled emit runs after
its secret scope is released. On a multiplexed serve an unscoped secret read raises ``UnscopedSecretError`` and a home
read answers for the LAUNCH profile, so a second profile's chat reported the launch home's catalog. Row
RT-FU-A-CHATS-STATUS-READ-OUTSIDE-ITS-TURN-RUNS-UNDER-NO-PROFILE-SCOPE: fixed here, in fork code, not in the upstream file.

The split modules' bodies are rebound onto server.py's namespace (``tui_gateway/method_ctx.bind_module``), so every
caller looks ``_session_info`` up in server.py's globals at call time. :func:`register` runs after that binding
(``agent_runtime.gateway_extensions.register``) and wraps the bound name in the session's full profile runtime scope
(HERMES_HOME + secrets + terminal policy; ``hydrate_secrets=False``: a status read never starts an external secret
source). A caller already inside that scope binds the same scope again, which changes nothing.
"""
from __future__ import annotations

__layer__ = "lanes"


def register(server) -> None:
    upstream_info = server._session_info

    def _session_info(agent, session: dict | None = None) -> dict:
        if session is None:  # upstream's own lookup, done first so the scope knows the session's profile
            session = next((c for c in server._sessions.values() if c.get("agent") is agent), None)
        profile_home = (session or {}).get("profile_home") or None
        with server._session_profile_runtime_scope({"profile_home": profile_home}, hydrate_secrets=False):
            return upstream_info(agent, session)

    _session_info.__doc__ = upstream_info.__doc__
    _session_info.__wrapped__ = upstream_info
    server._session_info = _session_info
