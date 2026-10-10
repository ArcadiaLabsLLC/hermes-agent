"""D1.02 — admission no longer drops upstream's tool-definitions memo; D1.01 S3 receipts.

Before D1.01 every admitting run registered N tools and tore N down, so
``registry.generation`` (part of ``model_tools._tool_defs_cache_key``) moved 2N per run and a
reused actor's ``get_tool_definitions`` was a full rebuild every turn (202-215 ms measured on a
44-tool home). With the resident scope the second admitting turn hits the memo, and the runner
says so: ``profile_timing.mcp_admission_reused`` = 1, kept by the durable record.

No test here spawns a real MCP server or connects a transport.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent_runtime.mcp_admission import (
    LANE_MISSION_CHAT,
    McpAdmission,
    admit_mcp_servers,
    release_mcp_admission,
    teardown_mcp_admission,
)
from tests._downstream.split_package_source import patch_where_bound

_SERVER = "memo_probe"
_TOOLSET = f"mcp-{_SERVER}"


def _admission() -> McpAdmission:
    return McpAdmission(
        lane=LANE_MISSION_CHAT,
        role="qa",
        permission_mode="profile_default",
        enabled=True,
        requested=(_SERVER,),
        server_names=(_SERVER,),
        server_configs={_SERVER: {"command": "noop"}},
        max_tool_calls_per_run=5,
    )


@pytest.fixture
def warm_probe(monkeypatch):
    """A connected ``memo_probe`` in ``tools/mcp_tool._servers``: live session, 12 listed tools."""

    import tools.mcp_tool as mcp_tool

    tools = [
        SimpleNamespace(
            name=f"probe_{index:02d}",
            description=f"probe tool {index}",
            inputSchema={"type": "object", "properties": {"x": {"type": "string"}}},
        )
        for index in range(12)
    ]
    server = SimpleNamespace(name=_SERVER, session=object(), tool_timeout=5.0, _tools=tools)
    monkeypatch.setitem(mcp_tool._servers, _SERVER, server)
    teardown_mcp_admission([_SERVER])
    yield server
    teardown_mcp_admission([_SERVER])


def _admitting_turn():
    import model_tools
    from agent_runtime.mcp_admission import _default_registrar

    outcome = admit_mcp_servers(_admission(), register=_default_registrar)
    assert outcome.admitted == (_SERVER,)
    definitions = model_tools.get_tool_definitions(enabled_toolsets=[_TOOLSET], quiet_mode=True)
    release_mcp_admission(outcome.admitted)
    return outcome, definitions


def test_the_second_admitting_turn_hits_the_tool_definitions_memo(warm_probe):
    import model_tools
    from tools.tool_defs_observability import (
        tool_defs_cache_hits_this_thread,
        tool_defs_cache_misses_this_thread,
    )

    model_tools._clear_tool_defs_cache()
    first, first_defs = _admitting_turn()
    hits, misses = tool_defs_cache_hits_this_thread(), tool_defs_cache_misses_this_thread()

    second, second_defs = _admitting_turn()

    assert tool_defs_cache_hits_this_thread() == hits + 1
    assert tool_defs_cache_misses_this_thread() == misses
    assert second.reused == (_SERVER,) and first.reused == ()
    assert [d["function"]["name"] for d in second_defs] == [d["function"]["name"] for d in first_defs]
    probe_keys = [key for key in model_tools._tool_defs_cache if key[1] == frozenset({_TOOLSET})]
    assert len(probe_keys) == 1


class _Agent:
    def __init__(self, **kwargs):
        self.session_id = kwargs.get("session_id") or "session_memo"
        self.provider = kwargs.get("provider")
        self.model = kwargs.get("model")
        self.base_url = None
        self.tools = []

    def run_conversation(self, user_message, system_message=None, task_id=None):
        return {"final_response": "ok", "session_id": self.session_id, "messages": [],
                "api_calls": 1, "total_tokens": 1}


def test_the_runner_records_a_reused_admission_and_the_record_keeps_it(monkeypatch, warm_probe):
    import agent_runtime.mcp_admission as mcp_admission
    from agent_runtime.mcp_admission import _default_registrar
    from agent_runtime.mission_chat_turns.records import safe_turn_profile_timing
    from agent_runtime.profile_runner import AgentRunRequest, ProfileAgentRunner

    # The production registrar, reached through the binding the runner's admission reads.
    patch_where_bound(monkeypatch, mcp_admission, "_default_registrar", lambda servers: _default_registrar(servers))
    events: list[dict] = []

    def _run():
        request = AgentRunRequest(profile=None, user_message="hi", mcp_admission=_admission(),
                                  progress_callback=events.append)
        return ProfileAgentRunner(agent_factory=_Agent).run(request).profile_timing

    first, second = _run(), _run()

    assert first["mcp_admission_reused"] == 0
    assert second["mcp_admission_reused"] == 1
    assert safe_turn_profile_timing(second)["mcp_admission_reused"] == 1
    summaries = [e["summary"] for e in events if e.get("step") == "mcp_admission_resolved"]
    assert summaries == [f"MCP admission (registered): {_SERVER}", f"MCP admission (reused): {_SERVER}"]
    assert json.dumps(second)  # the flag is a plain int, safe on the wire
