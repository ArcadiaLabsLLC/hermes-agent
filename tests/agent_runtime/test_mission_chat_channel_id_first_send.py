"""A first send that names the operator CHANNEL id opens the instance's root.

Live 2026-10-02 (launcher lane w6-chat): on a fresh seeded instance, the first
send before "new chat" carried the conversation's thread id
``profile:base::personainst_profile_base`` as its session and was refused
"unknown explicit persona chat root". A channel id is hermes's own; its tail
is the instance (no chat yet) or the session.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.operator_channels.instances import split_operator_channel_id
from hermes_cli.harness_parts.persona import chat_turn_message
from tests.agent_runtime.test_mission_chat_send_refused_guard_events import (
    _canonical_db,
    _chat_lane,
    _refused_rows,
    _send_args,
)

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _last_json(capsys) -> dict:
    out = capsys.readouterr().out
    decoder, index, last = json.JSONDecoder(), 0, None
    while (start := out.find("{", index)) != -1:
        last, index = decoder.raw_decode(out, start)
    assert last is not None, out
    return last


def test_a_first_send_to_an_instance_channel_opens_its_root(monkeypatch, capsys, isolate_agent_runtime_root):
    db = _canonical_db()
    _chat_lane(monkeypatch, db)

    code = chat_turn_message._cmd_mission_chat_message(
        _send_args(
            persona_id="dev",
            persona_instance_id=None,
            session_id="dev::personainst_dev",
            client_message_id="cm-channel-1",
        )
    )
    reply = _last_json(capsys)

    assert code == 0, reply
    assert reply["ok"] is True
    assert reply["persona_instance_id"] == "personainst_dev"
    root = PersonaInstanceStore().get("personainst_dev").default_chat_session_id
    assert root and reply["session_id"] == root
    assert _refused_rows() == []


def test_a_channel_of_another_persona_is_still_refused(monkeypatch, capsys, isolate_agent_runtime_root):
    db = _canonical_db()
    _chat_lane(monkeypatch, db)

    code = chat_turn_message._cmd_mission_chat_message(
        _send_args(
            persona_id="dev",
            persona_instance_id=None,
            session_id="qa::personainst_qa",
            client_message_id="cm-channel-2",
        )
    )
    reply = _last_json(capsys)

    assert code == 2
    assert reply["error_kind"] == "unknown_chat_session"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("profile:base::personainst_profile_base", ("profile:base", "personainst_profile_base")),
        ("dev::persona_chat_personainst_dev_abc", ("dev", "persona_chat_personainst_dev_abc")),
        ("persona_chat_personainst_dev_abc", None),
        ("dev::", None),
        ("a::b::c", None),
        (None, None),
    ],
)
def test_split_operator_channel_id(value, expected):
    assert split_operator_channel_id(value) == expected
