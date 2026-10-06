"""h-chatperf: the chat-open prewarm builds the actor the first turn will reuse,
and when it cannot, the waste is recorded as the prewarm's outcome.

Cold turn ``1e4c06ba`` (2026-10-03): the prewarm built an actor with 61 deferred
tools, the turn built one with 71, and ``resident_signature_diff
components=tool_contract`` threw the prewarm away. The only key component that
moved was ``registry_epoch``: the turn's first request on its Launcher
connection had registered the connection's app functions
(``serve.lanes._bind_launcher_link``), and ``_augment_chat_capabilities`` adds
``launcher_app_functions`` to the chat lane only once they are registered.

Pinned:
1. the prewarm worker refreshes the opening connection's app functions BEFORE
   it prepares (so its tool contract is the turn's);
2. both open-chat doors hand the prewarm that link -- the method lane through
   ``launcher_link_of``, the argv lane by binding it (without a wire request on
   the reader thread);
3. a first turn that discards an unused prewarmed actor records it: the
   prewarm receipt line, and ``resident_rebuild_prewarm_discarded`` on the
   turn's timing.

Named sabotage: delete ``_await_link_refresh(link)`` from ``_drain`` ->
``test_prewarm_order_downstream``'s wait row reds (the ask now leaves at the
gesture, so row 1's order alone no longer proves the wait); delete the ``self._prewarm_discards[...] =`` line in
``PersonaChatRuntimeRegistry.acquire`` -> row 3 reds.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.test_persona_chat_actor_prewarm import (  # noqa: F401 - fixture
    _Agent,
    _request,
    stub_runtime,
)

from agent_runtime import launcher_app_functions as app
from agent_runtime import persona_chat_actor_prewarm as prewarm_module
from agent_runtime import persona_chat_continuity
from agent_runtime.persona_chat_continuity import PersonaChatRuntimeRegistry
from agent_runtime.profile_runner import ProfileAgentRunner


@pytest.fixture(autouse=True)
def _clean():
    _Agent.constructed = 0
    with prewarm_module._lock:
        prewarm_module._pending.clear()
        prewarm_module._links.clear()
    yield
    with prewarm_module._lock:
        prewarm_module._pending.clear()
        prewarm_module._links.clear()


def test_the_worker_refreshes_the_opening_link_before_it_prepares(monkeypatch):
    order: list[str] = []
    link = app.LauncherLink(sink=object(), origin=app.ORIGIN_LOCAL)
    monkeypatch.setattr(app, "refresh_app_function_tools", lambda got: order.append(("refresh", got)))
    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", lambda root: order.append(("prewarm", root)) or "warmed")
    monkeypatch.setattr(prewarm_module, "_ensure_worker", lambda: None)
    registry = PersonaChatRuntimeRegistry()
    patch_where_bound(monkeypatch, persona_chat_continuity, "persona_chat_runtime_registry", lambda: registry)

    assert prewarm_module.request_chat_actor_prewarm("chat_root_1", launcher_link=link) == "started"
    worker = threading.Thread(target=prewarm_module._drain, daemon=True)
    worker.start()
    prewarm_module._queue.join()

    assert order == [("refresh", link), ("prewarm", "chat_root_1")], order


def test_a_prewarm_with_no_link_refreshes_nothing(monkeypatch):
    """Positive control: the boot pass has no connection and must not invent one."""

    order: list[str] = []
    monkeypatch.setattr(app, "refresh_app_function_tools", lambda got: order.append("refresh"))
    monkeypatch.setattr(prewarm_module, "prewarm_chat_actor", lambda root: order.append("prewarm") or "warmed")
    monkeypatch.setattr(prewarm_module, "_ensure_worker", lambda: None)
    registry = PersonaChatRuntimeRegistry()
    patch_where_bound(monkeypatch, persona_chat_continuity, "persona_chat_runtime_registry", lambda: registry)

    prewarm_module.request_chat_actor_prewarm("chat_root_2")
    worker = threading.Thread(target=prewarm_module._drain, daemon=True)
    worker.start()
    prewarm_module._queue.join()
    assert order == ["prewarm"]


def test_the_method_lane_recovers_the_link_behind_its_requester():
    link = app.LauncherLink(sink=object(), origin=app.ORIGIN_LOCAL)
    assert app.launcher_link_of(link.request) is link
    assert app.launcher_link_of(None) is None
    assert app.launcher_link_of(lambda method, args: {}) is None


def test_the_argv_open_chat_binds_the_link_without_a_wire_request(monkeypatch):
    from hermes_cli.harness_parts.serve import lanes

    refreshed: list[object] = []
    monkeypatch.setattr(lanes, "refresh_app_function_tools", lambda link: refreshed.append(link))
    link = app.LauncherLink(sink=object(), origin=app.ORIGIN_LOCAL)
    host = SimpleNamespace(_launcher_link=lambda owner, from_gateway, sink: link)
    request = SimpleNamespace(
        is_chat_turn=False, argv=["harness", "persona", "instance", "open-chat", "--persona-id", "dev"],
        owner="stdio", from_gateway=False,
    )
    token = lanes.ArgvLanes._bind_launcher_link(host, request, sink=None)
    try:
        assert app.current_launcher_link() is link
    finally:
        app.reset_launcher_link(token)
    assert refreshed == [], "the reader-side bind must never ask the Launcher anything"
    other = SimpleNamespace(is_chat_turn=False, argv=["harness", "snapshot"], owner="stdio", from_gateway=False)
    assert lanes.ArgvLanes._bind_launcher_link(host, other, sink=None) is None


def test_a_first_turn_that_discards_an_unused_prewarm_records_it(stub_runtime, caplog):
    registry = PersonaChatRuntimeRegistry()
    runner = ProfileAgentRunner(agent_factory=_Agent)
    runner.prewarm(_request(prewarm_only=True, registry=registry, signature="sig-prewarm",
                            persona_chat_runtime_signature_components={"tool_contract": "a"}))
    with caplog.at_level("INFO"):
        result = runner.run(_request(prewarm_only=False, registry=registry, signature="sig-turn",
                                     persona_chat_runtime_signature_components={"tool_contract": "b"}))

    assert result.profile_timing["resident_rebuild_prewarm_discarded"] == 1
    assert result.profile_timing["resident_rebuild_component_tool_contract"] == 1
    line = next(r.getMessage() for r in caplog.records if "outcome=discarded_signature_mismatch" in r.getMessage())
    assert "root=chat_root_1" in line and "components=tool_contract" in line
    assert registry.take_prewarm_discard("chat_root_1") is None, "reported on exactly one turn"


def test_a_turn_built_actor_that_moves_is_not_a_prewarm_discard(stub_runtime):
    """Positive control: the same signature move on an actor a TURN built."""

    registry = PersonaChatRuntimeRegistry()
    runner = ProfileAgentRunner(agent_factory=_Agent)
    runner.run(_request(prewarm_only=False, registry=registry, signature="sig-1"))
    result = runner.run(_request(prewarm_only=False, registry=registry, signature="sig-2"))
    assert result.profile_timing["resident_rebuild_runtime_signature_changed"] == 1
    assert "resident_rebuild_prewarm_discarded" not in result.profile_timing
