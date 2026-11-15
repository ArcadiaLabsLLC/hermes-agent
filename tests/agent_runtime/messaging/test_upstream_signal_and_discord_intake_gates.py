"""RT-MESSAGING-SHIM-STRANGER-GATE-HOLDS-ONLY-ON-TELEGRAM: the fork's operator list at Signal's and Discord's
OWN intake, driven through the adapters' real intake code.

Read in code first (``SWITCH_AUDIT.md`` finding 1, and the row): the shim's shared gate is an empty
``allow_from`` plus ``set_authorization_check``, and neither adapter asks it before it acts —

* Signal's ``_handle_envelope`` has no DM sender gate and fetches attachments (``_collect_attachments`` →
  ``_fetch_attachment``, signal-cli's ``getAttachment``) before ``handle_message``;
* Discord's ``_discord_message_admission`` asks ``_is_allowed_user``, which with no ``DISCORD_ALLOWED_*``
  refuses EVERY sender, the operator included, and the fork never hears of it.

The first test of each pair records the hazard with the shim's open gate (``is_allowed=None``); the rest run
the per-adapter overrides in ``agent_runtime/messaging/upstream_adapter_transport.py``. Neither library
(signal-cli, discord.py) is needed: Signal's adapter is httpx-only and its fetch is spied, Discord's admission
runs with the two ``discord`` names it reads stood in when discord.py is absent. No network.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agent_runtime.messaging.upstream_adapter_transport import (
    DiscordUpstreamAdapterTransport, SignalUpstreamAdapterTransport)

OPERATOR, STRANGER, ACCOUNT = "+15550000042", "+15550000099", "+15550000001"

SIGNAL_GATE_ENV = ("SIGNAL_ALLOWED_USERS", "SIGNAL_GROUP_ALLOWED_USERS", "SIGNAL_REQUIRE_MENTION",
                   "GATEWAY_ALLOW_ALL_USERS", "GATEWAY_ALLOWED_USERS")
DISCORD_GATE_ENV = ("DISCORD_ALLOWED_USERS", "DISCORD_ALLOWED_ROLES", "DISCORD_ALLOWED_CHANNELS",
                    "DISCORD_ALLOW_ALL_USERS", "GATEWAY_ALLOW_ALL_USERS", "GATEWAY_ALLOWED_USERS",
                    "DISCORD_IGNORE_NO_MENTION", "DISCORD_ALLOW_BOTS")


def _drain(adapter, coro):
    async def run():
        await coro
        pending = [t for t in list(getattr(adapter, "_background_tasks", ())) if not t.done()]
        pending += [t for t in list(getattr(adapter, "_session_tasks", {}).values()) if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    return run()


# ── Signal ──


@pytest.fixture
def signal(monkeypatch):
    from gateway.config import PlatformConfig
    from plugins.platforms.signal.adapter import SignalAdapter

    for name in SIGNAL_GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    made = []

    def make(*, hardened: bool):
        adapter = SignalAdapter(PlatformConfig(enabled=True, extra={"http_url": "http://127.0.0.1:9",
                                                                    "account": ACCOUNT}))
        fetched: list = []

        async def fetch(attachment_id):
            fetched.append(attachment_id)
            return None, ""

        adapter._fetch_attachment = fetch  # signal-cli's getAttachment, the thing a stranger must not reach
        refused: list = []
        inbound: list = []
        transport = SignalUpstreamAdapterTransport(
            adapter, connect=False,
            is_allowed=(lambda user_id: user_id == OPERATOR) if hardened else None,
            on_refused=(lambda *row: refused.append(row)) if hardened else None)
        transport.start(inbound.append)
        made.append(transport)
        rig = SimpleNamespace(adapter=adapter, transport=transport, fetched=fetched, refused=refused,
                              inbound=inbound)
        rig.receive = lambda envelope: transport._call(_drain(adapter, adapter._handle_envelope(envelope)))
        return rig

    yield make
    for transport in made:
        transport.stop()


def _envelope(sender, text="look at this", *, name="Someone", attachment="att-1", group=None, edit=False):
    message = {"timestamp": 1763000000000, "message": text,
               "attachments": [{"id": attachment, "size": 10, "contentType": "image/png"}] if attachment else []}
    if group:
        message["groupInfo"] = {"groupId": group}
    body = {"editMessage": {"dataMessage": message}} if edit else {"dataMessage": message}
    return {"envelope": {"sourceNumber": sender, "sourceName": name, "timestamp": 1763000000000, **body}}


def test_signal_with_the_open_gate_a_strangers_attachment_is_fetched_before_anyone_refuses(signal):
    """Records the hazard the override closes (the adapter's own path, no override installed)."""
    rig = signal(hardened=False)
    rig.receive(_envelope(STRANGER))
    assert rig.fetched == ["att-1"]


def test_signal_hardened_a_strangers_attachment_is_never_fetched_and_the_refusal_is_listed(signal):
    """Killing mutation: ``SignalUpstreamAdapterTransport._install_intake_gate`` returns without wrapping
    ``_handle_envelope`` → ``att-1`` is fetched and the message reaches the bridge → red."""
    rig = signal(hardened=True)
    rig.receive(_envelope(STRANGER, name="Stranger"))
    rig.receive(_envelope(STRANGER, "edited", name="Stranger", attachment="att-2", edit=True))
    assert rig.fetched == [] and rig.inbound == []
    assert rig.refused == [(STRANGER, STRANGER, "Stranger"), (STRANGER, STRANGER, "Stranger")]


def test_signal_hardened_a_stranger_in_an_allowed_group_is_refused_too(signal, monkeypatch):
    monkeypatch.setenv("SIGNAL_GROUP_ALLOWED_USERS", "*")
    rig = signal(hardened=True)
    rig.receive(_envelope(STRANGER, group="grp-1"))
    assert rig.fetched == [] and rig.inbound == [] and rig.refused == [(STRANGER, "group:grp-1", "Someone")]


def test_signal_hardened_the_operator_gets_through_with_their_attachment(signal):
    rig = signal(hardened=True)
    rig.receive(_envelope(OPERATOR, "what moved today?"))
    assert rig.fetched == ["att-1"] and rig.refused == []
    [message] = rig.inbound
    assert (message.user_id, message.chat_id, message.text) == (OPERATOR, OPERATOR, "what moved today?")


def test_signal_hardened_envelopes_with_no_message_are_the_adapters_and_list_nobody(signal):
    """A receipt or typing envelope from a stranger has nothing to fetch; listing it would fill the console's
    Allow list with everyone who ever read a message."""
    rig = signal(hardened=True)
    rig.receive({"envelope": {"sourceNumber": STRANGER, "receiptMessage": {"isRead": True}}})
    rig.receive({"envelope": {"sourceNumber": STRANGER, "typingMessage": {"action": "STARTED"}}})
    assert rig.refused == [] and rig.inbound == [] and rig.fetched == []


# ── Discord ──


class _DM:
    """Stands in for ``discord.DMChannel`` (isinstance is all the admission asks of it)."""

    id = 555


@pytest.fixture
def discord_rig(monkeypatch):
    from gateway.config import PlatformConfig
    from plugins.platforms.discord import adapter as discord_module
    from plugins.platforms.discord.adapter import DiscordAdapter

    for name in DISCORD_GATE_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(discord_module, "discord", SimpleNamespace(
        DMChannel=_DM, MessageType=SimpleNamespace(default="default", reply="reply")))
    made = []

    def make(*, hardened: bool):
        adapter = DiscordAdapter(PlatformConfig(enabled=True, token="discord-test-token"))
        adapter._client = SimpleNamespace(user=SimpleNamespace(id=1, bot=True))
        refused: list = []
        transport = DiscordUpstreamAdapterTransport(
            adapter, connect=False,
            is_allowed=(lambda user_id: user_id == "42") if hardened else None,
            on_refused=(lambda *row: refused.append(row)) if hardened else None)
        transport.start(lambda _message: None)
        made.append(transport)
        return SimpleNamespace(adapter=adapter, refused=refused)

    yield make
    for transport in made:
        transport.stop()


def _dm(user_id, name, message_id):
    return SimpleNamespace(id=message_id, type="default", channel=_DM(), guild=None, content="hi", mentions=[],
                           author=SimpleNamespace(id=user_id, bot=False, display_name=name, name=name.lower()))


def test_discord_with_the_open_gate_the_operator_is_refused_too(discord_rig):
    """Records the hazard: with no ``DISCORD_ALLOWED_*`` the adapter's own gate refuses everyone."""
    rig = discord_rig(hardened=False)
    assert rig.adapter._discord_message_admission(_dm(42, "Max", 1), claim=True) == (False, False)


def test_discord_hardened_the_operator_is_admitted_through_the_adapters_own_admission(discord_rig):
    """Killing mutation: ``DiscordUpstreamAdapterTransport._install_intake_gate`` returns without replacing
    ``_is_allowed_user`` → the adapter's fail-closed default refuses the operator → red."""
    rig = discord_rig(hardened=True)
    admitted, _roles = rig.adapter._discord_message_admission(_dm(42, "Max", 2), claim=True)
    assert admitted is True and rig.refused == []


def test_discord_hardened_a_stranger_is_refused_at_admission_and_listed_with_a_name(discord_rig):
    rig = discord_rig(hardened=True)
    assert rig.adapter._discord_message_admission(_dm(99, "Stranger", 3), claim=True) == (False, False)
    assert rig.refused == [("99", "", "Stranger")]


def test_discord_hardened_upstreams_wildcard_does_not_widen_the_forks_list(discord_rig, monkeypatch):
    """``DISCORD_ALLOW_ALL_USERS`` (or a pairing grant) is upstream's open mode; under the shim the fork's
    operator list is the one answer."""
    monkeypatch.setenv("DISCORD_ALLOW_ALL_USERS", "true")
    rig = discord_rig(hardened=True)
    assert rig.adapter._discord_message_admission(_dm(99, "Stranger", 4), claim=True) == (False, False)
