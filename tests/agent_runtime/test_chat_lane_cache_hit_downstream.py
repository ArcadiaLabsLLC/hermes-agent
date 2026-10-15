"""A chat's turn 1 and turn 2 send one tools prefix and one prompt-cache key (lane h-cache-hit).

Live evidence (Neko, 2026-10-05 22:51 and 2026-10-06 00:15): turn 1's ``prompt_cache_key`` was
the hash of a ``tool_search`` reading "Search 48 additional tools" (the prewarm's catalog, before
the Launcher's app functions registered) plus the five ``browser_vault_*`` tools the persona
defers, ridden eager; turn 2's was the same tools with "Search 58" -- upstream's between-turns
refresh re-appends the deferred tools, and the fork's re-prune re-assembled the bridge only after
the request was built. The fix settles the persona's form in a ``pre_llm_call`` hook, between the
refresh and the request (``plugins/eternia-harness::settle_turn_tools``).

The turns here run the real pieces in upstream's order: the actor built and deferred
(``apply_chat_lane_defer``), the between-turns refresh (``refresh_agent_mcp_tools``,
``preserve_prefix=True``), the plugin's ``pre_llm_call`` hook, the request from ``agent.tools``
in the Responses shape, then the plugin's ``llm_request`` middleware (briefs + cache routing).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.agent_runtime.test_chat_lane_defer import _names, lane  # noqa: F401 — the fixture
from tests.tools.test_tool_search import _td

VAULT = ("browser_vault_list", "browser_vault_unlock", "browser_vault_fill",
         "browser_vault_save_login", "browser_vault_enter_code")
#: A deferred tool that registers AFTER the prewarm built the actor (the live case: the
#: Launcher's ten app functions, absent from the 22:51:19 prewarm's 43/48 catalog).
LATE_TOOL = "session_search"
SYSTEM = "You are Neko. The stable system prompt."


def _plugin():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_cache_hit_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _LedgerActor(SimpleNamespace):
    """An actor whose ``tools`` writes are counted: the writer ledger (plan S0)."""

    def __init__(self, ledger: dict, tools: list, **kwargs):
        super().__init__(**kwargs)
        self.__dict__["_ledger"] = ledger
        self.__dict__["_tools"] = tools

    @property
    def tools(self):
        return self.__dict__["_tools"]

    @tools.setter
    def tools(self, value):
        self.__dict__["_ledger"]["publishes"] += 1
        self.__dict__["_tools"] = value


#: The actor's toolsets: the lane's own, plus the launcher_qa scope the run admitted.
ENABLED = ["harness_core", "mcp-launcher_qa"]


def _new_ledger() -> dict:
    return {"publishes": 0, "pins": [], "reads": 0}


def _reset(ledger: dict) -> dict:
    ledger.update(_new_ledger())
    return ledger


def _register_late(raw: list) -> None:
    """The late tool lands in the catalog the way the live one did: registered, after the build."""
    from tools.registry import registry

    raw.append(_td(LATE_TOOL, f"{LATE_TOOL} does its job."))
    registry.register(LATE_TOOL, "session_search", raw[-1]["function"], handler=lambda *_a, **_k: "")


@pytest.fixture
def chat(lane, monkeypatch):  # noqa: F811 — the imported fixture
    """``(new_actor, turn, raw, ledger)``: actors built by the runner's default factory as the
    chat lane builds them, one turn's wire -- ``(responses tools, persona cache routing
    observability)`` -- and the writer ledger (publishes of ``agent.tools``, session pin writes
    with the pinned names, ``get_tool_definitions`` reads)."""
    import model_tools
    import run_agent
    import tools.mcp_tool  # noqa: F401 — upstream's refresh slot is import-gated on it
    import tools.mcp_tool_agent as mcp_tool_agent
    import tools.tool_search as ts
    from agent.codex_responses_adapter import _responses_tools
    from agent.turn_context import _refresh_mcp_tools_between_turns
    from agent_runtime.cache_routing import persona_cache_scope_id
    from agent_runtime.persona_turn_binding import bind_persona_turn_agent
    from agent_runtime.profile_runner.runner import _default_agent_factory
    from tools.registry import registry

    raw, _build = lane
    ledger = _new_ledger()
    config = ts.ToolSearchConfig.from_raw(None)

    def definitions(**kw):
        """Upstream's get_tool_definitions: the lane's builtins plus every registered MCP tool in
        the enabled toolsets; the profile-wide assembly unless the caller skips it."""
        ledger["reads"] += 1
        enabled = kw.get("enabled_toolsets")
        defs = [td for td in raw if not td["function"]["name"].startswith("mcp__")]
        defs += [{"type": "function", "function": {**e.schema, "name": e.name}}
                 for e in registry.get_all_entries()
                 if str(e.toolset).startswith("mcp-") and (enabled is None or e.toolset in enabled)]
        if kw.get("skip_tool_search_assembly"):
            return defs
        return ts.assemble_tool_defs(defs, context_length=272_000, config=config).tool_defs

    monkeypatch.setattr(model_tools, "get_tool_definitions", definitions)
    monkeypatch.setattr("tools.mcp_tool_discovery.has_registered_mcp_tools", lambda: True)
    monkeypatch.setattr(mcp_tool_agent, "persist_agent_tool_names", lambda agent: ledger["pins"].append(
        {"version": mcp_tool_agent.tool_pin_version(), "tools": json.loads(json.dumps(agent.tools))}))
    plugin = _plugin()
    routed = {}
    monkeypatch.setattr("agent_runtime.cache_routing.route_persona_cache",
                        lambda request, **_kw: routed.setdefault("request", request) and None)

    def upstream_constructor(**kwargs):
        """``run_agent.AIAgent`` as the factory calls it: the profile-wide form at build time."""
        tools = model_tools.get_tool_definitions(enabled_toolsets=list(ENABLED))
        return _LedgerActor(
            ledger, tools, valid_tool_names=_names(tools), enabled_toolsets=list(ENABLED),
            disabled_toolsets=None, context_compressor=SimpleNamespace(context_length=272_000),
            session_id=kwargs["session_id"],
        )

    monkeypatch.setattr(run_agent, "AIAgent", upstream_constructor)

    def new_actor(session_id: str):
        agent = _default_agent_factory(
            session_id=session_id, chat_lane_defer_tools=list(VAULT),
            cache_scope_id=persona_cache_scope_id("personainst_neko_1", session_id))
        assert not agent.valid_tool_names & set(VAULT), "the factory did not apply the persona's defer"
        return agent

    def turn(agent, *, pre_brief: dict | None = None):
        """One turn in upstream's order: the between-turns refresh slot, the plugin's
        ``pre_llm_call`` hook, the request from ``agent.tools``, the ``llm_request`` middleware."""
        from agent_runtime.cache_routing import apply_persona_cache_routing

        _refresh_mcp_tools_between_turns(agent)
        with bind_persona_turn_agent(agent):
            plugin.settle_turn_tools(session_id=agent.session_id)
            request = {"model": "gpt-5.6-luna", "instructions": SYSTEM,
                       "tools": _responses_tools(agent.tools), "prompt_cache_key": "x"}
            if pre_brief is not None:
                pre_brief["tools"] = json.loads(json.dumps(request["tools"]))
            plugin.brief_tool_descriptions(request, api_mode="codex_responses", session_id=agent.session_id)
        wire = routed.pop("request")
        _, observability = apply_persona_cache_routing(
            wire, cache_scope_id=agent.cache_scope_id, session_id=agent.session_id,
            is_codex_backend=True, is_github_responses=False, is_xai_responses=False)
        return wire["tools"], observability

    return new_actor, turn, raw, ledger


def _bytes(tools) -> str:
    return json.dumps(tools, ensure_ascii=False, separators=(",", ":"))


def test_a_prewarmed_chats_turn_one_and_turn_two_send_one_prefix_and_one_key(chat):
    """Positive control (CHANGE commit): drop the ``settle_turn_tools`` call from ``turn``
    (the pre-fix order) -> turn 1 carries the prewarm's bridge and the vault eager, and the
    byte assertion reds."""
    new_actor, turn, raw, _ledger = chat
    actor = new_actor("chat-a")  # the prewarm, before the late tool registers
    _register_late(raw)

    first_tools, first = turn(actor)
    second_tools, second = turn(actor)
    third_tools, third = turn(actor)

    assert _bytes(first_tools) == _bytes(second_tools) == _bytes(third_tools)
    assert first["prompt_cache_key_fingerprint"] == second["prompt_cache_key_fingerprint"] \
        == third["prompt_cache_key_fingerprint"]
    names = {t.get("name") for t in first_tools}
    assert not names & set(VAULT), f"a deferred tool rode the wire eager: {sorted(names & set(VAULT))}"
    listing = next(t for t in first_tools if t.get("name") == "tool_search")["description"]
    assert LATE_TOOL in listing and all(name in listing for name in VAULT)


def test_two_chats_of_one_instance_send_one_prefix_one_key_and_one_scope(chat):
    """Chat A was prewarmed before the late tool registered; chat B was built after. Their
    first turns share the tools prefix, the body key and the instance-scoped Codex header."""
    new_actor, turn, raw, _ledger = chat
    chat_a = new_actor("chat-a")
    _register_late(raw)
    chat_b = new_actor("chat-b")

    a_tools, a = turn(chat_a)
    b_tools, b = turn(chat_b)

    assert _bytes(a_tools) == _bytes(b_tools)
    assert a["prompt_cache_key_fingerprint"] == b["prompt_cache_key_fingerprint"]
    assert a["session_header_fingerprint"] == b["session_header_fingerprint"]
    assert a["cache_scope_source"] == b["cache_scope_source"] == "cache_scope_id"


def test_two_new_chats_turn_one_differ_first_inside_the_user_turn(chat):
    """S6 (lane h-newchat-t1): turn 1 of two chats of one instance sends one prefix up to the
    first per-chat byte, and that byte is inside ``input`` -- never in the tools, never in the
    instructions the turn's own builder composes -- under one body key and one Codex header.

    Live 2026-10-06: the 01:25 chat's turn 1 (``1de60c28``) missed the 00:15 chat's bucket
    (``9c7f8b9d``) because the serve between them changed the wire tools (h-cache-hit: the five
    ``browser_vault_*`` stopped riding eager, tools JSON offset 34687), not on a per-chat byte.

    *Killing mutation:* scope the cache by the chat (``persona_cache_scope_id`` returns its
    fallback, the pre-S6 routing) -- the two chats' headers differ.
    """
    from agent_runtime.persona_runtime import _mission_chat_surface_message
    from tests.agent_runtime.persona_samples import sample_personas

    neko = next(p for p in sample_personas() if p.id == "neko_supervisor")
    new_actor, turn, _raw, _ledger = chat
    wires = []
    for root, text in (("persona_chat_personainst_neko_1_aaaa", "hi"),
                       ("persona_chat_personainst_neko_1_bbbb", "hello there")):
        tools, observability = turn(new_actor(root))
        body = {"tools": tools, "instructions": _mission_chat_surface_message(neko, ""),
                "input": [{"role": "user", "content": text}]}
        wires.append((_bytes(body), _bytes({"tools": tools, "instructions": body["instructions"]})[:-1],
                      observability))
    (a, a_prefix, a_obs), (b, b_prefix, b_obs) = wires
    first = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
    assert a_prefix == b_prefix and first >= len(a_prefix), (first, a[first - 40:first + 40])
    assert a[len(a_prefix):].startswith(',"input":')
    assert a_obs["prompt_cache_key_fingerprint"] == b_obs["prompt_cache_key_fingerprint"]
    assert a_obs["session_header_fingerprint"] == b_obs["session_header_fingerprint"]


# ── The writer ledger (plan tool-form-one-owner-2026-10-08 S0) ──────────────────────────────
# Measured on the pre-owner tree, per warm turn: 2 publishes of ``agent.tools`` (upstream's
# between-turns refresh, the fork's re-assembly), 1 session pin write (the refresh's form, the
# persona's deferred tools in it), 2 ``get_tool_definitions`` reads (the refresh's assembled
# read, the re-assembly's raw read). With one owner and the refresh off (S2): 0 / 0 / 0.


def _warm_turns(chat, n: int = 2) -> dict:
    """A chat's actor built before the late tool registered, turn 1 run, then ``n`` warm turns
    under a fresh ledger: what a warm turn costs."""
    new_actor, turn, raw, ledger = chat
    actor = new_actor("chat-a")
    _register_late(raw)
    turn(actor)
    _reset(ledger)
    for _ in range(n):
        turn(actor)
    return ledger


def test_a_warm_turn_publishes_the_form_once_and_pins_nothing(chat):
    ledger = _warm_turns(chat)
    assert (ledger["publishes"], len(ledger["pins"])) == (0, 0), (
        f"two warm turns: publishes={ledger['publishes']} pins={len(ledger['pins'])}")


def test_the_pin_never_carries_a_persona_deferred_name(chat):
    new_actor, turn, raw, ledger = chat
    actor = new_actor("chat-a")
    _register_late(raw)
    for _ in range(3):
        turn(actor)
    carried = [sorted({t["function"]["name"] for t in pin["tools"]} & set(VAULT)) for pin in ledger["pins"]]
    assert not any(carried), f"pins carrying deferred names: {carried}"


def test_a_warm_turn_reads_no_tool_definitions(chat):
    ledger = _warm_turns(chat)
    assert ledger["reads"] == 0, f"two warm turns read get_tool_definitions {ledger['reads']} times"
