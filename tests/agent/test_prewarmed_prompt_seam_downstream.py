"""Fork tests for the h-turn1 A3 seam in upstream `agent/conversation_loop.py::_restore_or_build_system_prompt`.

Kept out of upstream's own test file so the fork footprint does not grow; reuses its `_make_agent` fixture builder."""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.conversation_loop import _restore_or_build_system_prompt
from tests.agent.test_system_prompt_restore import _make_agent


# ---------------------------------------------------------------------------
# Fork seam (h-turn1 A3): a prompt the chat-actor prewarm built for this first turn
# ---------------------------------------------------------------------------


class TestPrewarmedPromptSeam:
    """``agent_runtime.prewarmed_system_prompt``'s stash, consumed by the one
    guarded block before the first-turn build. Killing mutation: delete that
    block (always build) -> ``test_a_matching_stash_is_adopted`` reds."""

    PREWARMED = "PREWARMED_PROMPT\nModel: test-model\nProvider: openrouter"

    def _agent(self, *, built_with="SURFACE", prompt=None):
        db = MagicMock()
        agent = _make_agent(session_db=db)
        vars(agent)["_prewarmed_system_prompt"] = (built_with, prompt or self.PREWARMED)
        return agent, db

    @staticmethod
    def _steps(agent):
        return [c.args[0].get("step") for c in agent.status_callback.call_args_list
                if c.args and isinstance(c.args[0], dict)]

    def test_a_matching_stash_is_adopted(self):
        agent, db = self._agent()
        _restore_or_build_system_prompt(agent, "SURFACE", [])

        agent._build_system_prompt.assert_not_called()
        assert agent._cached_system_prompt == self.PREWARMED
        assert "conversation_system_prompt_prewarmed" in self._steps(agent)
        assert "conversation_system_prompt_build" not in self._steps(agent)
        # h-turn1-conn: the adopted prompt's persist is held until the request is sent, then runs once.
        from agent_runtime.prewarmed_system_prompt import run_deferred_turn_persist

        db.update_system_prompt.assert_not_called()
        assert run_deferred_turn_persist(agent) is True
        db.update_system_prompt.assert_called_once_with(agent.session_id, self.PREWARMED)
        assert run_deferred_turn_persist(agent) is False, "held once, run once"
        assert "_prewarmed_system_prompt" not in vars(agent), "consumed exactly once"

    def test_a_stash_for_another_runtime_is_rebuilt(self):
        agent, _db = self._agent(prompt="PREWARMED\nModel: other-model\nProvider: openrouter")
        _restore_or_build_system_prompt(agent, "SURFACE", [])

        agent._build_system_prompt.assert_called_once_with("SURFACE")
        assert agent._cached_system_prompt == "BUILT_PROMPT"
        assert "_prewarmed_system_prompt" not in vars(agent)

    def test_a_stash_for_another_system_message_is_rebuilt(self):
        agent, _db = self._agent(built_with="OTHER")
        _restore_or_build_system_prompt(agent, "SURFACE", [])

        agent._build_system_prompt.assert_called_once_with("SURFACE")
        assert agent._cached_system_prompt == "BUILT_PROMPT"

    def test_a_mock_agent_never_reads_as_carrying_a_stash(self):
        agent = _make_agent(session_db=None)
        _restore_or_build_system_prompt(agent, None, [])
        agent._build_system_prompt.assert_called_once_with(None)
