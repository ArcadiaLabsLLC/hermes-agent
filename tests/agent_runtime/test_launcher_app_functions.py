"""The Launcher's app functions as agent tools (Stage 7 harness half).

Contract: launcher ``docs/embedded_hermes/planned/IMPLEMENTATION_2026-09-28.md``,
"Stage 7 launcher half as landed" — ``launcher.app_functions.list`` returns
``{"tools": [{name, method, description, parameters}, ...]}``; a call is a
request whose method is the entry's ``method`` and whose ``params._meta.origin``
is ``local`` or ``paired_device``.
"""

from __future__ import annotations

import json
import threading

import pytest

from agent_runtime import launcher_app_functions as laf
from hermes_cli.harness_parts.serve.argv_lane import _ArgvRequest
from hermes_cli.harness_parts.serve.handle_message import MessageHandling
from hermes_cli.harness_parts.serve.lanes import ArgvLanes
from hermes_cli.harness_parts.serve.subscriptions import SubscriptionLanes

_TOOLS = [
    {
        "name": "launcher_library_list",
        "method": "launcher.library.list",
        "description": "List the library.",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}},
        "reach": "paired_device",
    },
    {
        "name": "launcher_navigation_open",
        "method": "launcher.navigation.open",
        "description": "Open a page.",
        "parameters": {"type": "object", "properties": {"page": {"type": "string"}}},
    },
]


class _Launcher:
    """A sink that answers like the Launcher's serve responder, on another thread."""

    def __init__(self, tools=None, *, silent=False, refuse=None):
        self.tools = _TOOLS if tools is None else tools
        self.silent = silent
        self.refuse = refuse or set()
        self.sent: list[dict] = []

    def emit(self, frame):
        self.sent.append(frame)
        if self.silent or "method" not in frame:
            return
        threading.Thread(target=laf.resolve_response, args=(self._answer(frame), self)).start()

    def _answer(self, frame):
        method = frame["method"]
        if method == laf.LIST_METHOD:
            return {"jsonrpc": "2.0", "id": frame["id"], "result": {"tools": self.tools}}
        if method in self.refuse:
            return {"jsonrpc": "2.0", "id": frame["id"],
                    "error": {"code": -32010, "message": "refused", "data": {"refusal": "permission_refused"}}}
        return {"jsonrpc": "2.0", "id": frame["id"], "result": {"data": {"echo": frame["params"]}}}


@pytest.fixture(autouse=True)
def _clean():
    laf._reset_for_tests()
    yield
    laf._reset_for_tests()


def _call(name: str, args: dict, link: laf.LauncherLink) -> dict:
    from tools.registry import registry

    token = laf.bind_launcher_link(link)
    try:
        return json.loads(registry.dispatch(name, args))
    finally:
        laf.reset_launcher_link(token)


def test_list_registers_one_tool_per_entry_with_the_given_schema():
    from tools.registry import registry

    launcher = _Launcher()
    names = laf.refresh_app_function_tools(laf.LauncherLink(launcher, laf.ORIGIN_LOCAL))

    assert names == ["launcher_library_list", "launcher_navigation_open"]
    assert launcher.sent[0]["method"] == laf.LIST_METHOD
    assert launcher.sent[0]["id"].startswith("lrq-")
    entry = registry.get_entry("launcher_library_list")
    assert entry.toolset == laf.APP_FUNCTIONS_TOOLSET
    assert entry.schema["parameters"] == _TOOLS[0]["parameters"]
    assert entry.schema["description"] == "List the library."


@pytest.mark.parametrize("origin", [laf.ORIGIN_LOCAL, laf.ORIGIN_PAIRED_DEVICE])
def test_a_call_sends_the_entry_method_with_the_turn_origin(origin):
    launcher = _Launcher()
    link = laf.LauncherLink(launcher, origin)
    laf.refresh_app_function_tools(link)

    result = _call("launcher_library_list", {"limit": 3}, link)

    request = launcher.sent[-1]
    assert request["method"] == "launcher.library.list"
    assert request["params"] == {"limit": 3, "_meta": {"origin": origin}}
    assert result == {"data": {"echo": {"limit": 3, "_meta": {"origin": origin}}}}


def test_a_model_supplied_meta_cannot_restate_the_origin():
    launcher = _Launcher()
    link = laf.LauncherLink(launcher, laf.ORIGIN_PAIRED_DEVICE)
    laf.refresh_app_function_tools(link)

    _call("launcher_library_list", {"_meta": {"origin": "local"}}, link)

    assert launcher.sent[-1]["params"]["_meta"] == {"origin": laf.ORIGIN_PAIRED_DEVICE}


def test_a_refusal_reaches_the_model_as_the_tool_result():
    launcher = _Launcher(refuse={"launcher.navigation.open"})
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)

    result = _call("launcher_navigation_open", {"page": "library"}, link)

    assert result["refusal"] == "permission_refused"
    assert result["code"] == -32010


def test_a_call_with_no_link_bound_sends_nothing():
    launcher = _Launcher()
    laf.refresh_app_function_tools(laf.LauncherLink(launcher, laf.ORIGIN_LOCAL))
    sent = len(launcher.sent)

    from tools.registry import registry

    assert "no Launcher" in json.loads(registry.dispatch("launcher_library_list", {}))["error"]
    assert len(launcher.sent) == sent


def test_a_silent_connection_is_probed_once(monkeypatch):
    monkeypatch.setattr(laf, "LIST_TIMEOUT_SECONDS", 0.05)
    silent = _Launcher(silent=True)
    link = laf.LauncherLink(silent, laf.ORIGIN_LOCAL)

    assert laf.refresh_app_function_tools(link) is None
    assert laf.refresh_app_function_tools(link) is None
    assert len(silent.sent) == 1
    assert laf.CLIENT_REQUESTS.open_count() == 0


def test_the_same_list_again_does_not_move_the_registry_epoch():
    from tools.registry import registry_epoch

    link = laf.LauncherLink(_Launcher(), laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    epoch = registry_epoch()
    laf.refresh_app_function_tools(link)
    assert registry_epoch() == epoch


def test_an_entry_the_launcher_drops_is_deregistered():
    from tools.registry import registry

    launcher = _Launcher()
    link = laf.LauncherLink(launcher, laf.ORIGIN_LOCAL)
    laf.refresh_app_function_tools(link)
    launcher.tools = _TOOLS[:1]
    laf.refresh_app_function_tools(link)

    assert registry.get_entry("launcher_navigation_open") is None
    assert registry.get_entry("launcher_library_list") is not None


def test_an_entry_outside_the_launcher_namespace_is_never_registered():
    from tools.registry import registry

    tools = [{"name": "terminal_again", "method": "terminal.run", "parameters": {}}, _TOOLS[0]]
    names = laf.refresh_app_function_tools(laf.LauncherLink(_Launcher(tools), laf.ORIGIN_LOCAL))

    assert names == ["launcher_library_list"]
    assert registry.get_entry("terminal_again") is None


def test_a_response_on_another_connection_settles_nothing():
    asked, other = _Launcher(silent=True), _Launcher(silent=True)
    result: dict = {}
    waiter = threading.Thread(
        target=lambda: result.update(laf.CLIENT_REQUESTS.request(asked, "launcher.x", {}, timeout=5)))
    waiter.start()
    while not asked.sent:
        pass
    frame = {"jsonrpc": "2.0", "id": asked.sent[0]["id"], "result": {"from": "asked"}}
    assert laf.resolve_response({**frame, "result": {"from": "other"}}, other) is False
    assert laf.resolve_response(frame, asked) is True  # positive control: same frame, the asking sink
    waiter.join()
    assert result == {"from": "asked"}


def test_the_serve_dispatcher_routes_a_response_frame_and_answers_nothing():
    asked = _Launcher(silent=True)
    result: dict = {}
    waiter = threading.Thread(
        target=lambda: result.update(laf.CLIENT_REQUESTS.request(asked, "launcher.x", {}, timeout=2)),
        daemon=True)
    waiter.start()
    while not asked.sent:
        pass
    before = len(asked.sent)
    frame = {"jsonrpc": "2.0", "id": asked.sent[0]["id"], "result": {"data": 1}}

    class _Dispatcher:
        lanes: list[str] = []

        def _dispatch_rpc(self, *_):
            self.lanes.append("rpc")

        def _dispatch_argv_request(self, *_):
            self.lanes.append("argv")

    assert MessageHandling._handle_request(_Dispatcher(), frame, asked, None) is None

    waiter.join()
    assert _Dispatcher.lanes == []  # neither lane saw the response
    assert result == {"data": 1}
    assert len(asked.sent) == before  # no error frame answered the response


class _Lanes(ArgvLanes, SubscriptionLanes):

    def __init__(self, frames):
        self.frames = frames


_CHAT_ARGV = ["harness", "mission-chat", "message", "--persona", "p", "--message", "hi"]


def _declare(owner: str, answers=("launcher.",)) -> dict:
    from agent_runtime.serve_rpc.client import _runtime_client_capabilities
    from agent_runtime.serve_rpc.protocol import RpcContext

    return _runtime_client_capabilities(
        "c1", {"answers": list(answers)}, RpcContext(connection_key=None if owner == "stdio" else owner))


def test_an_undeclared_connection_never_sees_a_launcher_request():
    client = _Launcher()
    request = _ArgvRequest("r", _CHAT_ARGV, owner="sock-1", sink=client)
    assert ArgvLanes._bind_launcher_link(_Lanes(_Launcher()), request, client) is None
    assert client.sent == []
    assert _declare("sock-1")["result"]["answers"] == ["launcher."]  # positive control: declared, asked
    token = ArgvLanes._bind_launcher_link(_Lanes(_Launcher()), request, client)
    laf.reset_launcher_link(token)
    assert client.sent[0]["method"] == laf.LIST_METHOD


def test_a_declaration_can_be_withdrawn():
    _declare("stdio")
    assert laf.answers_launcher_requests("stdio")
    _declare("stdio", answers=())
    assert not laf.answers_launcher_requests("stdio")


def test_a_local_chat_turn_binds_its_own_connection_as_local():
    assert _ArgvRequest("r", _CHAT_ARGV).is_chat_turn
    stdio, socket_client = _Launcher(), _Launcher()
    _declare("sock-1")
    request = _ArgvRequest("r", _CHAT_ARGV, owner="sock-1", sink=socket_client)
    token = ArgvLanes._bind_launcher_link(_Lanes(stdio), request, socket_client)
    try:
        link = laf.current_launcher_link()
        assert (link.sink, link.origin) == (socket_client, laf.ORIGIN_LOCAL)
    finally:
        laf.reset_launcher_link(token)
    assert socket_client.sent[0]["method"] == laf.LIST_METHOD
    assert stdio.sent == []


def test_a_gateway_turn_reaches_the_launcher_on_stdio_as_paired_device():
    stdio, device = _Launcher(), _Launcher()
    _declare("stdio")
    request = _ArgvRequest("r", _CHAT_ARGV, owner="gw-1", sink=device, from_gateway=True)
    token = ArgvLanes._bind_launcher_link(_Lanes(stdio), request, device)
    try:
        link = laf.current_launcher_link()
        assert (link.sink, link.origin) == (stdio, laf.ORIGIN_PAIRED_DEVICE)
    finally:
        laf.reset_launcher_link(token)
    assert device.sent == []


def test_a_non_chat_request_binds_nothing():
    stdio = _Launcher()
    _declare("stdio")
    assert ArgvLanes._bind_launcher_link(_Lanes(stdio), _ArgvRequest("r", ["harness", "status"]), stdio) is None
    assert stdio.sent == []


def test_the_chat_lane_adds_the_toolset_only_once_a_launcher_listed_it():
    from agent_runtime.chat_lane_bundle import _augment_chat_capabilities

    assert laf.APP_FUNCTIONS_TOOLSET not in _augment_chat_capabilities(None, [])
    laf.refresh_app_function_tools(laf.LauncherLink(_Launcher(), laf.ORIGIN_LOCAL))
    assert laf.APP_FUNCTIONS_TOOLSET in _augment_chat_capabilities(None, [])


class _SocketLanes(_Lanes):
    def __init__(self, frames, sinks):
        super().__init__(frames)
        self.connection_sinks = dict(sinks)
        self.connection_sinks_lock = threading.Lock()


class _DetachedStdio(_Launcher):
    detached = True


def test_a_gateway_turn_reaches_a_socket_attached_launcher_when_stdio_is_detached():
    stdio, device, other, socket_client = _DetachedStdio(), _Launcher(), _Launcher(), _Launcher()
    _declare("stdio")
    request = _ArgvRequest("r", _CHAT_ARGV, owner="gw-1", sink=device, from_gateway=True)
    lanes = _SocketLanes(stdio, {"sock-0": other, "sock-1": socket_client})
    assert ArgvLanes._bind_launcher_link(lanes, request, device) is None  # positive control: nobody declared on a socket
    _declare("sock-1")
    token = ArgvLanes._bind_launcher_link(lanes, request, device)
    try:
        link = laf.current_launcher_link()
        assert (link.sink, link.origin) == (socket_client, laf.ORIGIN_PAIRED_DEVICE)
    finally:
        laf.reset_launcher_link(token)
    assert socket_client.sent[0]["method"] == laf.LIST_METHOD
    assert stdio.sent == device.sent == other.sent == []


def test_a_gateway_turn_asks_the_most_recent_socket_declaration():
    first, second = _Launcher(), _Launcher()
    _declare("sock-2")
    _declare("sock-1")
    lanes = _SocketLanes(_DetachedStdio(), {"sock-1": first, "sock-2": second})
    request = _ArgvRequest("r", _CHAT_ARGV, owner="gw-1", sink=_Launcher(), from_gateway=True)
    laf.reset_launcher_link(ArgvLanes._bind_launcher_link(lanes, request, request.sink))
    assert first.sent and not second.sent


def test_native_requester_keeps_its_admitting_connection_and_proven_origin():
    from types import SimpleNamespace

    client, replacement = _Launcher(), _Launcher()
    lanes = _Lanes(client)
    assert lanes._launcher_requester(None, client) is None
    _declare("stdio")
    request = lanes._launcher_requester(None, client)
    lanes.frames = replacement
    result = request("launcher.generated.create", {"_meta": {"origin": "paired_device"}})
    assert result["data"]["echo"]["_meta"] == {"origin": "local"}
    assert not replacement.sent
    remote = SimpleNamespace(key="gw-1", transport="gateway")
    request = lanes._launcher_requester(remote, _Launcher())
    assert request is not None
    result = request("launcher.generated.create", {"_meta": {"origin": "local"}})
    assert result["data"]["echo"]["_meta"] == {"origin": "paired_device"}
