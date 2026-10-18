"""``serve_rpc.protocol.defer_or_inline`` — the one door for "run the reply on the worker lane, else answer inline".

Eleven method families hand-wrote the shape (RT-RPC-DEFER-OR-INLINE-HANDWRITTEN); each now goes through the
door. Every family's frame is pinned to the same BYTES on all three lanes (no worker lane, a lane that refuses
the deferral, an accepted deferral whose build the lane runs), and a source walk keeps the shape from being
hand-written again.

Killing mutations: hand-write the shape back into any family with a different inline frame (red in
``test_each_family_answers_the_same_bytes_on_every_lane``); call ``deferred_reply`` or ``.spawn_reply(`` from a
new module (red in ``test_only_the_doors_hand_a_build_to_the_worker_lane``).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from agent_runtime.call_authorization import STDIO_OWNER
from agent_runtime.serve_rpc import handle_request
from agent_runtime.serve_rpc.protocol import DEFERRED, RpcContext, ok

REPO = Path(__file__).resolve().parents[2]


class _Service:
    def load(self, _params):
        return {"pinned": "speech.load"}


def _pin(module: str, attr: str, value):
    return module, attr, value


def _frame(tag: str):
    return lambda rid, *_args, **_kwargs: ok(rid, {"pinned": tag})


def _result(tag: str):
    return lambda *_args, **_kwargs: {"pinned": tag}


#: (method, params, the patch that makes the family's builder answer ``{"pinned": tag}``, tag)
FAMILIES = [
    ("runtime.persona.instance.set_model", {}, _pin("console_operations", "_console_model", _result("console")),
     "console"),
    ("runtime.operator.conversation.list", {}, _pin("instance_history", "_list_reply", _frame("history.list")),
     "history.list"),
    ("runtime.operator.conversation.read", {}, _pin("operator_conversation", "_read_operator_reply",
                                                    _frame("conversation.read")), "conversation.read"),
    ("runtime.operator.conversation.undo.recover", {}, _pin("operator_history", "recover_operator_undo",
                                                            _result("undo.recover")), "undo.recover"),
    ("runtime.operator.conversation.undo.status", {}, _pin("operator_history", "operator_undo_status",
                                                           _result("undo.status")), "undo.status"),
    ("runtime.operator.conversation.subagents.list", {}, _pin("operator_subagents", "inspect_operator",
                                                              _result("subagents")), "subagents"),
    ("runtime.realm.sync.status", {}, _pin("realm", "_run_verb", _frame("realm")), "realm"),
    ("runtime.speech.load", {}, _pin("speech", "_service", lambda: _Service()), "speech.load"),
    ("runtime.default_model.set", {"provider": "p", "model": "m"},
     _pin("default_model", "_default_model_answer", _frame("default_model")), "default_model"),
    ("runtime.provider.list", {}, _pin("provider", "_answer", _frame("provider")), "provider"),
]


def _lanes():
    return {
        "no_lane": None,
        "lane_refused": lambda build: False,
    }


@pytest.mark.parametrize(("name", "params", "patch", "tag"), FAMILIES, ids=[f[0] for f in FAMILIES])
def test_each_family_answers_the_same_bytes_on_every_lane(monkeypatch, name, params, patch, tag):
    import importlib

    module, attr, value = patch
    monkeypatch.setattr(importlib.import_module(f"agent_runtime.serve_rpc.{module}"), attr, value)
    request = {"jsonrpc": "2.0", "id": "r1", "method": name, "params": params}
    pinned = '{"jsonrpc": "2.0", "id": "r1", "result": {"pinned": "' + tag + '"}}'

    for lane, spawn_reply in _lanes().items():
        frame = handle_request(request, RpcContext(caller=STDIO_OWNER, spawn_reply=spawn_reply))
        assert json.dumps(frame) == pinned, lane

    builds = []
    accepted = RpcContext(caller=STDIO_OWNER, spawn_reply=lambda build: builds.append(build) or True)
    assert handle_request(request, accepted) is DEFERRED
    assert json.dumps(builds.pop()()) == pinned


def test_the_door_runs_an_inline_build_inside_the_fault_boundary():
    from agent_runtime.serve_rpc.protocol import defer_or_inline

    def explode():
        raise RuntimeError("boom")

    frame = defer_or_inline("r1", "runtime.example", None, explode)
    assert frame["id"] == "r1" and frame["error"]["code"] == -32000
    assert frame["error"]["data"] == {"reason": "handler_failed", "method": "runtime.example"}


#: Modules that may hand a build to the worker lane themselves, each with why. Shrinks only.
_LANE_CALLERS = {
    "agent_runtime/serve_rpc/protocol.py": "the doors (defer_or_refuse, defer_or_inline)",
    "agent_runtime/serve_rpc/media.py": "its inline fallback dials a different path than its deferred build",
    "agent_runtime/serve_rpc/schedule.py": "hand-written defer-or-refuse; RT-RPC-DEFER-OR-REFUSE-STRAGGLERS",
    "agent_runtime/batch/rpc.py": "hand-written defer-or-refuse; RT-RPC-DEFER-OR-REFUSE-STRAGGLERS",
}


def _hands_a_build_to_the_lane(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "deferred_reply":
            return True
        if isinstance(func, ast.Attribute) and func.attr in {"spawn_reply", "deferred_reply"}:
            return True
    return False


def test_only_the_doors_hand_a_build_to_the_worker_lane():
    """A negative source walk: nothing outside :data:`_LANE_CALLERS` calls ``deferred_reply`` or ``.spawn_reply``."""

    found = set()
    for path in sorted((REPO / "agent_runtime").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "deferred_reply" not in source and "spawn_reply" not in source:
            continue
        if _hands_a_build_to_the_lane(ast.parse(source)):
            found.add(path.relative_to(REPO).as_posix())

    assert found == set(_LANE_CALLERS)
