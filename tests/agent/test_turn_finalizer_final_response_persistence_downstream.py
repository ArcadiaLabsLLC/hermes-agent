"""Fork-owned tests moved out of ``tests/agent/test_turn_finalizer_final_response_persistence.py`` (seam Stage 5).

Same names, same bodies; the upstream file keeps only upstream's tests.
"""

from agent.turn_finalizer import finalize_turn

from tests.agent.test_turn_finalizer_final_response_persistence import (  # noqa: F401 — upstream names the moved tests use
    FakeAgent,
)


# Fork-owned: the per-call usage ledger feeds Mission Control's context budget.
# Upstream has no ledger, so these two have no upstream counterpart.
def test_turn_result_carries_the_per_call_usage_ledger(monkeypatch):
    """The ledger must survive into the turn result.

    Mission Control's context budget reads row 1 (the assembled context, tool
    schemas included). If it stops here, the budget silently falls back to a
    tool-blind estimate that reads ~4x low.
    """
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    agent = FakeAgent()
    agent.session_usage_ledger = [
        {"call_index": 1, "prompt_tokens": 42_733},
        {"call_index": 2, "prompt_tokens": 60_000},
    ]

    result = finalize_turn(
        agent,
        final_response="Done.",
        api_call_count=2,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "do it"}],
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message="do it",
        original_user_message="do it",
        _should_review_memory=False,
        _turn_exit_reason="completed",
    )

    assert [row["call_index"] for row in result["usage_ledger"]] == [1, 2]
    assert result["usage_ledger"][0]["prompt_tokens"] == 42_733


def test_turn_result_ledger_is_empty_for_agents_without_one(monkeypatch):
    """An agent predating the field must not crash finalization."""
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *_a, **_kw: [])
    agent = FakeAgent()  # FakeAgent has no session_usage_ledger

    result = finalize_turn(
        agent,
        final_response="Done.",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "do it"}],
        conversation_history=[],
        effective_task_id="task",
        turn_id="turn",
        user_message="do it",
        original_user_message="do it",
        _should_review_memory=False,
        _turn_exit_reason="completed",
    )

    assert result["usage_ledger"] == []
