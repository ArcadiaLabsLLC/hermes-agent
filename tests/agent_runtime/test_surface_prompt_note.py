"""RT-SURFACE-INSTRUCTIONS-FROZEN-AT-A-CHATS-FIRST-TURN: each turn's surface prompt reaches the model.

A two-turn persona chat through ``GPTPersonaRuntime.mission_chat_reply``. The runner stands in for
the profile runner around the parts that decide what the model reads, which stay upstream's own:
the agent-ready hook fires first (as ``profile_runner.execute`` does), then upstream's
``_restore_or_build_system_prompt`` on a real ``SessionDB`` restores the stored first-turn prompt,
and ``_merge_gateway_notes`` reads the one-shot note channel into the turn's ``api_content``.

Killing mutation (watched red): ``persona_runtime`` passing ``agent_ready_callback`` through
unwrapped (no ``with_surface_prompt_note``) -> turn 2's model input still names draft-1.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_runtime.persona_runtime import GPTPersonaRuntime
from agent_runtime.profile_runner import AgentRunResult
from agent_runtime.surface_prompt_note import NOTE_OPEN
from hermes_state import SessionDB
from tests.agent_runtime.persona_samples import sample_personas

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")

SESSION = "surface-note-chat"
DRAFT_1 = "Optional new-panel draft: draft-1, revision 1"
DRAFT_2 = "Optional new-panel draft: draft-2, revision 1"


@pytest.fixture(autouse=True)
def _bundled_profiles_exist(bundled_persona_profiles):
    return bundled_persona_profiles


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes-home"))
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "runtime"))
    session_db = SessionDB(db_path=tmp_path / "state.db")
    session_db.create_session(SESSION, source="tool", model="gpt-5.5")
    yield session_db
    session_db.close()


def _turn_agent(db) -> MagicMock:
    """A fresh per-turn agent whose prompt build embeds the caller's system message, as upstream's does."""
    agent = MagicMock()
    agent._cached_system_prompt = None
    agent.session_id = SESSION
    agent.model, agent.provider = "gpt-5.5", "openai-codex"
    agent.platform = "tool"
    agent.pass_session_id = False
    agent.session_start = None
    agent._bot_chat_timeless_prompt = False
    agent._persist_disabled = False
    agent._use_prompt_caching = False
    agent._session_db = db
    agent._platform_hint_overrides = None
    agent._surface_switch_note = ""
    agent._gateway_turn_context_notes = ""
    agent._skills_index_note = ""
    agent.enabled_toolsets = agent.disabled_toolsets = None
    agent._build_system_prompt = MagicMock(side_effect=lambda sm: f"You are Hermes Agent.\n\n{sm}")
    return agent


class UpstreamShapedRunner:
    """Records, per turn, the system prompt sent and the user turn's wire text."""

    def __init__(self, db):
        self.db = db
        self.turns: list[dict] = []

    def run(self, request):
        from agent.conversation_loop import _restore_or_build_system_prompt
        from agent.turn_context import _merge_gateway_notes

        agent = _turn_agent(self.db)
        if request.agent_ready_callback is not None:
            request.agent_ready_callback(agent)
        history = list(request.conversation_history or [])
        _restore_or_build_system_prompt(agent, request.system_message, history)
        notes = _merge_gateway_notes(agent, [], -1, "")
        wire_user = f"{request.user_message}\n\n{notes}" if notes else request.user_message
        self.turns.append({"system_prompt": agent._cached_system_prompt, "user": wire_user})
        return AgentRunResult(final_response="ok", session_id=SESSION, provider="openai-codex",
                              model="gpt-5.5", base_url=None, messages=[])


def _chat(db, surfaces: list[str]) -> UpstreamShapedRunner:
    runner = UpstreamShapedRunner(db)
    runtime = GPTPersonaRuntime(default_provider="openai-codex", default_model="gpt-5.5", agent_runner=runner)
    persona = next(p for p in sample_personas() if p.id == "neko_supervisor")
    history: list[dict] = []
    for index, surface in enumerate(surfaces):
        message = f"request {index + 1}"
        runtime.mission_chat_reply(
            persona, message, session_id=SESSION, permission_session_id=SESSION,
            turn_id=f"turn-{index + 1}", surface_prompt=surface, conversation_history=list(history),
        )
        sent = runner.turns[-1]["user"]
        # The persisted user row: what the operator typed, with the wire bytes in the sidecar.
        history.append({"role": "user", "content": message, "api_content": sent if sent != message else None})
        history.append({"role": "assistant", "content": "ok"})
    return runner


def test_a_changed_surface_prompt_reaches_the_model_on_turn_two(db):
    runner = _chat(db, [DRAFT_1, DRAFT_2])
    first, second = runner.turns

    assert DRAFT_1 in first["system_prompt"]
    assert NOTE_OPEN not in first["user"]
    # Turn 2 reads draft-2, from its tail.
    assert DRAFT_2 in second["user"]
    assert second["user"].index("request 2") < second["user"].index(DRAFT_2)


def test_the_stored_system_prompt_is_unchanged(db):
    runner = _chat(db, [DRAFT_1, DRAFT_2])
    first, second = runner.turns

    assert second["system_prompt"] == first["system_prompt"]
    assert db.get_session(SESSION)["system_prompt"] == first["system_prompt"]


def test_an_unchanged_surface_prompt_adds_nothing(db):
    runner = _chat(db, [DRAFT_1, DRAFT_1, DRAFT_2, DRAFT_2, DRAFT_1])
    users = [turn["user"] for turn in runner.turns]

    assert NOTE_OPEN not in users[1]  # same as the stored prompt
    assert DRAFT_2 in users[2]
    assert NOTE_OPEN not in users[3]  # same as the note turn 3 already carries in the transcript
    assert DRAFT_1 in users[4] and NOTE_OPEN in users[4]  # back to the first one: told again
