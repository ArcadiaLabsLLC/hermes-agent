"""A QUEUED turn sees its sender's Launcher tools, never the most recent attach's.

Per-connection tool scope, S1 (plan deleted on landing; domain doc: 05-chat-turn-lane.md).
The registry holds the union of every attached Launcher's catalog (D1.03, ``0df2a3a79c0``)
and each turn sees only its bound link's entries; a queued turn binds its sender's link
(L5.13, ``hermes_cli/harness_parts/serve/queued_turn_origin.py``). This pins the join of
the two: the case the row named, a turn queued by B while A attached last.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from agent_runtime import launcher_app_functions as laf
from tests.agent_runtime.test_launcher_app_functions import _TOOLS, _Launcher

_A_ONLY = {"name": "launcher_a_only_probe", "method": "launcher.a_only.probe",
           "description": "Only A declares this.", "parameters": {"type": "object", "properties": {}}}
_B_ONLY = {"name": "launcher_b_only_probe", "method": "launcher.b_only.probe",
           "description": "Only B declares this.", "parameters": {"type": "object", "properties": {}}}
_SHARED_A = dict(_TOOLS[1], parameters={"type": "object", "properties": {"page": {"type": "string"}}})
_SHARED_B = dict(_TOOLS[1], parameters={"type": "object", "properties": {"route": {"type": "string"}}})


@pytest.fixture(autouse=True)
def _clean():
    laf._reset_for_tests()
    yield
    laf._reset_for_tests()


def _definitions(link) -> dict[str, set[str]]:
    from model_tools import get_tool_definitions

    token = laf.bind_launcher_link(link)
    try:
        return {d["function"]["name"]: set(d["function"]["parameters"].get("properties", {}))
                for d in get_tool_definitions(enabled_toolsets=[laf.APP_FUNCTIONS_TOOLSET],
                                              quiet_mode=True, skip_tool_search_assembly=True)}
    finally:
        laf.reset_launcher_link(token)


def _two_launchers():
    """B declared first, A last: A is the most recent attach (the gateway rule's pick)."""

    a, b = _Launcher([_A_ONLY, _SHARED_A]), _Launcher([_B_ONLY, _SHARED_B])
    laf.declare_answerer("sock-b", True)
    laf.declare_answerer("sock-a", True)
    link_a, link_b = laf.LauncherLink(a, laf.ORIGIN_LOCAL), laf.LauncherLink(b, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link_b)
    laf.refresh_app_function_tools(link_a)
    session = SimpleNamespace(
        connection_sinks_lock=threading.Lock(),
        connection_sinks={"sock-a": a, "sock-b": b},
        _gateway_turn_launcher_sink=lambda: a,
        frames=None,
    )
    return a, b, link_a, session


def _queued_by(owner: str):
    from agent_runtime.chat_root_send_queue import ORIGIN_ARG

    return SimpleNamespace(args={ORIGIN_ARG: {"owner": owner, "gateway": False}})


def test_a_turn_queued_by_b_sees_bs_tools_while_a_attached_last():
    from hermes_cli.harness_parts.serve.queued_turn_origin import queued_turn_link

    _a, b, link_a, session = _two_launchers()

    queued = queued_turn_link(session, _queued_by("sock-b"))

    assert queued is not None and queued.sink is b
    seen = _definitions(queued)
    assert "launcher_b_only_probe" in seen
    assert "launcher_a_only_probe" not in seen
    assert seen[_TOOLS[1]["name"]] == {"route"}  # B's schema for the shared name
    # Positive control: a direct turn on A sees A's own tool and A's schema.
    direct = _definitions(link_a)
    assert "launcher_a_only_probe" in direct and direct[_TOOLS[1]["name"]] == {"page"}


def test_switching_between_attached_launchers_moves_no_registry_generation():
    from hermes_cli.harness_parts.serve.queued_turn_origin import queued_turn_link
    from tools.registry import registry

    _a, _b, link_a, session = _two_launchers()
    generation = registry.generation

    laf.refresh_app_function_tools(link_a)
    queued_turn_link(session, _queued_by("sock-b"))
    laf.refresh_app_function_tools(link_a)

    assert registry.generation == generation
