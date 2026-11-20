"""A copy or an extra instance made through the instance verb belongs to the account that made it.

Row ``RT-INSTANCE-CREATE-MAKES-A-CHAT-WITH-NO-ACCOUNT`` (review w1118a.44 D3,
security): ``runtime.persona.instance.create`` and ``harness persona instance
create`` took no account scope, so the chat a new copy or instance minted
belonged to no account; Eternia's console read "saved conversation is not
linked to this account". Both doors now take ``client_scope`` (validated as
``runtime.agent.create`` validates it), stamp it on the chat all three mints
make, and echo it. A send under another account is refused.
"""

from __future__ import annotations

import json
from argparse import Namespace
from contextlib import closing

import pytest

from agent_runtime import serve_rpc
from agent_runtime.conversation_owner import session_client_scope
from tests.agent_runtime.test_serve_rpc_agent_create import (
    _instances,
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)

OWNER = "a" * 64
OTHER = "b" * 64


@pytest.fixture(autouse=True)
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


def _create(**params) -> dict:
    return serve_rpc.handle_request({
        "jsonrpc": "2.0", "id": "create", "method": "runtime.persona.instance.create",
        "params": {"persona_id": "qa", **params},
    })


def _owner_of(row: dict) -> str | None:
    """The owner stamped on the chat, read from the instance's own chat head
    (an independent copy keeps its chat in its own profile's head)."""
    from agent_runtime.persona_assignments import PersonaInstanceStore
    from hermes_cli.harness_parts.persona.lifecycle_commands import _instance_session_db

    instance = PersonaInstanceStore().get(row["persona_instance_id"])
    with closing(_instance_session_db(instance)) as db:
        return session_client_scope(db.get_session(row["session_id"]))


def _personas() -> set[str]:
    from agent_runtime.store import AgentStore

    return {p.id for p in AgentStore().list_all()}


def test_the_manifest_publishes_the_scope_so_a_client_can_refuse_an_older_runtime():
    # Mutation: drop "client_scope" from twin_params' row -> red.
    assert "client_scope" in serve_rpc.manifest()["params"]["runtime.persona.instance.create"]


def test_a_scoped_copy_opens_for_its_maker_and_refuses_another_account(qa_persona):
    # Mutation: drop ``client_scope=owner`` from the ``create_independent_agent``
    # call in ``lifecycle_commands._cmd_persona_instance_create`` -> red: the
    # copy's chat has no owner and the other account's send is not refused.
    reply = _create(display_name="Scout", independent_agent=True, client_message_id="copy-1",
                    client_scope=OWNER)
    row = reply["result"]
    assert row["client_scope"] == OWNER
    session = row["session_id"]
    assert _owner_of(row) == OWNER

    effects: list = []
    context = serve_rpc.RpcContext(spawn_chat_turn=lambda *a: effects.append(a))
    target = dict(persona_id=row["persona_id"], persona_instance_id=row["persona_instance_id"],
                  session_id=session, turn_request_id="t-other", message="Hello", client_scope=OTHER)
    refused = serve_rpc.handle_request(
        dict(jsonrpc="2.0", id="send", method="runtime.chat.message", params=target), context)
    assert refused["error"]["data"]["reason"] == "conversation_owner_changed", refused
    assert effects == []


def test_a_scoped_extra_instance_chat_belongs_to_its_maker(qa_persona):
    # Mutation: drop ``client_scope=owner`` from the ``add_instance`` call in
    # ``_cmd_persona_instance_create`` -> red: owner is None.
    row = _create(display_name="QA desk", add_instance=True, placement_id="qa_agent_0a1b2c3d",
                  client_scope=OWNER)["result"]
    assert row["client_scope"] == OWNER
    assert _owner_of(row) == OWNER


def test_a_scoped_operator_chat_belongs_to_its_maker(qa_persona):
    # Mutation: drop ``client_scope=client_scope`` from ``_durable_chat_root`` in
    # ``chat_binding.create_operator_chat`` -> red: owner is None.
    row = _create(display_name="QA Agent", client_scope=OWNER)["result"]
    assert row["client_scope"] == OWNER
    assert _owner_of(row) == OWNER


def test_an_unscoped_create_keeps_the_operator_behaviour(qa_persona):
    row = _create(display_name="Lone", independent_agent=True, client_message_id="copy-u")["result"]
    assert "client_scope" not in row
    assert _owner_of(row) is None


@pytest.mark.parametrize("owner", [None, "", "someone@example.test", "A" * 64, 123])
def test_a_malformed_scope_is_refused_before_any_write(qa_persona, owner):
    # Mutation: remove the ``request_client_scope`` check in
    # ``chat_verbs.instance_create.create_persona_instance`` -> red on ``None``:
    # a JSON null passes the argv door's check and an unowned copy is minted.
    before = (_personas(), set(_instances()))
    reply = _create(display_name="Scout", independent_agent=True, client_message_id="copy-bad",
                    client_scope=owner)
    assert reply["error"]["data"]["reason"] == "invalid_client_scope", reply
    assert (_personas(), set(_instances())) == before


def test_the_argv_verb_refuses_a_malformed_scope_before_any_write(qa_persona, capsys):
    # Mutation: remove the ``_valid_client_scope`` check at the top of
    # ``_cmd_persona_instance_create`` -> red: the copy's persona and profile
    # are provisioned before the chat mint trips on the digest.
    from hermes_cli.harness_parts.persona.lifecycle_commands import _cmd_persona_instance_create
    from hermes_cli.profiles import get_profile_dir

    before = (_personas(), set(_instances()))
    args = Namespace(
        json=True, persona_id="qa", title="Scout", display_name="Scout", requested_by="cli",
        independent_agent=True, add_instance=False, placement_id=None, session_id=None,
        workspace_id=None, realm_id=None, source_instance_id=None, client_message_id="copy-argv",
        client_scope="not-a-digest", coordinator_id=None,
    )
    assert _cmd_persona_instance_create(args) == 2
    assert json.loads(capsys.readouterr().out)["error_kind"] == "invalid_client_scope"
    assert (_personas(), set(_instances())) == before
    # Nothing was provisioned and then archived away, either.
    retired = get_profile_dir("agent-probe").parent / ".retired-independent-agents"
    assert not retired.exists()
