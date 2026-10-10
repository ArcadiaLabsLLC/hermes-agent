"""D1.01 — the admitted MCP registry scope is resident; the call budget is per run.

Owner ruling 2026-10-10 (design sweep D1, superseding R2's per-run teardown): an admitted
server's registry scope lives for its transport session plus its admission content, and
isolation between personas stays ``scope_toolsets_to_admission``. What this file pins:

1. Two admissions of the same set: the registrar runs once and ``registry.generation`` is
   equal before run 2 and after its release (the D1.02 memo key does not move).
2. Run 2 is metered by run 2's budget, never run 1's spent count.
3. A released scope refuses a dispatch no admitted run owns (fail closed).
4. A narrower admission of the same server re-registers: the wider surface is not inherited.

No test here spawns a real MCP server or connects a transport.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.mcp_admission import (
    LANE_MISSION_CHAT,
    MCP_ADMISSION_BUDGET_EXHAUSTED,
    READ_ONLY_EXCLUDED_TOOLS,
    READ_ONLY_INCLUDED_TOOLS,
    McpAdmission,
    admit_mcp_servers,
    release_mcp_admission,
    teardown_mcp_admission,
)

_SERVER = "launcher_qa"
_TOOLSET = f"mcp-{_SERVER}"


@pytest.fixture
def registry():
    from tools.registry import registry

    teardown_mcp_admission([_SERVER])
    yield registry
    teardown_mcp_admission([_SERVER])


def _admission(*, limit: int = 3, config: dict | None = None) -> McpAdmission:
    return McpAdmission(
        lane=LANE_MISSION_CHAT,
        role="qa",
        permission_mode="profile_default",
        enabled=True,
        requested=(_SERVER,),
        server_names=(_SERVER,),
        server_configs={_SERVER: dict(config or {"command": "noop"})},
        max_tool_calls_per_run=limit,
    )


class _CountingRegistrar:
    """Registers three plain tools under ``mcp-launcher_qa`` and counts its own calls."""

    tools = ("get_buttons", "run_actions", "kill_launcher")

    def __init__(self, registry):
        self.registry = registry
        self.registrations = 0
        self.dispatched: list[str] = []

    def prefixed(self, tool: str) -> str:
        return f"mcp__{_SERVER}__mcp_{_SERVER}_{tool}"

    def __call__(self, _servers) -> list[str]:
        self.registrations += 1
        names = []
        for tool in self.tools:
            name = self.prefixed(tool)
            self.registry.register(
                name=name,
                toolset=_TOOLSET,
                schema={"name": name, "description": tool, "parameters": {}},
                handler=self._handler(name),
                is_async=False,
                description=tool,
            )
            names.append(name)
        return names

    def _handler(self, name: str):
        def _call(args, **kwargs):
            self.dispatched.append(name)
            return json.dumps({"ok": True, "tool": name})

        return _call


def test_a_second_admission_reuses_the_scope_and_moves_no_generation(registry):
    registrar = _CountingRegistrar(registry)

    first = admit_mcp_servers(_admission(), register=registrar)
    assert first.admitted == (_SERVER,)
    release_mcp_admission(first.admitted)

    before_run_2 = registry.generation
    second = admit_mcp_servers(_admission(), register=registrar)
    release_mcp_admission(second.admitted)

    assert second.admitted == (_SERVER,)
    assert registrar.registrations == 1
    assert registry.generation == before_run_2
    assert set(registry.get_tool_names_for_toolset(_TOOLSET)) == {
        registrar.prefixed(tool) for tool in registrar.tools
    }


def test_run_two_is_metered_by_its_own_budget(registry):
    registrar = _CountingRegistrar(registry)
    tool = registrar.prefixed("get_buttons")

    first = admit_mcp_servers(_admission(limit=1), register=registrar)
    assert json.loads(registry.dispatch(tool, {}))["ok"] is True
    assert first.call_budget.exhausted
    release_mcp_admission(first.admitted)

    second = admit_mcp_servers(_admission(limit=1), register=registrar)
    # Run 1's spent count is not carried: run 2's first call dispatches.
    assert json.loads(registry.dispatch(tool, {}))["ok"] is True
    refused = json.loads(registry.dispatch(tool, {}))

    assert refused["code"] == MCP_ADMISSION_BUDGET_EXHAUSTED
    assert refused["budget"]["limit"] == 1
    assert (second.call_budget.spent, second.call_budget.refused) == (1, 1)
    assert (first.call_budget.spent, first.call_budget.refused) == (1, 0)
    assert registrar.dispatched == [tool, tool]
    release_mcp_admission(second.admitted)


def test_a_released_scope_refuses_a_call_no_admitted_run_owns(registry):
    registrar = _CountingRegistrar(registry)
    tool = registrar.prefixed("kill_launcher")

    outcome = admit_mcp_servers(_admission(), register=registrar)
    release_mcp_admission(outcome.admitted)

    refused = json.loads(registry.dispatch(tool, {}))

    assert refused["code"] == MCP_ADMISSION_BUDGET_EXHAUSTED
    assert refused["tool"] == tool
    assert registrar.dispatched == []
    assert outcome.call_budget.spent == 0


# ── the real warm seam: a narrower admission is never served the wider surface ──


class _FakeMcpTool:
    def __init__(self, name: str):
        self.name = name
        self.description = f"fake {name}"
        self.inputSchema = {"type": "object", "properties": {}}


class _FakeConnectedServer:
    def __init__(self, name: str, tool_names):
        self.name = name
        self.session = object()
        self.tool_timeout = 5.0
        self._tools = [_FakeMcpTool(tool) for tool in tool_names]


_FULL_SURFACE = tuple(
    sorted(set(READ_ONLY_INCLUDED_TOOLS[_SERVER]) | set(READ_ONLY_EXCLUDED_TOOLS[_SERVER]))
)


@pytest.fixture
def warm_server(monkeypatch, registry):
    import tools.mcp_tool as mcp_tool

    server = _FakeConnectedServer(_SERVER, _FULL_SURFACE)
    monkeypatch.setitem(mcp_tool._servers, _SERVER, server)
    return server


def _raw(registry) -> set[str]:
    return {name.rsplit("__", 1)[-1] for name in registry.get_tool_names_for_toolset(_TOOLSET) or []}


def test_a_narrower_admission_re_registers_instead_of_inheriting(registry, warm_server):
    from agent_runtime.mcp_admission import _default_registrar

    wide = admit_mcp_servers(_admission(), register=_default_registrar)
    assert "mcp_launcher_qa_kill_launcher" in _raw(registry)
    release_mcp_admission(wide.admitted)

    narrow_config = {"command": "noop", "tools": {"include": list(READ_ONLY_INCLUDED_TOOLS[_SERVER])}}
    narrow = admit_mcp_servers(_admission(config=narrow_config), register=_default_registrar)
    release_mcp_admission(narrow.admitted)

    assert narrow.admitted == (_SERVER,)
    assert _raw(registry) == set(READ_ONLY_INCLUDED_TOOLS[_SERVER])
    for mutator in READ_ONLY_EXCLUDED_TOOLS[_SERVER]:
        assert mutator not in _raw(registry)


# ── S2: invalidation — the scope stands only while its session, list and tools do ──


class _CountingDefaultRegistrar:
    """The production registrar, counted."""

    def __init__(self):
        self.calls = 0

    def __call__(self, servers):
        from agent_runtime.mcp_admission import _default_registrar

        self.calls += 1
        return _default_registrar(servers)


def test_a_replaced_session_re_registers(registry, warm_server):
    registrar = _CountingDefaultRegistrar()
    release_mcp_admission(admit_mcp_servers(_admission(), register=registrar).admitted)

    warm_server.session = object()  # a reconnect: same server task, new session
    second = admit_mcp_servers(_admission(), register=registrar)
    release_mcp_admission(second.admitted)

    assert second.admitted == (_SERVER,)
    assert registrar.calls == 2


def test_a_session_lost_during_the_run_drops_the_scope_at_release(registry, warm_server):
    first = admit_mcp_servers(_admission(), register=_CountingDefaultRegistrar())
    assert _raw(registry)

    warm_server.session = None  # parked mid-run: the handlers point at a dead session
    released = release_mcp_admission(first.admitted)

    assert released.ok
    assert len(released.removed_tool_names) == len(_FULL_SURFACE)
    assert _raw(registry) == set()


def test_a_server_that_re_listed_its_tools_re_registers(registry, warm_server):
    registrar = _CountingDefaultRegistrar()
    release_mcp_admission(admit_mcp_servers(_admission(), register=registrar).admitted)

    warm_server._tools = warm_server._tools + [_FakeMcpTool("mcp_launcher_qa_new_verb")]
    release_mcp_admission(admit_mcp_servers(_admission(), register=registrar).admitted)

    assert registrar.calls == 2
    assert "mcp_launcher_qa_new_verb" in _raw(registry)


def test_a_partial_registration_is_re_registered_whole(registry):
    registrar = _CountingRegistrar(registry)
    release_mcp_admission(admit_mcp_servers(_admission(), register=registrar).admitted)

    registry.deregister(registrar.prefixed("run_actions"))  # e.g. a failed meter removed it
    second = admit_mcp_servers(_admission(), register=registrar)
    release_mcp_admission(second.admitted)

    assert registrar.registrations == 2
    assert set(registry.get_tool_names_for_toolset(_TOOLSET)) == {
        registrar.prefixed(tool) for tool in registrar.tools
    }


@pytest.mark.parametrize("named", [True, False])
def test_drop_resident_scopes_empties_the_registry_of_that_server(registry, named):
    from agent_runtime.mcp_admission import drop_resident_scopes

    registrar = _CountingRegistrar(registry)
    release_mcp_admission(admit_mcp_servers(_admission(), register=registrar).admitted)

    dropped = drop_resident_scopes([_SERVER] if named else None)

    assert dropped.ok and dropped.servers == (_SERVER,)
    assert registry.get_tool_names_for_toolset(_TOOLSET) == []
    release_mcp_admission(admit_mcp_servers(_admission(), register=registrar).admitted)
    assert registrar.registrations == 2
