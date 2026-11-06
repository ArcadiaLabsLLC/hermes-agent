"""RT-EXTERNAL-GATEWAY-CHANNEL-MESSAGE-VERB: ``runtime.channel.message``.

Plan ``docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md`` §2 D2–D4,
§5. ``(the proven device, channel_key)`` → ONE independent chat root of the bound instance, minted
by open-chat's own ``new_session`` door and replayed after; the turn rides ``runtime.chat.message``'s
own accept. Dispatcher tests go through ``serve_rpc.handle_request`` with a recording worker lane;
the last test runs a REAL serve with the gateway lane over TLS and a channel credential paired
through the real ceremony.
"""

from __future__ import annotations

from contextlib import closing

import pytest

from agent_runtime import gateway_channel, paths, serve_rpc
from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    DEVICE_KIND_CHANNEL,
    LOCAL_CONSOLE,
    TIER_CONSOLE,
    TRANSPORT_GATEWAY,
    RpcCaller,
)
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.serve_gateway_auth import mint_pairing_code, redeem_pairing_code
from tests.agent_runtime.test_serve_gateway_lane import (
    device_client,
    gateway_on,  # fixture
    running_serve,
)
from tests.agent_runtime.test_serve_rpc_open_chat import placed_agent, qa_persona  # fixtures


@pytest.fixture(autouse=True)
def switch_on(monkeypatch):
    monkeypatch.setattr(gateway_channel, "external_access_on", lambda env=None: True)


def _channel(instance_id: str, device_id: str = "dev_bot_a") -> RpcCaller:
    return RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id=device_id,
                     device_tier=TIER_CONSOLE, device_kind=DEVICE_KIND_CHANNEL, bound_instances=(instance_id,))


def _send(caller: RpcCaller, *, channel_key: str, text: str = "hello", turn: str, spawned=None, **extra) -> dict:
    def spawn(request_id, argv, turn_request_id):
        if spawned is not None:
            spawned.append((turn_request_id, argv))

    params = {"channel_key": channel_key, "text": text, "turn_request_id": turn, **extra}
    return serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": f"cm-{turn}", "method": "runtime.channel.message", "params": params},
        context=serve_rpc.RpcContext(caller=caller, spawn_chat_turn=spawn))


def _meta(session_id: str) -> dict:
    with closing(default_persona_session_db()) as db:
        return {key: db.get_session_model_config_value(session_id, key) for key in ("channel_source", "channel_key")}


def test_one_channel_key_lands_in_one_session_and_a_second_key_opens_a_second(placed_agent):
    instance = placed_agent["persona_instance_id"]
    caller = _channel(instance)
    spawned: list = []

    first = _send(caller, channel_key="telegram:42", turn="t-1", sender="Ada", spawned=spawned)["result"]
    again = _send(caller, channel_key="telegram:42", turn="t-2", spawned=spawned)["result"]
    other = _send(caller, channel_key="telegram:7", turn="t-3", spawned=spawned)["result"]

    assert first["accepted"] is True and first["persona_instance_id"] == instance
    assert (first["session_created"], again["session_created"]) == (True, False)
    assert again["session_id"] == first["session_id"]
    assert other["session_id"] != first["session_id"] and other["session_created"] is True
    assert _meta(first["session_id"]) == {"channel_source": "channel:dev_bot_a", "channel_key": "telegram:42"}
    # The turn is runtime.chat.message's own, on the minted root, with the sender shown to the agent.
    turn_id, argv = spawned[0]
    assert turn_id == "t-1" and first["session_id"] in argv and "Ada: hello" in argv
    # An independent conversation: the instance's own selected chat did not move.
    from agent_runtime.persona_assignments import PersonaInstanceStore

    assert PersonaInstanceStore().get(instance).session_id not in {first["session_id"], other["session_id"]}


def test_two_gateways_sharing_a_channel_key_never_share_a_session(placed_agent):
    """Killing mutation: derive ``channel_session_key`` from ``channel_key`` alone (drop the
    device id) → both gateways replay one root and the inequality reds."""

    instance = placed_agent["persona_instance_id"]
    a = _send(_channel(instance, "dev_bot_a"), channel_key="telegram:42", turn="x-1")["result"]
    b = _send(_channel(instance, "dev_bot_b"), channel_key="telegram:42", turn="x-2")["result"]
    assert a["session_id"] != b["session_id"]


def test_the_session_lists_in_the_instances_conversations(placed_agent):
    from agent_runtime.gateway_identity import ensure_install_identity

    instance = placed_agent["persona_instance_id"]
    sent = _send(_channel(instance), channel_key="telegram:42", turn="l-1")["result"]
    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "list", "method": "runtime.operator.conversation.list",
         "params": {"install_id": ensure_install_identity(paths.store_root()).install_id,
                    "all_accounts": True, "persona_instance_id": instance}},
        serve_rpc.RpcContext(caller=LOCAL_CONSOLE))
    rows = {row["session_id"]: row for row in reply["result"]["conversations"]}
    assert sent["session_id"] in rows and rows[sent["session_id"]]["persona_instance_id"] == instance


def test_refusals_are_typed(placed_agent):
    instance = placed_agent["persona_instance_id"]
    device = RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev_phone",
                       device_tier=TIER_CONSOLE)
    assert _send(device, channel_key="k", turn="r-1")["error"]["data"]["reason"] == "channel_credential_required"
    caller = _channel(instance)
    assert _send(caller, channel_key="k", turn="r-2", persona_instance_id="personainst_other")[
        "error"]["data"]["reason"] == "channel_instance_not_bound"
    assert _send(caller, channel_key="k", turn="r-3", attachments=[{"x": 1}])[
        "error"]["data"]["reason"] == "channel_attachments_unsupported"
    assert _send(caller, channel_key="", turn="r-4")["error"]["data"]["reason"] == "invalid_params"


def test_a_channel_message_over_the_real_gateway_lane(gateway_on, placed_agent):
    instance = placed_agent["persona_instance_id"]
    root = paths.store_root()
    code = mint_pairing_code(root, name="tg-bot", kind=DEVICE_KIND_CHANNEL, bound_instances=[instance])
    credential = redeem_pairing_code(root, code.code)
    with running_serve() as handle:
        with device_client(handle, credential) as (connection, reply):
            assert reply["event"] == "hello_ok", reply
            assert "runtime.channel.message" in reply["rpc"]["methods"]
            assert reply["rpc"]["params"]["runtime.channel.message"] == [
                "channel_key", "correlation_id", "persona_instance_id", "sender", "text", "turn_request_id"]
            connection.send({"jsonrpc": "2.0", "id": "g-1", "method": "runtime.channel.message",
                             "params": {"channel_key": "telegram:42", "text": "hi", "turn_request_id": "g-1"}})
            frame = None
            for _ in range(50):
                frame = connection.read_frame()
                if frame is None or frame.get("id") == "g-1":
                    break
    assert frame is not None and "result" in frame, frame
    result = frame["result"]
    assert result["accepted"] is True and result["request_id"] and result["session_created"] is True
    assert _meta(result["session_id"])["channel_source"] == "channel:tg-bot"


_ACCOUNT = "a" * 64


def _scoped_list(instance: str, client_scope: str) -> set[str]:
    from agent_runtime.gateway_identity import ensure_install_identity

    reply = serve_rpc.handle_request(
        {"jsonrpc": "2.0", "id": "scoped", "method": "runtime.operator.conversation.list",
         "params": {"install_id": ensure_install_identity(paths.store_root()).install_id,
                    "client_scope": client_scope, "persona_instance_id": instance}},
        serve_rpc.RpcContext(caller=LOCAL_CONSOLE))
    return {row["session_id"] for row in reply["result"]["conversations"]}


def test_a_scoped_channel_conversation_lists_under_its_account(placed_agent):
    """RT-EXTERNAL-GATEWAY-CHANNEL-CLIENT-SCOPE. Killing mutation: drop the ``client_scope`` key
    from ``_open_conversation``'s open-chat params → the minted root is unscoped, the account-
    filtered list omits it and the ``in listed`` assertion reds."""

    instance = placed_agent["persona_instance_id"]
    root = paths.store_root()
    scoped = redeem_pairing_code(root, mint_pairing_code(
        root, name="tg-bot", kind=DEVICE_KIND_CHANNEL, bound_instances=[instance], client_scope=_ACCOUNT).code)
    plain = redeem_pairing_code(root, mint_pairing_code(
        root, name="tg-old", kind=DEVICE_KIND_CHANNEL, bound_instances=[instance]).code)
    first = _send(_channel(instance, scoped.device_id), channel_key="telegram:42", turn="s-1")
    assert "result" in first, first
    sent = first["result"]
    again = _send(_channel(instance, scoped.device_id), channel_key="telegram:42", turn="s-2")["result"]
    legacy = _send(_channel(instance, plain.device_id), channel_key="telegram:42", turn="s-3")["result"]

    assert sent["client_scope"] == _ACCOUNT and again["session_id"] == sent["session_id"]
    listed = _scoped_list(instance, _ACCOUNT)
    assert sent["session_id"] in listed
    # A channel paired without a scope keeps today's answer: listed only under all_accounts.
    assert legacy["session_id"] not in listed and "client_scope" not in legacy
    assert sent["session_id"] not in _scoped_list(instance, "b" * 64)


def test_a_client_scope_is_a_channel_digest_or_refused():
    root = paths.store_root()
    wrong_kind = mint_pairing_code(root, name="phone", client_scope=_ACCOUNT)
    malformed = mint_pairing_code(root, name="bot", kind=DEVICE_KIND_CHANNEL,
                                  bound_instances=["personainst_x"], client_scope="Not-A-Digest")
    assert (wrong_kind.reason, malformed.reason) == ("invalid_client_scope", "invalid_client_scope")
