"""RT-CHAT-MESSAGE-MINT-UNSCOPED: the send lane's first-send mint carries the client scope.

A scoped console send that names no session reaches ``_mint_send_root``; the root it mints is
the chat the account lists (``launcher.agent_chat.list`` filters on ``client_scope``). Before
this, the mint was called with no scope, so the chat was unscoped and dropped from the list
after a relaunch (Eternia MC-CONSOLE-FIRST-SEND-CHAT-UNSCOPED-DROPS-FROM-DIRECTORY).
"""

from __future__ import annotations

from argparse import Namespace

from hermes_cli.harness_parts.persona import chat_turn_message


def _mint(monkeypatch, args: Namespace) -> dict:
    seen: dict = {}

    def fake_mint_chat_root(**kwargs):
        seen.update(kwargs)
        return Namespace(session_id="persona_chat_x", dispatched_from={})

    monkeypatch.setattr(chat_turn_message, "mint_chat_root", fake_mint_chat_root)
    minted, refused = chat_turn_message._mint_send_root(
        args, instance_store=object(), session_db=object(), normalized_persona="base",
        persona_instance_id="personainst_base", client_message_id="m1", session_id=None,
        mint_title="Base chat", existing_root=None, requested_by_session=None,
    )
    assert refused is None and minted.session_id == "persona_chat_x"
    return seen


def test_a_scoped_send_mints_an_owned_root(monkeypatch):
    scope = "b" * 64
    assert _mint(monkeypatch, Namespace(client_scope=scope))["client_scope"] == scope


def test_an_unscoped_send_mints_as_before(monkeypatch):
    # The in-process door and a bare CLI send carry no scope attribute at all.
    assert _mint(monkeypatch, Namespace())["client_scope"] is None
