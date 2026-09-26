"""A run's blocked tools, enforced through the plugin surface (plugin-fit PF-1).

Three doors, one block: the constructed agent is pruned
(``profile_runner.runner._default_agent_factory``), the eternia-harness
``llm_request`` middleware drops the definition from the provider payload, and its
``pre_tool_call`` hook refuses the call — a ``tool_call``-unwrapped one included.
Every negative below has its positive control: the same input, the block unbound.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from agent_runtime.tool_blocks import blocked_tools_for, bound_tool_block, prune_agent_tools


def _plugin_callbacks():
    path = Path(__file__).resolve().parents[2] / "plugins" / "eternia-harness" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_eternia_harness_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    registered: dict[str, object] = {}

    class _Ctx:
        def __getattr__(self, name):
            return lambda *a, **k: None

        def register_middleware(self, kind, callback):
            registered[kind] = callback

        def register_hook(self, name, callback):
            registered[name] = callback

    module.register(_Ctx())
    return registered


_PAYLOADS = {
    "chat_completions": lambda name: {"type": "function", "function": {"name": name, "description": "d", "parameters": {}}},
    "codex_responses": lambda name: {"type": "function", "name": name, "description": "d", "parameters": {}},
    "anthropic_messages": lambda name: {"name": name, "description": "d", "input_schema": {}},
}


def _wire_names(request):
    names = []
    for entry in request["tools"]:
        inner = entry.get("function")
        names.append((inner if isinstance(inner, dict) else entry)["name"])
    return names


@pytest.mark.parametrize("api_mode", sorted(_PAYLOADS))
def test_the_llm_request_middleware_drops_the_blocked_definition(api_mode):
    callback = _plugin_callbacks()["llm_request"]
    shape = _PAYLOADS[api_mode]
    request = {"model": "m", "tools": [shape("pf1_blocked_probe"), shape("pf1_kept_probe")]}

    with bound_tool_block(["pf1_blocked_probe"], session_ids=["s-pf1"]):
        result = callback(request=request, session_id="s-pf1", api_mode=api_mode)
    assert _wire_names((result or {"request": request})["request"]) == ["pf1_kept_probe"]
    assert "blocked tools dropped" in result["reason"]
    assert _wire_names(request) == ["pf1_blocked_probe", "pf1_kept_probe"]  # input not mutated

    # Positive control: same payload, no block bound -> the definition stays on the wire.
    unbound = callback(request=request, session_id="s-pf1", api_mode=api_mode)
    names = _wire_names((unbound or {"request": request})["request"])
    assert "pf1_blocked_probe" in names


def _register_probe(name, toolset, calls):
    from tools.registry import registry

    def _handler(args, task_id=None, **kw):
        calls.append(args)
        return json.dumps({"ok": True})

    registry.register(
        name=name, toolset=toolset, handler=_handler,
        schema={"name": name, "description": f"probe {name}", "parameters": {"type": "object", "properties": {}}},
    )


@pytest.fixture
def plugin_pre_tool_call(monkeypatch):
    """Route upstream's ``pre_tool_call`` fire site to the plugin's registered hook."""
    from hermes_cli import lifecycle

    hook = _plugin_callbacks().get("pre_tool_call")

    def _invoke(name, **kwargs):
        return [hook(**kwargs)] if hook is not None and name == "pre_tool_call" else []

    monkeypatch.setattr(lifecycle, "invoke_hook", _invoke)
    return hook


def test_a_blocked_tool_is_refused_through_the_tool_call_bridge(plugin_pre_tool_call):
    import model_tools

    calls: list = []
    _register_probe("mcp_pf1_probe_op", "mcp-pf1-probe", calls)
    call = dict(
        function_name="tool_call",
        function_args={"name": "mcp_pf1_probe_op", "arguments": {}},
        enabled_toolsets=["mcp-pf1-probe"],
        session_id="s-pf1-bridge",
    )

    with bound_tool_block(["mcp_pf1_probe_op"], session_ids=["s-pf1-bridge"]):
        refused = json.loads(model_tools.handle_function_call(**call))
    assert calls == []
    assert "not available in this session" in json.dumps(refused)

    # Positive control: no block bound -> the same bridged call dispatches.
    assert json.loads(model_tools.handle_function_call(**call)) == {"ok": True}
    assert calls == [{}]


def test_the_block_follows_the_run_past_a_rotated_session_id():
    with bound_tool_block(["terminal"], session_ids=["root-session"]):
        assert blocked_tools_for("root-session") == {"terminal"}
        assert blocked_tools_for("compression-child") == {"terminal"}
    assert blocked_tools_for("root-session") == frozenset()
    assert blocked_tools_for("compression-child") == frozenset()


class _Agent:
    def __init__(self, names):
        self.tools = [{"type": "function", "function": {"name": name}} for name in names]
        self.valid_tool_names = set(names) | {"provider_only_tool"}
        self._kanban_worker_guidance = "kanban guidance"


def test_prune_drops_the_names_from_tools_and_valid_tool_names():
    agent = _Agent(["terminal", "memory", "kanban_show"])
    prune_agent_tools(agent, ["memory", "kanban_show"])
    assert [t["function"]["name"] for t in agent.tools] == ["terminal"]
    assert agent.valid_tool_names == {"terminal", "provider_only_tool"}
    assert agent._kanban_worker_guidance == ""

    control = _Agent(["terminal", "memory"])
    prune_agent_tools(control, [])
    assert control.valid_tool_names == {"terminal", "memory", "provider_only_tool"}


def test_the_default_factory_prunes_and_never_hands_the_kwarg_to_upstream(monkeypatch):
    import run_agent
    from agent_runtime.profile_runner.runner import _default_agent_factory

    seen: dict = {}

    class _Upstream(_Agent):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(["terminal", "memory"])

    monkeypatch.setattr(run_agent, "AIAgent", _Upstream)
    agent = _default_agent_factory(model="m", blocked_tool_names=["memory"])
    assert "blocked_tool_names" not in seen
    assert "memory" not in agent.valid_tool_names
    assert [t["function"]["name"] for t in agent.tools] == ["terminal"]


def test_the_runner_binds_the_block_for_the_run(monkeypatch):
    from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner

    observed: dict = {}

    class _RunAgent:
        def __init__(self, **kwargs):
            self.session_id = "s-run"
            self.provider, self.model, self.base_url = kwargs.get("provider"), kwargs.get("model"), ""
            self.tools = []

        def run_conversation(self, user_message, system_message=None, task_id=None):
            observed["during"] = blocked_tools_for(self.session_id)
            return {"final_response": "ok", "session_id": self.session_id, "messages": []}

    monkeypatch.setattr(
        "agent_runtime.profile_runner.execute.resolve_runtime_provider",
        lambda requested, target_model: {"provider": requested, "model": target_model, "api_mode": "chat_completions"},
    )
    ProfileAgentRunner(agent_factory=_RunAgent).run(
        AgentRunRequest(profile=None, provider="p", model="m", blocked_tool_names=["send_message"], user_message="hi")
    )
    assert "send_message" in observed["during"]
    assert blocked_tools_for("s-run") == frozenset()
