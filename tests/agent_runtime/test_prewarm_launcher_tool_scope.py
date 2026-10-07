"""An opening connection must survive catalog refresh into actor construction.

Regression: the catalog was registered on one thread, then the prewarm worker
constructed an actor without a LauncherLink. The registry correctly hid every
Launcher tool, and the next turn reused that incomplete actor.
"""

from __future__ import annotations

import json
import queue
import threading

import pytest

from tests._downstream.split_package_source import patch_where_bound
from tests.agent_runtime.test_launcher_app_functions import _Launcher
from tests.agent_runtime.test_persona_chat_actor_prewarm import (
    _Agent,
    _request,
    stub_runtime,  # noqa: F401 - fixture
)

from agent_runtime import launcher_app_functions as app
from agent_runtime import persona_chat_actor_prewarm as prewarm
from agent_runtime import persona_chat_continuity
from agent_runtime.chat_lane_bundle import ChatLaneBundle
from agent_runtime.launcher_invocation import launcher_invocation
from agent_runtime.persona_chat_continuity import PersonaChatRuntimeRegistry
from agent_runtime.profile_runner import ProfileAgentRunner
from tools.registry import registry

_CREATE = {
    "name": "launcher_generated_create",
    "method": "launcher.generated.create",
    "description": "Create editable content in this conversation.",
    "parameters": {"type": "object", "properties": {
        "document_json": {"type": "string"}}, "required": ["document_json"]},
    "reach": "local",
}


def _tool_contract():
    return ChatLaneBundle(
        key="test", permission_mode="unbounded", permission_source="test",
        admission=None, enabled_toolsets=(app.APP_FUNCTIONS_TOOLSET,),
        blocked_tool_names=(), operating_skills=(), admission_line="",
        _capability={}, _tool_contract={"enabled_toolsets": [app.APP_FUNCTIONS_TOOLSET]},
        _permission_state={},
    )


class _WorkerStopped(Exception):
    pass


class _TestQueue(queue.PriorityQueue):
    def get(self, *args, **kwargs):
        item = super().get(*args, **kwargs)
        if item[2] is None:
            raise _WorkerStopped
        return item


@pytest.fixture
def worker(monkeypatch):
    app._reset_for_tests()
    resident = PersonaChatRuntimeRegistry()
    patch_where_bound(monkeypatch, persona_chat_continuity,
                      "persona_chat_runtime_registry", lambda: resident)
    items = _TestQueue()
    monkeypatch.setattr(prewarm, "_queue", items)
    monkeypatch.setattr(prewarm, "_pending", {})
    monkeypatch.setattr(prewarm, "_links", {})
    monkeypatch.setattr(prewarm, "_running_root", None)
    monkeypatch.setattr(prewarm, "_running_priority", None)
    monkeypatch.setattr(prewarm, "_ensure_worker", lambda: None)
    finished = threading.Event()
    threads = []

    def run():
        try:
            prewarm._drain()
        except _WorkerStopped:
            pass

    def drain():
        thread = threading.Thread(target=run, daemon=True)
        threads.append(thread)
        thread.start()
        assert finished.wait(10), "prewarm worker did not complete the test item"

    yield resident, finished, drain
    for thread in threads:
        items.put((99, 99, None))
        thread.join(2)
        assert not thread.is_alive(), "test worker leaked into another fixture"
    app._reset_for_tests()


def test_first_turn_reuses_an_actor_with_callable_launcher_tools(worker, monkeypatch, stub_runtime):
    resident, finished, drain = worker
    launcher = _Launcher(tools=[_CREATE])
    link = app.LauncherLink(launcher, app.ORIGIN_LOCAL)
    actors = []
    contract = _tool_contract()
    boot_signature = json.dumps(contract.tool_contract(), sort_keys=True)
    prewarm_signatures = []

    class ToolAwareAgent(_Agent):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.tools = registry.get_definitions({_CREATE["name"]}, quiet=True)
            actors.append(self)

        def run_conversation(self, *args, **kwargs):
            self.answer = json.loads(registry.dispatch(_CREATE["name"], {"document_json": "[]"}))
            return super().run_conversation(*args, **kwargs)

    runner = ProfileAgentRunner(agent_factory=ToolAwareAgent)

    def construct(root):
        try:
            signature = json.dumps(contract.tool_contract(), sort_keys=True)
            prewarm_signatures.append(signature)
            runner.prewarm(_request(prewarm_only=True, registry=resident, signature=signature))
            return prewarm.OUTCOME_WARMED
        finally:
            finished.set()

    monkeypatch.setattr(prewarm, "prewarm_chat_actor", construct)
    assert prewarm.request_chat_actor_prewarm("chat_root_1", launcher_link=link) == "started"
    drain()
    assert [tool["function"]["name"] for tool in actors[0].tools] == [_CREATE["name"]]

    token = app.bind_launcher_link(link)
    try:
        with launcher_invocation("operator", "chat_root_1", "turn_1", client_scope="account-a"):
            signature = json.dumps(contract.tool_contract(), sort_keys=True)
            assert signature == prewarm_signatures[0]
            assert signature != boot_signature, "a connection-less boot actor must not be reused"
            result = runner.run(_request(prewarm_only=False, registry=resident, signature=signature))
    finally:
        app.reset_launcher_link(token)

    assert len(actors) == 1, "fixing tool availability must not throw the prewarm away"
    assert result.profile_timing["resident_actor_reused"] == 1
    assert actors[0].answer["data"]["echo"]["_meta"]["invocation"] == {
        "channel": "operator", "session_id": "chat_root_1", "turn_id": "turn_1",
        "client_scope": "account-a",
    }
    assert [frame["method"] for frame in launcher.sent] == [app.LIST_METHOD, _CREATE["method"]]


def test_a_linked_item_does_not_leak_its_connection_into_boot_work(worker, monkeypatch):
    """Positive control: registration alone never grants Launcher access."""
    _, finished, drain = worker
    launcher = _Launcher(tools=[_CREATE])
    link = app.LauncherLink(launcher, app.ORIGIN_LOCAL)
    observed = []

    def construct(root):
        observed.append((root, app.current_launcher_link(),
                         registry.get_definitions({_CREATE["name"]}, quiet=True)))
        if root == "linked":
            raise RuntimeError("construction failed")
        if root == "boot":
            finished.set()
        return prewarm.OUTCOME_WARMED

    monkeypatch.setattr(prewarm, "prewarm_chat_actor", construct)
    prewarm.request_chat_actor_prewarm("linked", launcher_link=link)
    prewarm.request_chat_actor_prewarm("boot", priority=prewarm.PRIORITY_BOOT)
    drain()
    assert observed[0][1] is link
    assert observed[0][2], "the linked construction must offer its tool"
    assert observed[1] == ("boot", None, [])
    assert app.current_launcher_link() is None


def test_reopening_a_running_chat_does_not_retain_its_link_for_later_boot(worker, monkeypatch):
    """A duplicate open may refresh tools, but cannot lend its link to boot work."""
    _, finished, drain = worker
    launcher = _Launcher(tools=[_CREATE])
    link = app.LauncherLink(launcher, app.ORIGIN_LOCAL)
    observed = []

    def construct(root):
        observed.append((root, app.current_launcher_link(),
                         registry.get_definitions({_CREATE["name"]}, quiet=True)))
        if len(observed) == 1:
            assert prewarm.request_chat_actor_prewarm(root, launcher_link=link) == "already_running"
            late_preparation = prewarm._links[root]
            late_preparation.refresh.join(2)
            assert not late_preparation.refresh.is_alive(), "catalog refresh leaked from the fixture"
        finished.set()
        return prewarm.OUTCOME_WARMED

    monkeypatch.setattr(prewarm, "prewarm_chat_actor", construct)
    assert prewarm.request_chat_actor_prewarm("reopened", launcher_link=link) == "started"
    drain()
    prewarm._queue.join()
    finished.clear()

    assert prewarm.request_chat_actor_prewarm("reopened", priority=prewarm.PRIORITY_BOOT) == "started"
    assert finished.wait(10), "later boot work did not complete"
    prewarm._queue.join()
    assert observed[0][1] is link
    assert observed[0][2], "positive control: linked construction offers its tool"
    assert observed[1] == ("reopened", None, [])
    assert prewarm._links == {}, "completed work must release even a late opening link"
    assert app.current_launcher_link() is None
