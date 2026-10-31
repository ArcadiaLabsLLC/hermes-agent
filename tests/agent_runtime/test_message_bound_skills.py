"""Composer selections travel with their message; session queues keep their existing owner."""
import pytest

from agent_runtime.chat_turn import CHAT_MESSAGE_PARAMS, ChatTurnInvalid, normalize_chat_message
from agent_runtime.chat_verbs.queue_skill import require_loadable_turn_skills
from agent_runtime.queued_skills import pending_skills_for_next_turn, queue_skills_for_next_turn
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tests.agent_runtime.test_mission_chat_turn_context import _build
from tests.agent_runtime.test_mission_chat_serve_route import _parser
from tests.agent_runtime.test_skill_inspection import put_skill


def test_rpc_parser_and_context_keep_two_message_selections_separate(tmp_path):
    token = set_hermes_home_override(tmp_path)
    try:
        put_skill(tmp_path, "picked-a")
        put_skill(tmp_path, "picked-b")
        first = normalize_chat_message(dict(turn_request_id="turn-a", persona_id="dev",
            message="Review A", skills=["picked-a", "picked-a"]))
        second = normalize_chat_message(dict(turn_request_id="turn-b", persona_id="dev",
            message="Review B", skills=["picked-b"]))
        first_args, second_args = _parser().parse_args(first.argv), _parser().parse_args(second.argv)
        assert first_args.skills == ["picked-a"]
        assert second_args.skills == ["picked-b"]
        assert "skills" in CHAT_MESSAGE_PARAMS
        assert pending_skills_for_next_turn(persona_id="dev", session_id="chat-root-1") == []
        a = _build(requested_skills=first_args.skills)
        b = _build(requested_skills=second_args.skills)
        assert a.skills.loaded == ("harness-dev-delivery", "queued-skill", "picked-a")
        assert b.skills.loaded == ("harness-dev-delivery", "queued-skill", "picked-b")
        assert "picked-a" in a.skill_preload_prompt and "picked-b" not in a.skill_preload_prompt
        assert "picked-b" in b.skill_preload_prompt and "picked-a" not in b.skill_preload_prompt
    finally:
        reset_hermes_home_override(token)


def test_invalid_selection_refuses_before_consuming_the_session_queue(tmp_path):
    token = set_hermes_home_override(tmp_path)
    try:
        queue_skills_for_next_turn(persona_id="dev", session_id="chat-root-1", skills=["held"])
        with pytest.raises(ValueError, match="not loadable"):
            _build(requested_skills=["not-installed"])
        assert pending_skills_for_next_turn(persona_id="dev", session_id="chat-root-1") == ["held"]
        put_skill(tmp_path, "installed")
        assert require_loadable_turn_skills(["installed"]) == ["installed"]
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize("value", ["name", [""], [7], [None]])
def test_bad_skill_selection_is_refused_at_rpc_boundary(value):
    with pytest.raises(ChatTurnInvalid) as error:
        normalize_chat_message(dict(turn_request_id="t", persona_id="dev", message="Review", skills=value))
    assert error.value.reason == "skills_invalid"
