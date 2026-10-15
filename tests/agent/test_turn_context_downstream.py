"""Fork-owned half of ``tests/agent/test_turn_context.py``.

The reused-durable-history persist boundary: a caller that already persisted this
turn's user row passes it as the history tail, so the persist index sits past it.
Upstream's autouse ``_stub_runtime_main`` and its ``_FakeAgent`` / ``_build`` helpers
are imported by name.
"""

from __future__ import annotations

from tests.agent.test_turn_context import (  # noqa: F401 — upstream names the moved test uses
    _FakeAgent,
    _build,
    _stub_runtime_main,
)


def test_reused_durable_user_history_sets_persist_boundary_after_history():
    agent = _FakeAgent()
    history = [{"role": "user", "content": "hello"}]
    ctx = _build(agent, conversation_history=history, reuse_current_user_message=True)
    assert ctx.messages == history
    assert agent._persist_user_message_idx == len(history)
