"""One owner of a persona chat turn's tool form (plan tool-form-one-owner-2026-10-08).

The turns run the real pieces in upstream's order on the writer-ledger fixture of
``test_chat_lane_cache_hit_downstream``: actors built by the runner's default factory,
upstream's between-turns slot, the eternia-harness ``pre_llm_call`` hook (the owner), the
request from ``agent.tools``, the ``llm_request`` middleware.
"""

from __future__ import annotations

from tests.agent_runtime.test_chat_lane_cache_hit_downstream import (  # noqa: F401 — the fixtures
    VAULT,
    _bytes,
    _register_late,
    _reset,
    chat,
)
from tests.agent_runtime.test_chat_lane_defer import _names, lane  # noqa: F401 — the fixture


def _receipt(agent):
    from agent_runtime.chat_lane_tool_form import RECEIPT_ATTR

    return getattr(agent, RECEIPT_ATTR)


def _wire_names(tools) -> list[str]:
    return [t.get("name") or (t.get("function") or {}).get("name") for t in tools]


def test_a_catalog_move_breaks_once(chat):
    """A tool registered between turns 1 and 2 moves the form once: turn 2 differs from turn 1,
    turn 3 equals turn 2, and turn 3 neither reads nor assembles.

    *Killing mutation:* the memo key drops ``registry_content_revision()`` -- the late
    registration never rebuilds and turn 2 ships turn 1's bytes."""
    new_actor, turn, raw, _ledger = chat
    actor = new_actor("chat-a")
    first, _ = turn(actor)
    _register_late(raw)
    second, _ = turn(actor)
    assert _receipt(actor).source == "rebuilt"
    third, _ = turn(actor)
    assert _bytes(second) != _bytes(first), "the catalog moved and the form did not"
    assert _bytes(third) == _bytes(second)
    assert _receipt(actor).source != "rebuilt", "a turn with no catalog move re-derived the form"


def test_the_pin_is_what_the_turn_ships(chat):
    """The session pin holds the turn's form after the owner and the block prune: the pre-brief
    ``request["tools"]`` names, ``agent.tools``'s names, never a deferred name.

    *Killing mutation:* the owner pins before it publishes -- the pin holds the previous form."""
    new_actor, turn, raw, ledger = chat
    actor = new_actor("chat-a")
    _register_late(raw)
    pre_brief: dict = {}
    turn(actor, pre_brief=pre_brief)
    assert ledger["pins"], "the turn's form moved and nothing was pinned"
    pinned = [t["function"]["name"] for t in ledger["pins"][-1]["tools"]]
    assert pinned == _wire_names(pre_brief["tools"]) == [t["function"]["name"] for t in actor.tools]
    assert not set(pinned) & set(VAULT), sorted(set(pinned) & set(VAULT))


def test_an_unchanged_form_is_not_published_again(chat):
    """Two settles with nothing moved between them: the second publishes nothing, pins nothing.

    *Killing mutation:* the owner publishes unconditionally -- a publish and a pin on the
    second settle."""
    from agent_runtime.chat_lane_tool_form import settle_turn_tool_form

    new_actor, _turn, raw, ledger = chat
    actor = new_actor("chat-a")
    _register_late(raw)
    assert settle_turn_tool_form(actor).published
    _reset(ledger)
    receipt = settle_turn_tool_form(actor)
    assert (receipt.source, ledger["publishes"], len(ledger["pins"]), ledger["reads"]) == ("unchanged", 0, 0, 0)


def test_a_persona_without_a_defer_list_is_left_to_its_constructor_form(lane):
    """An actor the factory did not build (no defer attribute) is never settled."""
    from agent_runtime.chat_lane_tool_form import settle_turn_tool_form

    _raw, build_agent = lane
    agent = build_agent()
    before = list(agent.tools)
    assert settle_turn_tool_form(agent) is None
    assert agent.tools == before


# ── S2: upstream's refresh is off for the lane; the owner lands the admitted scope ───────────


def _launcher_qa_server():
    """The launcher_qa server as ``_launcher_qa_registration`` builds it: every verb, a mock session."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from tests.tools.test_tool_search_downstream import (
        _LAUNCHER_QA_CONTROL_VERB,
        _LAUNCHER_QA_CORE_VERBS,
        _LAUNCHER_QA_DEMOTED_VERB,
    )
    from tools.mcp_tool import MCPServerTask

    server = MCPServerTask("launcher_qa")
    server._tools = [SimpleNamespace(name=verb, description="launcher_qa verb.", inputSchema=None)
                     for verb in (*_LAUNCHER_QA_CORE_VERBS, _LAUNCHER_QA_CONTROL_VERB, _LAUNCHER_QA_DEMOTED_VERB)]
    server.session = MagicMock()
    return server


def test_the_factory_switches_the_upstream_refresh_off(chat):
    """*Killing mutation:* the factory stops setting ``_skip_mcp_refresh`` -- this, and the
    ledger's ``test_a_warm_turn_reads_no_tool_definitions``, red."""
    new_actor, _turn, _raw, _ledger = chat
    assert new_actor("chat-a")._skip_mcp_refresh is True


def test_an_admitted_servers_tools_reach_a_reused_actor_once(chat):
    """A reused actor built with no launcher_qa scope: the run admits the server (the real MCP
    registration path), the turn ships its promoted verbs eager and lists the demoted one, which
    ``tool_call`` resolves; the scope is torn down and the next turn ships none of it, one publish.

    *Killing mutation:* the memo key omits ``admitted_mcp_tools`` -- the admitted scope never
    reaches the reused actor (and, once it has, the torn-down scope is served from the memo)."""
    import tools.tool_search as ts
    from agent_runtime.mcp_admission.registration import teardown_mcp_admission
    from tools.mcp_tool_registration import _register_server_tools
    from tools.tool_search_downstream import PROMOTED_MCP_TOOLS, scoped_turn_defer

    new_actor, turn, _raw, ledger = chat
    teardown_mcp_admission(["launcher_qa"])
    actor = new_actor("chat-a")
    assert not {n for n in actor.valid_tool_names if n.startswith("mcp__")}
    turn(actor)

    registered = _register_server_tools("launcher_qa", _launcher_qa_server(), {})
    demoted = next(n for n in registered if n.endswith("capture_screenshot"))
    _reset(ledger)
    wire, _ = turn(actor)
    names = set(_wire_names(wire))
    assert PROMOTED_MCP_TOOLS <= names, sorted(PROMOTED_MCP_TOOLS - names)
    assert demoted not in names
    listing = next(t for t in wire if t.get("name") == "tool_search")["description"]
    assert demoted in listing
    with scoped_turn_defer(VAULT):
        _name, _args, err = ts.resolve_underlying_call({"calls": [{"name": demoted, "arguments": {}}]})
    assert err is None, err
    assert (ledger["publishes"], _receipt(actor).admitted) == (1, len(registered))

    teardown_mcp_admission(["launcher_qa"])
    _reset(ledger)
    wire, _ = turn(actor)
    assert not set(registered) & set(_wire_names(wire)), sorted(set(registered) & set(_wire_names(wire)))
    assert demoted not in next(t for t in wire if t.get("name") == "tool_search")["description"]
    assert (ledger["publishes"], _receipt(actor).admitted) == (1, 0)


def test_admission_churn_does_not_rebuild_the_form(chat):
    """Another run's scope (``mcp-other``, not this actor's) registers and tears down between two
    turns: ``registry.generation`` moves, the form does not -- no read, no publish, no pin.

    *Killing mutation:* the memo key carries ``registry.generation`` -- a read and a rebuild."""
    from tools.registry import registry

    new_actor, turn, raw, ledger = chat
    actor = new_actor("chat-a")
    _register_late(raw)
    turn(actor)
    before = registry._generation
    registry.register("mcp__other__probe", "mcp-other", {"name": "mcp__other__probe", "description": "x",
                                                          "parameters": {"type": "object", "properties": {}}},
                      handler=lambda *_a, **_k: "")
    registry.deregister("mcp__other__probe")
    assert registry._generation == before + 2
    _reset(ledger)
    turn(actor)
    assert (ledger["reads"], ledger["publishes"], len(ledger["pins"]), _receipt(actor).source) == (0, 0, 0, "unchanged")
