"""The operator-chat request's fork-measurable share stays under a token budget (lane h-slim-prompt).

Live inventory (dev persona ``personainst_dev_agent_8b319ebf``, gpt-launcher, 2026-10-06 17:05,
``agent.log`` ``API call #1`` + ``prompt_observability/ctx_111c95fca249ebf4.json``): a one-word
turn sent 26.5k-28.1k tokens. The table is in the lane's commit body; this file pins the three
parts the fork composes from code in this tree, built from the REAL sources, so growth in any
of them reds here instead of on the provider's meter:

* the eager tool wire — the dev persona's live eager set (the record's 25, less the three
  promoted ``launcher_qa`` tools whose text the server owns and the two bridge tools whose
  listing depends on the deferred catalog), from the real registry, measured as the wire
  carries it (``tools.downstream_schema.wire_tool_chars``: briefed, compact JSON);
* the fork's share of the system prompt — the identity block and the operative rules at the
  default (``lean_operative_rules`` off);
* the per-turn volatile tail — the capability account and wall-budget line every delivery
  repeats, which every turn then carries forward in history.

Tokens are upstream's chars/4 basis (``tools.tool_search_catalog.CHARS_PER_TOKEN``), the
basis of the S0 receipt; the venv ships no tokenizer.
"""

from __future__ import annotations

import math
import time
import types

import pytest

#: The record's eager tools, less the promoted MCP three (server-owned text) and the
#: ``tool_search`` / ``tool_call`` bridge (its listing is the deferred catalog, ruling R3).
DEV_EAGER_MEASURED = (
    "agent_chat_dispatches", "agent_chat_send", "browser_exec", "clarify", "delegate_task",
    "execute_code", "memory", "patch", "read_file", "search_files", "skill_manage",
    "skill_search", "skill_view", "skills_list", "terminal", "vision_analyze", "web_extract",
    "web_search", "write_file",
)
#: Anti-vacuity: tools whose absence would make the measurement meaningless.
MUST_MEASURE = frozenset({"agent_chat_send", "agent_chat_dispatches", "terminal", "read_file",
                          "search_files", "delegate_task", "memory", "skill_manage"})

#: Budgets (chars/4 tokens), measured 2026-10-06 on this tree + ~5% headroom: tools 5,815
#: (``vision_analyze`` is check-gated off offline; live it adds 182), system share 2,527, tail 224.
TOOLS_BUDGET = 6_100
SYSTEM_SHARE_BUDGET = 2_650
TAIL_BUDGET = 240
TOTAL_BUDGET = 8_990


def _tokens(chars: int) -> int:
    from tools.tool_search_catalog import CHARS_PER_TOKEN

    return math.ceil(chars / CHARS_PER_TOKEN)


def _tool_wire_tokens() -> tuple[int, dict[str, int]]:
    import model_tools  # noqa: F401 — registers the built-in tools
    from tools.downstream_schema import wire_tool_chars
    from tools.registry import registry
    from tools.tool_search_downstream import tool_describe_schema

    defs = registry.get_definitions(set(DEV_EAGER_MEASURED), quiet=True) + [tool_describe_schema()]
    chars = wire_tool_chars(defs)
    missing = MUST_MEASURE - set(chars)
    assert not missing, f"the registry did not produce {sorted(missing)}; the pin would measure nothing"
    return _tokens(sum(chars.values())), chars


def _system_share_tokens() -> int:
    from agent_runtime.mission_chat_prompts import (
        _mission_chat_identity_prompt,
        _mission_chat_operative_rules,
    )
    from tests.agent_runtime.persona_samples import sample_personas

    dev = next(p for p in sample_personas() if p.id == "dev")
    return _tokens(len(_mission_chat_identity_prompt(dev)) + len(_mission_chat_operative_rules()))


def _tail_tokens() -> int:
    from agent_runtime.permission_modes import PERMISSION_MODE_UNBOUNDED
    from agent_runtime.runtime_config import TerminalEnvelopeConfig
    from agent_runtime.runtime_hud import render_capability_block, resolve_capability_block
    from agent_runtime.terminal_envelope import LANE_MISSION_CHAT, explain_terminal_envelope
    from agent_runtime.turn_budget import TurnWallBudget, render_turn_budget_line

    capability = render_capability_block(resolve_capability_block(
        permission_mode=PERMISSION_MODE_UNBOUNDED,
        permission_source="runtime_default",
        envelope=explain_terminal_envelope(
            role="dev", lane=LANE_MISSION_CHAT,
            cfg=types.SimpleNamespace(terminal_envelope=TerminalEnvelopeConfig(grants={})),
            permission_mode=PERMISSION_MODE_UNBOUNDED,
        ),
    ))
    now = time.time()
    budget = render_turn_budget_line(TurnWallBudget(total_seconds=1800.0, deadline_epoch=now + 1800.0), now=now)
    assert capability and budget, "the tail rendered nothing; the pin would measure nothing"
    return _tokens(len(capability) + 1 + len(budget))


@pytest.fixture
def default_root_config(tmp_path, monkeypatch):
    from agent_runtime import config as cfgpkg
    from tests._downstream.split_package_source import patch_where_bound

    path = tmp_path / "config.yaml"
    path.write_text("agent_runtime:\n  mission_chat: {}\n", encoding="utf-8")
    patch_where_bound(monkeypatch, cfgpkg, "harness_root_config_path", lambda: path)
    return path


def test_the_operator_chat_request_stays_under_its_token_budget(default_root_config):
    """Positive control (CHANGE commit): plant 2,000 chars of prose in ``agent_chat_send``'s
    ``message`` parameter description -> the tools and total assertions red."""

    tools, per_tool = _tool_wire_tokens()
    system = _system_share_tokens()
    tail = _tail_tokens()
    parts = (f"tools={tools} (largest: {sorted(per_tool.items(), key=lambda kv: -kv[1])[:5]}) "
             f"system_share={system} tail={tail}")
    assert tools <= TOOLS_BUDGET, parts
    assert system <= SYSTEM_SHARE_BUDGET, parts
    assert tail <= TAIL_BUDGET, parts
    assert tools + system + tail <= TOTAL_BUDGET, parts
