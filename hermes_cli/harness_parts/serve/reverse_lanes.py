"""The serve's reverse lanes: opened beside the pool, closed with the socket lanes.

Both roles of ``agent_runtime.reverse_lane`` run in one object per serve. As a COMPUTER,
its hello hook (``reverse_lane.lanes.handoff``, installed on the loopback and gateway
listeners) parks a paired phone's lane and splices the owner's attach onto it. As a PHONE,
its admitter — a ``ConnectionAdmitter`` with no listener — serves the computer over the
lane this engine dialled, with this session's own dispatcher, greeting and disconnect path,
on the ``gateway`` transport so every remote-door refusal (the argv lane, the denied ops,
the unknown-caller guard) applies to it unchanged.

Opened on every serve, the embedded (phone) one included: it opens no socket by itself.
Per serve, never process-global: the hook and the ``runtime.gateway.reverse.*`` verbs reach
this session's lanes through the session (``RpcContext.reverse_lanes``).
"""

from __future__ import annotations

from typing import Any

from hermes_cli.harness_parts.serve.constants import GATEWAY_TRANSPORT, SERVE_SCHEMA_VERSION

__layer__ = "lanes"

__all__ = ["close_reverse_lanes", "open_reverse_lanes", "reverse_handoff"]


def open_reverse_lanes(session: Any) -> Any:
    """Build this serve's reverse lanes; ``None`` without a store root."""

    store_root = getattr(session, "store_root_path", None)
    if store_root is None:
        return None
    from agent_runtime.reverse_lane.lanes import ReverseLanes, lane_authenticator

    def admitter() -> Any:
        from agent_runtime.serve_socket.admit import ConnectionAdmitter

        return ConnectionAdmitter(
            store_root,
            boot_id=session.boot_id,
            dispatch_line=session._handle_socket_line,
            hello_payload=session._hello_ok_frame,
            # No root token on a lane: the grant's lane proof is the only credential.
            token_provider=lambda: None,
            authenticator=lane_authenticator(store_root),
            transport_name=GATEWAY_TRANSPORT,
            frame_contract=SERVE_SCHEMA_VERSION,
            on_disconnect=session._on_connection_closed,
            log=session._service_log,
        )

    def call_admitter() -> Any:
        from agent_runtime.pair_call.calls import call_lane_authenticator
        from agent_runtime.serve_socket.admit import ConnectionAdmitter

        # A lane of a call (``agent_runtime.pair_call``): its caller proves its own credential, bound to
        # the call and lane ids; served like the gateway lane, every remote-door refusal included.
        return ConnectionAdmitter(
            store_root,
            boot_id=session.boot_id,
            dispatch_line=session._handle_socket_line,
            hello_payload=session._hello_ok_frame,
            token_provider=lambda: None,
            authenticator=call_lane_authenticator(store_root),
            transport_name=GATEWAY_TRANSPORT,
            frame_contract=SERVE_SCHEMA_VERSION,
            on_disconnect=session._on_connection_closed,
            log=session._service_log,
        )

    return ReverseLanes(store_root, admitter_factory=admitter, call_admitter_factory=call_admitter,
                        log=session._service_log)


def close_reverse_lanes(lanes: Any, reason: str) -> None:
    if lanes is not None:
        lanes.close(reason)


def reverse_handoff(session: Any) -> Any:
    """The listeners' hello hook, bound to *session*'s lanes as they are when a hello arrives."""

    def hook(admitter: Any, connection: Any, reader: Any, message: dict[str, Any]) -> bool:
        from agent_runtime.reverse_lane.lanes import handoff

        return handoff(getattr(session, "reverse_lanes", None), admitter, connection, reader, message)

    return hook
