"""This device's virtual tree, asked of this device's Eternia with no turn bound.

Row ``RT-PHONE-FILES-THE-ENGINE-ASKS-THIS-DEVICES-ETERNIA-FOR-A-VIRTUAL-TREE-WITH-NO-TURN`` (Eternia
``MC-PHONE-FILES-THE-ENGINE-READS-ETERNIAS-VIRTUAL-TREES-BY-ASKING-ETERNIA``, plan
``PHONE_PROJECT_FOLDERS_FILE_TREE_2026-11-21`` §4 V1). Every call goes through the real dispatcher
(``handle_request``) with the caller the transport would stamp; each connection's Eternia is a sink
that answers the server→client request on the real lane (``CLIENT_REQUESTS``) and records what it
was asked, so a test can say what never left hermes.

Killing mutations (each red seen 2026-11-22):

* ``serve_rpc.client._runtime_client_capabilities``: hand every declaring caller's sink in as an
  owner sink, and a paired device's own Eternia is asked for this device's tree;
* ``launcher_app_functions.forget_launcher_connection``: keep a closed owner connection's sink, and
  the closed-Eternia test is answered instead of refused ``virtual_tree_unavailable``;
* ``serve_rpc.agent_files._runtime_agent_files_virtual``: declare the verb ``read`` tier, and a
  view-only device's write reaches Eternia;
* the same handler: ask with origin ``local`` for every caller, and Eternia is told a paired
  device's read is this device's owner's.
"""

from __future__ import annotations

import pytest

from agent_runtime import launcher_app_functions as app
from agent_runtime.call_authorization import (
    CALLER_DEVICE,
    REASON_SCOPE_DENIED,
    STDIO_OWNER,
    TIER_CONSOLE,
    TIER_READ,
    TRANSPORT_GATEWAY,
    RpcCaller,
)
from agent_runtime.launcher_client_requests import CLIENT_REQUESTS
from agent_runtime.project_files.rules import REFUSAL_CODES
from agent_runtime.serve_rpc.dispatch import handle_request
from agent_runtime.serve_rpc.protocol import RpcContext

VIRTUAL = "runtime.agent.files.virtual"
TREE = {"entries": [{"path": "/doc/components/calc/index.html", "chars": 120}]}


class _Eternia:
    """One connection's Eternia: answers each ``launcher.`` request at once, and remembers it."""

    def __init__(self) -> None:
        self.asked: list[dict] = []

    def emit(self, frame: dict) -> None:
        if str(frame.get("id", "")).startswith("lrq-"):
            self.asked.append(frame)
            CLIENT_REQUESTS.resolve({"jsonrpc": "2.0", "id": frame["id"], "result": TREE}, self)


def _device(tier: str, key: str = "dev-1") -> RpcCaller:
    return RpcCaller(kind=CALLER_DEVICE, connection_key=key, transport=TRANSPORT_GATEWAY,
                     device_id="dev_phone", device_tier=tier)


def _call(method: str, params: dict, *, caller: RpcCaller, sink: _Eternia | None = None,
          key: str | None = None) -> dict:
    return handle_request({"jsonrpc": "2.0", "id": "v1", "method": method, "params": params},
                          RpcContext(caller=caller, connection_key=key, emit=None if sink is None else sink.emit))


def _declare(caller: RpcCaller, sink: _Eternia, key: str | None, answers: list[str]) -> None:
    reply = _call("runtime.client.capabilities", {"answers": answers}, caller=caller, sink=sink, key=key)
    assert "result" in reply, reply


@pytest.fixture(autouse=True)
def _fresh_answerers():
    app._reset_for_tests()
    yield
    app._reset_for_tests()


def test_with_no_turn_the_owners_eternia_answers_and_learns_who_asked():
    owner = _Eternia()
    _declare(STDIO_OWNER, owner, None, ["launcher."])
    args = {"document_id": "doc-1", "path": "/doc/", "depth": 2}

    remote = _call(VIRTUAL, {"verb": "tree", "args": args}, caller=_device(TIER_CONSOLE))
    assert remote["result"] == TREE, remote
    local = _call(VIRTUAL, {"verb": "read", "args": {"path": "/doc/document.json"}}, caller=STDIO_OWNER)
    assert local["result"] == TREE, local

    assert [(f["method"], f["params"]["_meta"]["origin"]) for f in owner.asked] == [
        ("launcher.generated.tree", "paired_device"), ("launcher.generated.read", "local")]
    assert {k: v for k, v in owner.asked[0]["params"].items() if k != "_meta"} == args


def test_a_paired_devices_own_eternia_is_never_asked_for_this_devices_tree():
    phone = _Eternia()
    _declare(_device(TIER_CONSOLE), phone, "dev-1", ["launcher."])

    reply = _call(VIRTUAL, {"verb": "tree", "args": {}}, caller=_device(TIER_CONSOLE))
    assert reply["error"]["data"] == {"reason": "virtual_tree_unavailable"}, reply
    assert reply["error"]["message"] == "Eternia is not open on this device."
    assert phone.asked == []


def test_with_eternia_closed_the_read_refuses_virtual_tree_unavailable():
    owner = _Eternia()
    _declare(STDIO_OWNER, owner, None, ["launcher."])
    app.forget_launcher_connection(owner)
    assert _call(VIRTUAL, {"verb": "grep", "args": {"pattern": "x"}},
                 caller=_device(TIER_CONSOLE))["error"]["data"] == {"reason": "virtual_tree_unavailable"}
    # A withdrawn declaration is the same: nothing on this device answers.
    _declare(STDIO_OWNER, owner, None, ["launcher."])
    _declare(STDIO_OWNER, owner, None, [])
    assert _call(VIRTUAL, {"verb": "tree", "args": {}},
                 caller=_device(TIER_CONSOLE))["error"]["data"] == {"reason": "virtual_tree_unavailable"}
    assert owner.asked == []
    assert "virtual_tree_unavailable" in REFUSAL_CODES


@pytest.mark.parametrize("verb", ["patch", "write", "move", "read"])
def test_a_view_only_devices_call_is_refused_before_any_request_leaves_hermes(verb):
    owner = _Eternia()
    _declare(STDIO_OWNER, owner, None, ["launcher."])

    reply = _call(VIRTUAL, {"verb": verb, "args": {"path": "/doc/a.luau", "read_version": "r1"}},
                  caller=_device(TIER_READ))
    assert reply["error"]["data"] == {"reason": REASON_SCOPE_DENIED, "tier": TIER_CONSOLE,
                                      "caller": CALLER_DEVICE}, reply
    assert owner.asked == []


def test_a_verb_outside_the_virtual_trees_is_refused_and_nothing_is_asked():
    owner = _Eternia()
    _declare(STDIO_OWNER, owner, None, ["launcher."])
    for params in ({"verb": "create", "args": {}}, {"verb": "tree", "args": "/doc"}):
        reply = _call(VIRTUAL, params, caller=_device(TIER_CONSOLE))
        assert reply["error"]["data"]["reason"] == "bad_argument", reply
    assert owner.asked == []
