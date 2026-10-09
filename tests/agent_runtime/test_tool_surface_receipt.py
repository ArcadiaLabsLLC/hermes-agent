"""The preview and the factory are one answer: the measured 45-vs-27 cannot recur.

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md`` §0
and §3 slice 4. ``persona tool-diff`` reported 45 names for Neko while the turn shipped 27 — the
preview never ran the persona's defer, availability or the bridge. Now the preview
(``inspect_commands._preview_tool_surface``, on the chat-lane bundle's ``tool_contract``) and the
factory (the tool form's owner, ``chat_lane_tool_form.apply_chat_lane_defer``) call one function
on one input; this test is the join itself.
"""

from __future__ import annotations

from types import SimpleNamespace

from tests.agent_runtime.test_chat_lane_defer import NEKO_DEFER
from tests.agent_runtime.test_tool_surface import ENABLED, harness_lane  # noqa: F401 - fixture

_BLOCK = ("skill_manage",)


def test_the_preview_and_the_factory_agree_on_one_input(harness_lane, monkeypatch):  # noqa: F811
    import agent_runtime.chat_lane_bundle as CLB
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer
    from agent_runtime.tool_surface import AGENT_SURFACE_ATTR
    from hermes_cli.harness_parts.persona import inspect_commands

    contract = {"enabled_toolsets": list(ENABLED), "blocked_tool_names": list(_BLOCK),
                "chat_lane_defer_tools": sorted(NEKO_DEFER)}
    bundle = SimpleNamespace(permission_mode="unbounded", tool_contract=lambda: dict(contract),
                             defer_tools=tuple(sorted(NEKO_DEFER)),
                             admission=SimpleNamespace(server_names=("launcher_qa",)))
    monkeypatch.setattr(CLB, "chat_lane_bundle", lambda persona, *, session_id: bundle)

    agent = harness_lane.build_agent()
    apply_chat_lane_defer(agent, contract["chat_lane_defer_tools"], blocked=contract["blocked_tool_names"])
    factory = getattr(agent, AGENT_SURFACE_ATTR)
    preview = inspect_commands._preview_tool_surface(
        SimpleNamespace(id="neko_supervisor"), SimpleNamespace(session_id=None), "unbounded", {})

    assert preview["contract_source"] == "chat_lane_bundle"
    extra = sorted(set(preview["eager"]) - set(factory["eager"]))
    missing = sorted(set(factory["eager"]) - set(preview["eager"]))
    assert preview["eager"] == factory["eager"], f"extra={extra} missing={missing}"
    assert preview["resolution_id"] == factory["resolution_id"]
    # Anti-vacuity: the factory's eager set IS the wire it published (block pruned), and the
    # persona's defer took names off it — the join compares two non-trivial answers.
    assert set(factory["eager"]) | set(factory["bridge"]) == {d["function"]["name"] for d in agent.tools}
    assert factory["deferred"]["browser_vault_list"]["reason"] == "persona_defer"
    assert "skill_manage" in factory["blocked"]
