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

from agent_runtime.tool_surface import receipt_names
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
    assert receipt_names(factory, "eager") | set(factory["bridge"]) == {d["function"]["name"] for d in agent.tools}
    assert factory["deferred"]["browser_vault_list"]["reason"] == "persona_defer"
    assert "skill_manage" in factory["blocked"]


def test_a_persona_with_no_defer_list_still_carries_the_account(harness_lane):  # noqa: F811
    """The constructor's form is the wire for a persona with no ``chat_lane_defer_tools``; its
    first settle accounts it once, so the curated and non-core defers are reported, not silent."""

    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer, settle_turn_tool_form
    from agent_runtime.tool_surface import AGENT_SURFACE_ATTR

    agent = harness_lane.build_agent()
    shipped = [d["function"]["name"] for d in agent.tools]
    assert apply_chat_lane_defer(agent, ()) is False
    settle_turn_tool_form(agent, pin=False)
    receipt = getattr(agent, AGENT_SURFACE_ATTR, None)
    assert receipt is not None and receipt.get("state") != "not_computed", receipt
    assert receipt["deferred"]["todo_list"]["reason"] == "curated_default_defer"
    assert receipt["deferred"]["agent_chat_open"]["reason"] == "non_core_rule_defer"
    assert [d["function"]["name"] for d in agent.tools] == shipped, "the account never moves the form"
    assert sorted([*receipt_names(receipt, "eager"), *receipt["bridge"]]) == sorted(shipped)


def test_a_persona_with_no_defer_list_is_accounted_at_construction(harness_lane):  # noqa: F811
    """Turn 1 of a prewarmed actor reads the receipt before any turn settle: construction
    (which the prewarm pays, off the turn) leaves it, and the first settle keeps it."""

    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer, settle_turn_tool_form
    from agent_runtime.tool_surface import AGENT_SURFACE_ATTR

    agent = harness_lane.build_agent()
    shipped = [d["function"]["name"] for d in agent.tools]
    assert apply_chat_lane_defer(agent, ()) is False
    at_construction = getattr(agent, AGENT_SURFACE_ATTR, None)
    assert at_construction is not None and at_construction.get("state") != "not_computed", at_construction
    assert sorted([*receipt_names(at_construction, "eager"), *at_construction["bridge"]]) == sorted(shipped)
    receipt = settle_turn_tool_form(agent, pin=False)
    assert receipt is not None and receipt.source == "unchanged"
    assert getattr(agent, AGENT_SURFACE_ATTR) == at_construction


def test_a_shell_preview_without_the_live_mcp_list_agrees_with_the_factory(harness_lane, monkeypatch):  # noqa: F811
    """The live gap (2026-10-09): ``persona tool-diff neko_supervisor`` said eager 19 /
    ``toolsurf_927c...`` while the turn's prompt record said eager 22 / ``toolsurf_97fc...``: the
    serve's process held launcher_qa's three promoted tools, the shell's had no MCP connection.
    The MCP names ride apart (``mcp``), so the core eager set and the resolution id are the part
    both processes can know, and they agree on it.

    Killing mutation: drop ``not is_mcp_tool_name(d.name)`` from ``ToolSurface.resolution_id``
    (or route MCP rows into the core states in ``receipt``) => red.
    """

    import model_tools

    import agent_runtime.chat_lane_bundle as CLB
    from agent_runtime.chat_lane_tool_form import apply_chat_lane_defer
    from agent_runtime.tool_surface import AGENT_SURFACE_ATTR, is_mcp_tool_name
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
    assert factory["mcp"]["eager"], "anti-vacuity: the factory's wire carries promoted MCP tools"

    # The shell: no MCP connection, so neither the definitions nor the registry hold launcher_qa.
    raw = [td for td in harness_lane.raw if not is_mcp_tool_name(td["function"]["name"])]
    monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **_kw: list(raw))
    for name in [n for n in harness_lane.registry.get_all_tool_names() if is_mcp_tool_name(n)]:
        harness_lane.registry.deregister(name)
    preview = inspect_commands._preview_tool_surface(
        SimpleNamespace(id="neko_supervisor"), SimpleNamespace(session_id=None), "unbounded", {})

    assert preview["mcp"] == {state: {} for state in ("eager", "deferred", "unavailable", "blocked")}
    assert preview["eager"] == factory["eager"]
    assert preview["counts"]["eager"] == factory["counts"]["eager"]
    assert preview["resolution_id"] == factory["resolution_id"]
