"""D1.07 S1 — ``peer.agent_chat.cancel``, the execute's Stop, answered by the install running the turn.

Driven through ``serve_rpc.handle_request`` with a fake peer caller and an
injected interrupt seam, as the execute tests drive the execute: the turn is
accepted through the real ``perform_chat_turn`` so the receipt the cancel reads
is the one an execute writes.
"""

from __future__ import annotations

from agent_runtime import serve_rpc
from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    CALLER_PEER,
    PEER_METHOD_ALLOWLIST,
    TIER_CONSOLE,
    TIER_READ,
    RpcCaller,
    STDIO_OWNER,
)
from agent_runtime.chat_turn import (
    PEER_CHAT_CANCEL_METHOD,
    PEER_CHAT_EXECUTE_METHOD,
    perform_chat_turn,
)
from agent_runtime.chat_turn_reservations import read_chat_turn_receipt, settle_chat_turn

PEER_A = RpcCaller(
    kind=CALLER_PEER, transport="gateway", peer_install_id="install-a", connection_key="k1"
)
PEER_C = RpcCaller(
    kind=CALLER_PEER, transport="gateway", peer_install_id="install-c", connection_key="k2"
)
DISPATCH_ID = "dispatch-abc123"
#: The wire literal an install of ANY build sends as the execute's request id
#: (``tools/agent_chat/detached.py``). Spelled out, not derived, so a change to
#: the derivation on this side reds here instead of silently missing older senders.
WIRE_TURN_REQUEST_ID = "agent-dispatch-dispatch-abc123"


def _accept_turn(install: str = "install-a") -> None:
    outcome = perform_chat_turn(
        {"turn_request_id": WIRE_TURN_REQUEST_ID, "target": "dev", "message": "run the suite"},
        verb=PEER_CHAT_EXECUTE_METHOD,
        spawn=lambda *_: None,
        peer_install_id=install,
    )
    assert outcome.refusal is None


def _cancel(caller=PEER_A, *, params=None, interrupt=None):
    seen: list[str] = []

    def seam(turn_request_id: str) -> bool:
        seen.append(turn_request_id)
        return True

    reply = serve_rpc.handle_request(
        {
            "jsonrpc": "2.0",
            "id": "c1",
            "method": PEER_CHAT_CANCEL_METHOD,
            "params": {"dispatch_id": DISPATCH_ID, "reason": "operator_stop"} if params is None else params,
        },
        serve_rpc.RpcContext(caller=caller, interrupt_operator=interrupt or seam),
    )
    return reply, seen


def test_the_verb_is_registered_allowlisted_and_declares_console():
    manifest = serve_rpc.manifest()

    assert PEER_CHAT_CANCEL_METHOD in manifest["methods"]
    assert manifest["tiers"][PEER_CHAT_CANCEL_METHOD] == TIER_CONSOLE
    assert PEER_CHAT_CANCEL_METHOD in PEER_METHOD_ALLOWLIST


def test_a_live_turn_is_stopped_through_the_interrupt_seam_with_the_derived_id():
    """Killing mutation: derive the id with a different salt in ``cancel_peer_turn``
    → no receipt is found → ``not_running`` and the seam is never called."""

    _accept_turn()

    reply, seen = _cancel()

    result = reply["result"]
    assert result["outcome"] == "stopping"
    assert result["turn_request_id"] == WIRE_TURN_REQUEST_ID
    assert result["owner_observed"] is True
    assert result["peer"] == "install-a"
    assert result["reason"] == "operator_stop"
    assert seen == [WIRE_TURN_REQUEST_ID]
    # Durable too: a turn still queued on the pool reads this when it starts.
    assert read_chat_turn_receipt(WIRE_TURN_REQUEST_ID).stop_requested is True


def test_a_settled_turn_is_already_finished_and_nothing_is_interrupted():
    _accept_turn()
    assert settle_chat_turn(turn_request_id=WIRE_TURN_REQUEST_ID, exit_code=0)

    reply, seen = _cancel()

    assert reply["result"]["outcome"] == "already_finished"
    assert reply["result"]["exit_code"] == 0
    assert seen == []


def test_an_unknown_dispatch_is_not_running():
    reply, seen = _cancel()

    assert reply["result"]["outcome"] == "not_running"
    assert seen == []


def test_another_install_cannot_stop_the_turn_install_a_asked_for():
    _accept_turn("install-a")

    reply, seen = _cancel(PEER_C)

    assert reply["result"]["outcome"] == "not_running"
    assert seen == []
    assert read_chat_turn_receipt(WIRE_TURN_REQUEST_ID).stop_requested is False


def test_a_read_tier_device_is_refused_by_the_chokepoint():
    device = RpcCaller(
        kind=CALLER_DEVICE, transport="gateway", device_id="phone", device_tier=TIER_READ
    )

    reply, seen = _cancel(device)

    assert reply["error"]["data"]["reason"] == "scope_denied"
    assert seen == []


def test_a_non_peer_caller_is_refused_with_its_own_reason():
    _accept_turn()

    reply, seen = _cancel(STDIO_OWNER)

    assert reply["error"]["data"]["reason"] == serve_rpc.PEER_CHAT_NOT_A_PEER_REASON
    assert seen == []


def test_a_missing_dispatch_id_is_refused_out_loud():
    reply, _ = _cancel(params={"reason": "x"})

    assert reply["error"]["data"]["reason"] == "dispatch_id_required"


def test_a_transport_with_no_interrupt_seam_refuses_rather_than_pretending():
    _accept_turn()
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "c1", "method": PEER_CHAT_CANCEL_METHOD,
         "params": {"dispatch_id": DISPATCH_ID}},
        serve_rpc.RpcContext(caller=PEER_A),
    )

    assert reply["error"]["data"]["reason"] == "control_unavailable"
    assert read_chat_turn_receipt(WIRE_TURN_REQUEST_ID).stop_requested is False
