"""A reply hermes stopped at its continuation limit is marked cut off on its turn.

Row RT-FU-A-REPLY-HERMES-STOPPED-AT-ITS-CONTINUATION-LIMIT-IS-MARKED-CUT-OFF-ON-ITS-TURN (review w1118a.66 D2).
Seen live 2026-11-20 (Eternia lane w1118a-qafu11, model fixture ``[[qa:cut_off …]]``): the model cut its reply
at the output limit on every call; hermes asked three continuations and ended the turn with the four parts
stitched, drawn as an ordinary finished reply. Reproduced whole here on the real loop (``held_model_turn``):
the model answers every call with text and ``finish_reason: length``.

The fact rides three places (``agent_runtime.reply_cut_off``): the terminal frame, the journal record, and the
agent's reply row on reload (persona history and the operator conversation). Killing mutations (reds in the
commit body): ``settle._cut_off_block`` answers {} -> the frame and the record red; ``_carry_cut_off`` returns
early -> the reload reds; ``reply_cut_off`` drops its error match -> the window-filled control reds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime.operator_channels.conversation import _conversation_contract
from agent_runtime.reply_cut_off import (
    CONTINUATION_LIMIT_ERROR,
    CUT_OFF_CAUSES,
    CUT_OFF_CONTINUATION_LIMIT,
    CUT_OFF_KEY,
    reply_cut_off,
)
from tests.agent_runtime.held_model_turn import HeldModel, operator_call, operator_params, operator_turn
from tests.agent_runtime.test_serve_rpc_open_chat import (  # placed_agent / qa_persona are fixtures
    PERSONA, WORKSPACE, _call, placed_agent, qa_persona,
)
from tests.agent_runtime.held_model_turn import OWNER

pytestmark = pytest.mark.timeout(180)


@pytest.fixture(autouse=True)
def chat_head(monkeypatch, isolate_agent_runtime_root):
    from hermes_constants import get_hermes_home

    monkeypatch.setenv("HERMES_HEAD_HOME", str(get_hermes_home()))


@pytest.fixture
def model():
    from hermes_constants import get_hermes_home

    held = HeldModel()
    held.hold = False
    held.configure(get_hermes_home())
    yield held
    held.close()


def _new_chat(placed) -> tuple[str, str]:
    instance = placed["persona_instance_id"]
    root = _call(dict(persona_id=PERSONA, persona_instance_id=instance, new_session=True,
                      idempotency_key="chat-1", client_scope=OWNER))["result"]["session_id"]
    return instance, root


def _reloaded_agent_rows(instance: str, root: str) -> tuple[dict, dict]:
    """The agent's reply row on reload: the persona history row and the operator conversation message."""

    history = operator_call("read", operator_params(instance, root, None, persona=PERSONA,
                                                    workspace=WORKSPACE))["result"]
    conversation = _conversation_contract(
        channel_id="channel-1", persona_id=PERSONA, persona_instance_id=instance, session_id=root, goal_id=None,
        title="Chat", state="idle", history=history, trace=None)
    [row] = [m for m in history["messages"] if str(m["role"]) == "agent"]
    [message] = [m for m in conversation["messages"] if str(m["role"]) == "agent"]
    return row, message


def _record(root: str, cmid: str) -> dict:
    from agent_runtime.mission_chat_turns import mission_chat_turn_records

    [record] = [r for r in mission_chat_turn_records(session_id=root) if r.get("client_message_id") == cmid]
    return record


def test_a_reply_stopped_at_the_continuation_limit_is_marked_cut_off(placed_agent, model):
    instance, root = _new_chat(placed_agent)
    parts = iter(f"part {n} of a long answer. " for n in range(1, 10))
    model.reply = lambda body: (next(parts), "length")

    _code, payload = operator_turn(instance, root, "msg-1", "Write the long essay.").join(120)

    assert len(model.requests) == 4  # the first call and three continuations, as seen live
    assert payload["reply"].startswith("part 1 of a long answer."), payload["reply"]
    assert "part 4" in payload["reply"]  # the stitched reply, with no words added to it
    assert payload[CUT_OFF_KEY] == CUT_OFF_CONTINUATION_LIMIT  # the terminal frame
    assert _record(root, "msg-1")[CUT_OFF_KEY] == CUT_OFF_CONTINUATION_LIMIT  # the turn's record
    row, message = _reloaded_agent_rows(instance, root)
    assert row["text"] == payload["reply"]
    assert (row[CUT_OFF_KEY], message[CUT_OFF_KEY]) == (CUT_OFF_CONTINUATION_LIMIT,) * 2  # after a reload


def test_an_ordinary_reply_carries_no_cut_off(placed_agent, model):
    instance, root = _new_chat(placed_agent)

    _code, payload = operator_turn(instance, root, "msg-1", "Hello.").join(120)

    assert payload["reply"] == "Thanks, noted."
    assert CUT_OFF_KEY not in payload and CUT_OFF_KEY not in _record(root, "msg-1")
    row, message = _reloaded_agent_rows(instance, root)
    assert CUT_OFF_KEY not in row and CUT_OFF_KEY not in message


def test_only_the_continuation_limit_exit_is_a_cut_off():
    """The window-filled exit and a cut tool call already say so in their reply: no field."""

    limit = {"partial": True, "failure_reason": "truncated", "error": CONTINUATION_LIMIT_ERROR}
    assert reply_cut_off(limit) == CUT_OFF_CONTINUATION_LIMIT
    window = {**limit, "error": "Prompt used 120000 of 128000 context tokens; no room to answer"}
    assert reply_cut_off(window) is None
    assert reply_cut_off({**limit, "partial": False}) is None
    assert reply_cut_off({**limit, "failure_reason": "timeout"}) is None
    assert reply_cut_off(None) is None


def test_the_cut_off_field_eternia_mirrors_is_the_runtimes():
    """The producer of Eternia's mirror (``tool/test_quality/hermes_mirrors.json``): the field and its causes.
    Mutation: add a cause to ``CUT_OFF_CAUSES`` -> red."""

    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "reply_cut_off_v1.json"
    assert json.loads(fixture.read_text(encoding="utf-8")) == {
        "field": CUT_OFF_KEY, "causes": list(CUT_OFF_CAUSES),
        "carried_on": ["mission.chat.message terminal frame", "persona history agent reply row",
                       "operator conversation agent message"]}
