"""RT-FU-ETERNIAS-AGENT-CALL-CAN-USE-HERMES-OWN-INTERRUPT-RULES: a message that talked over the agent says so.

``runtime.chat.message`` takes ``interrupted: true`` (argv ``--interrupted``), the turn runner hands it
to ``mission_chat_reply``, and the turn stages hermes's own ``SPEECH_INTERRUPTED_NOTE`` on the one-shot
note channel, ahead of the fork's surface-prompt note (the gateway's ``surface_note`` puts the
interruption first among its own notes too). A send queued behind a busy chat keeps the flag. Each hop is
pinned through its real entry point; the model input is read as upstream's own ``_merge_gateway_notes``
builds it (``tests/agent_runtime/test_surface_prompt_note.py``'s runner).

Killing mutations (each watched red):
* ``normalize_chat_message`` without the ``--interrupted`` append -> the lowering case;
* ``("interrupted", "--interrupted", "flag")`` dropped from ``SEND_FLAGS`` -> the round trip
  (``test_mission_chat_serve_route``) and the route case;
* ``run.py`` not passing ``interrupted=`` -> the production-lane case;
* ``persona_runtime`` without ``with_interruption_note`` -> the model-input cases;
* the two wrappers composed the other way round -> the ordering case.
"""

from __future__ import annotations

import pytest

from agent_runtime.chat_turn import ChatTurnInvalid, normalize_chat_message
from agent_runtime.persona_runtime import GPTPersonaRuntime
from agent_runtime.surface_prompt_note import NOTE_OPEN
from agent_runtime.turn_interruption_note import with_interruption_note
from tests.agent_runtime.persona_samples import sample_personas
from tests.agent_runtime.test_chat_turn_redo import _send, lane  # noqa: F401  (the production-lane fixture)
from tests.agent_runtime.test_surface_prompt_note import SESSION, UpstreamShapedRunner, db  # noqa: F401
from tools.tts_streaming import SPEECH_INTERRUPTED_NOTE

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

SEND = {"turn_request_id": "t-1", "persona_id": "neko", "message": "wait, make it shorter"}


@pytest.fixture(autouse=True)
def _bundled_profiles_exist(bundled_persona_profiles):
    return bundled_persona_profiles


def test_the_send_lowers_interrupted_to_its_flag_and_refuses_anything_but_a_boolean():
    assert normalize_chat_message({**SEND, "interrupted": True}).argv.count("--interrupted") == 1
    assert "--interrupted" not in normalize_chat_message(SEND).argv
    assert "--interrupted" not in normalize_chat_message({**SEND, "interrupted": False}).argv
    assert "--interrupted" not in normalize_chat_message({**SEND, "interrupted": None}).argv
    for bad in ("yes", 1, "true", [True]):
        with pytest.raises(ChatTurnInvalid) as refused:
            normalize_chat_message({**SEND, "interrupted": bad})
        assert refused.value.reason == "interrupted_invalid"


def test_the_turn_parser_reads_what_the_send_lowers_and_the_serve_route_forwards_it():
    from hermes_cli.harness_parts.persona import chat_serve_route
    from tests.agent_runtime.test_mission_chat_serve_route import _parser

    parser = _parser()  # hermes's whole command parser, as the turn worker builds it
    lowered = parser.parse_args(normalize_chat_message({**SEND, "interrupted": True}).argv)
    assert lowered.interrupted is True
    assert parser.parse_args(normalize_chat_message(SEND).argv).interrupted is False
    assert parser.parse_args(chat_serve_route.send_argv(lowered)).interrupted is True


@pytest.mark.parametrize("interrupted", [True, False])
def test_the_production_turn_hands_interrupted_to_the_runtime(lane, capsys, isolate_agent_runtime_root,  # noqa: F811
                                                              interrupted):
    code, _answer = _send(lane, capsys, "cm-1", interrupted=interrupted)
    assert code == 0, _answer
    assert lane.calls[-1]["interrupted"] is interrupted


def test_a_send_queued_behind_a_busy_chat_keeps_the_flag():
    """A busy root queues the send's args and runs them later (``chat_root_send_runner._turn_args``)."""
    import json
    from types import SimpleNamespace

    from agent_runtime.chat_root_send_queue import persistable_args
    from agent_runtime.chat_root_send_runner import _turn_args

    stored = json.loads(json.dumps(persistable_args(SimpleNamespace(message="wait", interrupted=True))))
    entry = SimpleNamespace(args=stored, root_session_id="root-1", client_message_id="cm-1")
    assert _turn_args(entry, stream=False).interrupted is True


def test_a_send_that_never_heard_of_the_flag_is_not_interrupted(lane, capsys, isolate_agent_runtime_root):  # noqa: F811
    code, _answer = _send(lane, capsys, "cm-1")
    assert code == 0, _answer
    assert lane.calls[-1]["interrupted"] is False


def _chat(db, turns: list[dict]) -> list[str]:  # noqa: F811
    """A persona chat turn by turn; each turn's model-bound user text as upstream builds it."""
    runner = UpstreamShapedRunner(db)
    runtime = GPTPersonaRuntime(default_provider="openai-codex", default_model="gpt-5.5", agent_runner=runner)
    persona = next(p for p in sample_personas() if p.id == "neko_supervisor")
    history: list[dict] = []
    for index, turn in enumerate(turns):
        message = f"request {index + 1}"
        runtime.mission_chat_reply(
            persona, message, session_id=SESSION, permission_session_id=SESSION, turn_id=f"turn-{index + 1}",
            surface_prompt=turn.get("surface", ""), interrupted=turn.get("interrupted", False),
            conversation_history=list(history),
        )
        sent = runner.turns[-1]["user"]
        history.append({"role": "user", "content": message, "api_content": sent if sent != message else None})
        history.append({"role": "assistant", "content": "ok"})
    return [turn["user"] for turn in runner.turns]


def test_the_interrupting_turn_tells_the_model_and_no_other_turn_does(db):  # noqa: F811
    users = _chat(db, [{}, {"interrupted": True}, {}])
    assert SPEECH_INTERRUPTED_NOTE not in users[0]
    assert users[1].index("request 2") < users[1].index(SPEECH_INTERRUPTED_NOTE)
    assert users[1].count(SPEECH_INTERRUPTED_NOTE) == 1
    assert SPEECH_INTERRUPTED_NOTE not in users[2]


def test_a_first_turn_can_be_interrupting_too(db):  # noqa: F811
    """No history means no surface note, but a call's first reply can still be talked over."""
    users = _chat(db, [{"interrupted": True}])
    assert SPEECH_INTERRUPTED_NOTE in users[0]


def test_the_interruption_note_comes_before_a_surface_note_on_the_same_turn(db):  # noqa: F811
    users = _chat(db, [{"surface": "draft-1"}, {"surface": "draft-2", "interrupted": True}])
    assert NOTE_OPEN in users[1]
    assert users[1].index(SPEECH_INTERRUPTED_NOTE) < users[1].index(NOTE_OPEN)


def test_the_wrapper_is_the_callback_itself_when_nothing_was_interrupted():
    def callback(agent):
        return None

    assert with_interruption_note(callback, interrupted=False) is callback
    assert with_interruption_note(None, interrupted=False) is None


def test_the_wrapper_stages_the_note_before_the_callback_runs():
    class Agent:
        _gateway_turn_context_notes = ""

    seen: list[str] = []
    agent = Agent()
    ready = with_interruption_note(lambda a: seen.append(a._gateway_turn_context_notes), interrupted=True)
    assert ready(agent) is None
    assert seen == [SPEECH_INTERRUPTED_NOTE]
    assert with_interruption_note(None, interrupted=True)(Agent()) is None
