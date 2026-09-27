"""Fork-owned: a persona chat's commands share one container — ``_resolve_container_task_id``
returns the chat's tool-execution scope first (``agent_runtime.terminal_policy.chat_container_scope``,
lane FOOTPRINT-DROP 2026-09-27)."""

from __future__ import annotations

from agent_runtime.persona_chat_continuity import tool_execution_scope
from tools import terminal_tool


def test_chat_scope_wins_over_the_task_id():
    with tool_execution_scope("chat-root-abc"):
        assert terminal_tool._resolve_container_task_id("tui:sess-1") == "chat-root-abc"


def test_positive_control_outside_a_chat_the_task_id_rules():
    assert terminal_tool._resolve_container_task_id("tui:sess-1") != "chat-root-abc"
