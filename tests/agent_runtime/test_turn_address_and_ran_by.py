"""RT-NAMING-ADDRESS-VALUE + RT-TURN-EDITION-STAMP: one typed address, and every turn record prints it
beside the edition / commit / code tree that ran it (naming map, § The address and ruling 9)."""

from __future__ import annotations

import pytest

from agent_runtime import address as addr
from agent_runtime import run_provenance
from agent_runtime.mission_chat_turns import (
    MissionChatTurnPersistOutcome,
    mission_chat_turn_record,
    transition_mission_chat_turn,
)
from agent_runtime.mission_chat_turns.records import safe_ran_by

TURN = "machine:mach_ab12/namespace:acct-0123456789abcdef/persona-instance:personainst_neko/chat:20261025_x:1/turn:t_9"


@pytest.mark.parametrize("text", [
    TURN,
    "machine:mach_ab12/namespace:base",
    "realm:realm_1/realm-workspace:ws_default/repo-slot:launcher",
    "machine:mach_ab12/namespace:stagec-smoke/slot-folder:ws_default/launcher",
])
def test_print_and_parse_are_one_format(text):
    parsed = addr.parse(text)
    assert str(parsed) == text
    assert addr.parse(str(parsed)) == parsed


def test_each_segment_is_read_by_its_kind():
    parsed = addr.parse(TURN)
    assert parsed.get("chat") == "20261025_x:1"  # only the first ':' splits kind from id
    assert parsed.get(addr.Kind.TURN) == "t_9"
    assert addr.parse("machine:m/namespace:n/slot-folder:ws/slot").get("slot-folder") == "ws/slot"


@pytest.mark.parametrize("text", [
    "personainst_neko",                          # a bare id names nothing
    "chat:c/turn:t",                             # not a prefix of any chain
    "machine:m/persona-instance:p",              # a segment skipped
    "machine:m/namespace:n/repo-slot:x",         # two chains mixed
    "machine:m/namespace:n/slot-folder:ws",      # slot-folder is a pair
    "machine:/namespace:n",                      # an empty id
    "machine:m n",                               # whitespace in an id
    "edition:developer",                         # editions are never a segment (ruling 9)
    "",
])
def test_what_is_not_an_address_refuses(text):
    with pytest.raises(addr.AddressError):
        addr.parse(text)


def test_a_turn_record_carries_its_address_and_ran_by_from_its_first_write(monkeypatch):
    monkeypatch.setattr(run_provenance, "_cached", {"edition": "developer", "commit": "a" * 40, "code_tree": "b" * 40})
    transition_mission_chat_turn(
        session_id="chat_root_1", client_message_id="cm_1", turn_id="turn_1", state="pending",
        metadata={"persona_instance_id": "personainst_neko", "root_chat_session_id": "chat_root_1"})
    record = mission_chat_turn_record(session_id="chat_root_1", client_message_id="cm_1")
    parsed = addr.parse(record["address"])
    assert parsed.get("persona-instance") == "personainst_neko"
    assert parsed.get("chat") == "chat_root_1" and parsed.get("turn") == "turn_1"
    assert parsed.get("machine").startswith("mach_") and parsed.get("namespace")
    assert record["ran_by"] == {"edition": "developer", "commit": "a" * 40, "code_tree": "b" * 40}
    # A later write by another build keeps the stamp of the process that STARTED the turn.
    monkeypatch.setattr(run_provenance, "_cached", {"edition": "bundled", "commit": "c" * 40, "code_tree": None})
    outcome = transition_mission_chat_turn(session_id="chat_root_1", client_message_id="cm_1", turn_id="turn_1",
                                           state="executing", metadata={})
    assert outcome is MissionChatTurnPersistOutcome.PERSISTED  # the second write happened
    again = mission_chat_turn_record(session_id="chat_root_1", client_message_id="cm_1")
    assert again["state"] == "executing"
    assert again["address"] == record["address"] and again["ran_by"]["edition"] == "developer"


def test_ran_by_keeps_only_its_three_shapes():
    assert safe_ran_by({"edition": "bundled", "commit": "ABC", "code_tree": "0f", "x": 1}) == {
        "edition": "bundled", "commit": None, "code_tree": "0f"}
    assert safe_ran_by({"edition": "nightly"}) is None
