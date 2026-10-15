"""Owned commands through the actual worker/operator dispatch and native helpers."""
import threading
import weakref
from contextlib import closing
from types import SimpleNamespace

import pytest

from agent.interrupt_control import InterruptControlMixin
from agent_runtime.subagents.commands import CommandReceipts
from tests.agent_runtime.test_subagent_worker_ownership import gateway, request
from tools.delegate_tool_child_run import _register_child
from tools.delegate_tool_registry import _unregister_subagent
from tests.agent_runtime.test_serve_rpc_open_chat import qa_persona, placed_agent
from tests.agent_runtime.test_instance_conversation_owner import chat_head


class Child(InterruptControlMixin):
    def __init__(self, key, parent=None):
        self._subagent_id, self._delegate_depth, self.model = key, 1, "test"
        self._execution_thread_id = None
        self.quiet_mode = True
        self._active_children_lock = threading.Lock()
        self._active_children = []
        self._pending_steer_lock = threading.Lock()
        self._pending_steer = None
        self._interrupt_requested = False
        if parent:
            self._delegate_parent_ref = weakref.ref(parent)
            parent._active_children.append(self)


def register(owner, transport, key="child", parent=None):
    child = Child(key, parent)
    _register_child(child, None, "task", owner_session_id="ui-owner",
                    owner_transport=transport, owner_session_record=owner)
    return child


def guard(call, key="child"):
    roster = request(call, "list")["result"]["data"]
    row = next(c for c in roster["children"] if c["subagent_id"] == key)
    assert row["controllable"]
    return {"child_ref": row["child_ref"], "expected_generation": roster["generation"]}


@pytest.fixture(autouse=True)
def fresh_receipts(monkeypatch):
    from agent_runtime.subagents import commands
    monkeypatch.setattr(commands, "commands", CommandReceipts())


def test_steer_is_queued_once_and_stop_preserves_parent_and_sibling(gateway):
    _, owner, transport, call = gateway
    parent = Child("parent")
    child = register(owner, transport, parent=parent)
    grandchild = register(owner, transport, "grandchild", child)
    sibling = register(owner, transport, "sibling", parent)
    selected = guard(call)
    payload = {**selected, "request_id": "steer-once", "text": "check ownership"}
    assert request(call, "steer", **payload)["result"]["data"]["status"] == "queued"
    assert request(call, "steer", **payload)["result"]["data"]["status"] == "queued"
    assert str(child._drain_pending_steer()) == "check ownership"
    assert "error" in request(call, "steer", **{**payload, "text": "different"})
    assert request(call, "receipt", **selected, request_id="steer-once")["result"]["data"]["status"] == "queued"
    assert request(call, "stop", **selected, request_id="stop-once")["result"]["data"]["status"] == "interrupt_requested"
    assert child._interrupt_requested and grandchild._interrupt_requested
    assert not parent._interrupt_requested and not sibling._interrupt_requested


@pytest.mark.parametrize("operation", ["steer", "stop"])
def test_mutation_rechecks_exact_record_at_native_acceptance(gateway, monkeypatch, operation):
    from tools import delegate_tool_registry as registry
    _, owner, transport, call = gateway
    child = register(owner, transport)
    selected = guard(call)
    original = getattr(registry, "steer_subagent" if operation == "steer" else "interrupt_subagent")
    replacements = []

    def race(*args, **kwargs):
        _unregister_subagent("child", agent=child)
        replacements.append(register(owner, transport))
        return original(*args, **kwargs)

    monkeypatch.setattr(registry, "steer_subagent" if operation == "steer" else "interrupt_subagent", race)
    reply = request(call, operation, **selected, request_id="race", **({"text": "wrong child"} if operation == "steer" else {}))
    assert "error" in reply
    assert replacements[0]._pending_steer is None and not replacements[0]._interrupt_requested
    # The same replacement is controllable with a freshly issued guard.
    monkeypatch.setattr(registry, "steer_subagent" if operation == "steer" else "interrupt_subagent", original)
    fresh = request(call, operation, **guard(call), request_id="fresh", **({"text": "right child"} if operation == "steer" else {}))
    assert fresh["result"]["data"]["status"] in {"queued", "interrupt_requested"}


def test_changed_transport_wrong_reference_and_closed_steering_refuse(gateway):
    from tools.delegate_tool_registry import _close_subagent_steering
    _, owner, transport, call = gateway
    child = register(owner, transport)
    selected = guard(call)
    foreign = SimpleNamespace(write=lambda _: True)
    assert "error" in request(call, "stop", via=foreign, **selected, request_id="foreign")
    assert "error" in request(call, "steer", **{**selected, "child_ref": "forged"}, request_id="forged", text="no")
    _close_subagent_steering("child", child)
    reply = request(call, "steer", **selected, request_id="closed", text="late")
    assert reply["result"]["data"]["status"] == "not_accepting"
    owner["transport"] = foreign
    assert "error" in request(call, "stop", via=foreign, **selected, request_id="new-transport")
    assert not child._interrupt_requested


def test_receipt_capacity_never_evicts_a_replayable_live_command(gateway, monkeypatch):
    from agent_runtime.subagents import commands
    monkeypatch.setattr(commands, "commands", CommandReceipts(limit=1))
    _, owner, transport, call = gateway
    child = register(owner, transport)
    selected = guard(call)
    payload = {**selected, "request_id": "first", "text": "once"}
    assert request(call, "steer", **payload)["result"]["data"]["status"] == "queued"
    assert "error" in request(call, "steer", **{**payload, "request_id": "second"})
    request(call, "steer", **payload)
    assert str(child._drain_pending_steer()) == "once"


def test_owner_changed_after_native_acceptance_is_unknown_not_rejected(gateway):
    _, owner, transport, call = gateway
    child = register(owner, transport)
    selected = guard(call)
    native_steer = child.steer

    def detach(text):
        accepted = native_steer(text)
        owner["transport"] = SimpleNamespace(write=lambda _: True)
        return accepted

    child.steer = detach
    reply = request(call, "steer", **selected, request_id="late-owner", text="accepted")
    assert reply["error"]["data"]["reason"] == "subagent_outcome_unknown"
    assert str(child._drain_pending_steer()) == "accepted"


def test_operator_unclassified_failure_cannot_claim_a_command_did_not_run(monkeypatch):
    from agent_runtime.serve_rpc import operator_subagents

    def failure(*_):
        raise RuntimeError("outcome not available")

    monkeypatch.setattr(operator_subagents, "inspect_operator", failure)
    for operation in ("steer", "stop"):
        reply = operator_subagents._subagent_reply(operation, 1, {})
        assert reply["error"]["data"]["reason"] == "subagent_outcome_unknown"
    assert operator_subagents._subagent_reply("list", 1, {})["error"]["data"]["reason"] == "subagent_unavailable"


def test_operator_mutations_require_current_live_parent(placed_agent, tmp_path):
    from agent_runtime.live_turns import live_turn
    from agent_runtime.persona_chat_durability import default_persona_session_db
    from tests.agent_runtime.test_operator_session_inspection import target, inspect

    params = target(placed_agent["persona_instance_id"])
    parent = Child("parent")
    parent.session_id = params["session_id"]
    child = Child("operator-child", parent)
    with closing(default_persona_session_db()) as db:
        from pathlib import Path
        child._session_db, child.logs_dir = db, Path(db.db_path).parent / "sessions"
        _register_child(child, parent, "task", owner_session_id=None, owner_transport=None, owner_session_record=None)
        try:
            roster = inspect("subagents.list", params)["result"]
            assert not roster["children"][0]["controllable"]
            selected = {**params, "child_ref": roster["children"][0]["child_ref"],
                        "expected_generation": roster["generation"], "request_id": "operator"}
            assert "error" in inspect("subagents.stop", selected)
            with live_turn(turn_id="proof", session_id=params["session_id"],
                           persona_instance_id=params["persona_instance_id"], agent=parent):
                assert inspect("subagents.list", params)["result"]["children"][0]["controllable"]
                from agent_runtime.call_authorization import UNKNOWN_CALLER
                from tests.agent_runtime.test_serve_rpc_open_chat import _device
                from tests.agent_runtime.test_instance_conversation_owner import OTHER
                for key, value in (("install_id", "other"), ("workspace_id", "other"),
                                   ("persona_id", "other"), ("persona_instance_id", "other"),
                                   ("session_id", "other"), ("client_scope", OTHER)):
                    assert "error" in inspect("subagents.stop", {**selected, key: value})
                for caller in (_device("read"), UNKNOWN_CALLER):
                    assert "error" in inspect("subagents.stop", selected, caller)
                assert not child._interrupt_requested
                assert inspect("subagents.stop", selected)["result"]["status"] == "interrupt_requested"
            assert child._interrupt_requested and not parent._interrupt_requested
        finally:
            _unregister_subagent("operator-child", agent=child)
