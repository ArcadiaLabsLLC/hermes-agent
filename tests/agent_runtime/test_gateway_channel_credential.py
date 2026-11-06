"""RT-EXTERNAL-GATEWAY-CHANNEL-CREDENTIAL: a ``channel`` device row, and what it may reach.

Plan ``docs/agent-runtime-harness/planned/external-gateway-namespace-access-2026-11-05.md`` §2 D1,
§5 (owner ruling C, 2026-11-05). A channel credential holds ``console``; its KIND narrows it to the
chat verbs (``call_authorization.CHANNEL_METHOD_ALLOWLIST``) and its ``bound_instances`` narrow
those to the agents it was paired for (``gateway_channel.channel_target_refusal``). Every gate
assertion goes through ``serve_rpc.handle_request`` — the dispatcher — because that is where the
decision is made; a test that called a handler directly would prove nothing about the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime import gateway_channel, serve_rpc
from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    DEVICE_KIND_CHANNEL,
    DEVICE_KIND_DEVICE,
    TIER_CONSOLE,
    TIER_READ,
    TRANSPORT_GATEWAY,
    RpcCaller,
    caller_for_connection,
)
from agent_runtime.serve_gateway_auth import (
    DeviceCredential,
    PairingCode,
    StoreRefusal,
    device_store_path,
    list_devices,
    lookup_device,
    mint_pairing_code,
    redeem_pairing_code,
)

BOUND = "personainst_qa"
OTHER = "personainst_qa_agent_2"


def _channel(bound=(BOUND,), tier: str = TIER_CONSOLE) -> RpcCaller:
    return RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev_bot",
                     device_tier=tier, device_kind=DEVICE_KIND_CHANNEL, bound_instances=tuple(bound))


def _call(method: str, params: dict, caller: RpcCaller) -> dict:
    return serve_rpc.handle_request({"jsonrpc": "2.0", "id": "c-1", "method": method, "params": params},
                                    context=serve_rpc.RpcContext(caller=caller))


@pytest.fixture
def switch_on(monkeypatch):
    """The external-access switch, on. Its own rule is RT-EXTERNAL-GATEWAY-SWITCH-GATE's file."""

    monkeypatch.setattr(gateway_channel, "external_access_on", lambda env=None: True)


# ── the row ──────────────────────────────────────────────────────────────────


def test_a_channel_code_redeems_to_a_channel_row_bound_to_its_instances(tmp_path: Path):
    code = mint_pairing_code(tmp_path, name="telegram bot", kind=DEVICE_KIND_CHANNEL,
                             bound_instances=[BOUND, BOUND, " "])
    assert isinstance(code, PairingCode)
    credential = redeem_pairing_code(tmp_path, code.code)
    assert isinstance(credential, DeviceCredential)
    assert (credential.kind, credential.bound_instances) == (DEVICE_KIND_CHANNEL, (BOUND,))
    row = json.loads(device_store_path(tmp_path).read_text(encoding="utf-8"))["devices"][credential.device_id]
    assert (row["kind"], row["bound_instances"]) == ("channel", [BOUND])
    record = lookup_device(tmp_path, credential.device_id)
    assert record.payload()["device_kind"] == "channel" and record.payload()["bound_instances"] == [BOUND]


def test_a_row_written_before_the_rule_reads_as_a_plain_device(tmp_path: Path):
    code = mint_pairing_code(tmp_path, name="phone")
    credential = redeem_pairing_code(tmp_path, code.code)
    path = device_store_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "kind" not in payload["devices"][credential.device_id], "a plain device row grew a key"
    [record] = list_devices(tmp_path)
    assert (record.kind, record.bound_instances) == (DEVICE_KIND_DEVICE, ())


def test_an_unknown_kind_word_reads_as_the_narrower_channel(tmp_path: Path):
    code = mint_pairing_code(tmp_path)
    credential = redeem_pairing_code(tmp_path, code.code)
    path = device_store_path(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["devices"][credential.device_id]["kind"] = "admin"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert lookup_device(tmp_path, credential.device_id).kind == DEVICE_KIND_CHANNEL


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"kind": "channel"}, "bound_instances_required"),
        ({"kind": "channel", "bound_instances": [BOUND], "tier": TIER_READ}, "invalid_tier"),
        ({"kind": "device", "bound_instances": [BOUND]}, "invalid_bound_instances"),
        ({"kind": "bot"}, "invalid_kind"),
    ],
)
def test_a_channel_code_needs_console_and_a_bound_instance(tmp_path: Path, kwargs, reason):
    refusal = mint_pairing_code(tmp_path, **kwargs)
    assert isinstance(refusal, StoreRefusal) and refusal.reason == reason


def test_the_connection_stamp_becomes_a_channel_caller():
    class _Conn:
        key, transport, authenticated, peer_install_id = "k", TRANSPORT_GATEWAY, True, None
        device_id, device_tier, device_kind, bound_instances = "dev_bot", TIER_CONSOLE, "channel", (BOUND,)

    caller = caller_for_connection(_Conn())
    assert (caller.kind, caller.device_kind, caller.bound_instances) == (CALLER_DEVICE, "channel", (BOUND,))
    assert caller.describe()["bound_instances"] == [BOUND]
    _Conn.device_kind = None
    assert caller_for_connection(_Conn()).device_kind == DEVICE_KIND_DEVICE


# ── the gate ─────────────────────────────────────────────────────────────────


def test_a_chat_verb_for_an_unbound_instance_is_refused_channel_instance_not_bound(switch_on):
    """Killing mutation: drop the bound-instance check (``channel_target_refusal`` returns
    ``None``) → this call is admitted to the handler and the assertion reds."""

    reply = _call("runtime.chat.message",
                  {"turn_request_id": "t-1", "persona_id": "qa", "persona_instance_id": OTHER, "message": "hi"},
                  _channel())
    assert reply["error"]["data"]["reason"] == "channel_instance_not_bound", reply


def test_a_session_owned_by_an_unbound_instance_is_refused_even_naming_a_bound_one(switch_on):
    reply = _call("runtime.chat.steer",
                  {"turn_request_id": "t-2", "persona_instance_id": BOUND,
                   "session_id": f"persona_chat_{OTHER}_0123456789ab", "message": "hi"},
                  _channel())
    assert reply["error"]["data"]["reason"] == "channel_instance_not_bound", reply


def test_a_chat_verb_naming_no_instance_is_refused(switch_on):
    reply = _call("runtime.chat.message", {"turn_request_id": "t-3", "persona_id": "qa", "message": "hi"},
                  _channel())
    assert reply["error"]["data"]["reason"] == "channel_instance_not_bound", reply


def test_a_chat_verb_for_the_bound_instance_is_admitted(switch_on):
    """Admitted past the gate: the refusal, if any, is the HANDLER's (no worker lane here)."""

    reply = _call("runtime.chat.message",
                  {"turn_request_id": "t-4", "persona_id": "qa", "persona_instance_id": BOUND,
                   "session_id": f"persona_chat_{BOUND}_0123456789ab", "message": "hi"},
                  _channel())
    assert reply["error"]["data"]["reason"] not in {"channel_instance_not_bound", "scope_denied"}, reply


@pytest.mark.parametrize("method", ["runtime.agent.retire", "runtime.office.get", "runtime.workspace.use"])
def test_every_non_chat_verb_is_refused_for_the_kind(switch_on, method):
    """Killing mutation: delete the channel arm in ``authorize_call`` → ``runtime.office.get`` (read)
    and ``runtime.agent.retire`` (console, which the device equality admits) pass and red."""

    reply = _call(method, {"persona_instance_id": BOUND}, _channel())
    assert reply["error"]["data"]["reason"] == "scope_denied", reply


def test_a_plain_console_device_is_untouched_by_the_channel_rules(switch_on):
    device = RpcCaller(kind=CALLER_DEVICE, transport=TRANSPORT_GATEWAY, device_id="dev_phone",
                       device_tier=TIER_CONSOLE, device_kind=DEVICE_KIND_DEVICE)
    reply = _call("runtime.chat.message",
                  {"turn_request_id": "t-5", "persona_id": "qa", "persona_instance_id": OTHER, "message": "hi"},
                  device)
    assert reply["error"]["data"]["reason"] not in {"channel_instance_not_bound", "scope_denied"}, reply
