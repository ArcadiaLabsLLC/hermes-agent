"""RT-CHAT-HEAD-CH1 — which ``state.db`` ``session_search`` searches during a Mission Control turn.

``docs/agent-runtime-harness/planned/chat-head-per-profile-2026-10-26.md`` §1. TODAY's behaviour,
pinned at runtime so the per-profile head (CH2) lands against a recorded red: the turn's SessionDB is
the chat head (``HERMES_HEAD_HOME`` = ``profiles/base``) whatever the agent's own profile, the runner
hands that handle to the agent, and recall searches it — so one agent's turn finds another agent's
chat (cross-agent recall). CH2 flips the last assertions: the turn searches its agent's profile store.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.inline_tool_executors import _session_search
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_runtime import GPTPersonaRuntime
from run_agent import AIAgent
from tests.agent_runtime.test_persona_runtime_fake import FakeAIAgent, sample_personas

pytestmark = pytest.mark.timeout(60)


@pytest.fixture
def namespace(tmp_path, monkeypatch, bundled_persona_profiles):
    """The head is ``profiles/base``; ``qa`` is the agent's own (live) profile, and the turn is qa's."""
    from hermes_cli.profiles import get_profile_dir

    own = get_profile_dir("qa")
    base = own.parent / "base"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_AGENT_RUNTIME_ROOT", str(tmp_path / "agent-runtime"))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(base))
    return base, own


def test_a_mission_control_turn_recalls_from_the_chat_head_so_it_reaches_every_agents_chats(namespace):
    base, own = namespace
    turn_db = default_persona_session_db()
    try:
        assert Path(turn_db.db_path).resolve() == (base / "state.db").resolve()
        # Agent bob's chat lives in the same head store qa's turn writes.
        turn_db.create_session("bob_chat", "agent_runtime_persona_chat")
        turn_db.append_message("bob_chat", role="user", content="the pineapple ledger is bob's")

        FakeAIAgent.instances.clear()
        qa = next(persona for persona in sample_personas() if persona.id == "qa")
        GPTPersonaRuntime(default_provider="openai-codex", default_model="gpt-5.5",
                          session_db=turn_db, agent_factory=FakeAIAgent,
                          ).mission_chat_reply(qa, "hi", permission_session_id="qa_chat")
        handed = FakeAIAgent.instances[0].kwargs["session_db"]
        assert handed is turn_db, "the runner hands the agent the turn's own chat-head handle"

        agent = SimpleNamespace(_persist_disabled=False, _session_db=handed, session_id="qa_chat")
        agent._get_session_db_for_recall = AIAgent._get_session_db_for_recall.__get__(agent)
        found = json.loads(_session_search(agent, {"query": "pineapple"}, None))
        hits = {row.get("session_id") for row in found.get("results", [])}
        assert "bob_chat" in hits, f"recall from qa's turn did not reach bob's chat: {found}"
        assert Path(handed.db_path).resolve() != (own / "state.db").resolve()
    finally:
        turn_db.close()
