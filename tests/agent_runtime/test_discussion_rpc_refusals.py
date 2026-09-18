"""Every refusal that reaches the wire carries a reason, never raw text.

``serve_rpc``'s generic boundary reports an uncaught handler exception as
``handler_failed`` with ``f"handler error: {exc}"``. Room-store and room-policy
errors are plain ValueError subclasses outside this module's own hierarchy, so
without an explicit arm they land there: unbranchable for a client and carrying
whatever the exception happened to say.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime.discussions import rpc
from gateway.hosted_room_discussion import DiscussionValidationError
from tests.agent_runtime.test_discussion_runtime import (  # noqa: F401 - pytest fixture
    begin,
    engine,
    settled,
    wait_until,
)

pytestmark = pytest.mark.timeout(180)


CONTEXT = SimpleNamespace(caller=SimpleNamespace(kind="console", device_id="device-1"))


def _handlers(service, monkeypatch) -> dict:
    """Bind the real RPC handlers, including their exception boundary."""
    registered: dict = {}

    def method(name, *, tier):
        def bind(fn):
            registered[name] = fn
            return fn

        return bind

    def ok(rid, result):
        return {"id": rid, "result": result}

    def err(rid, code, message, data):
        return {"id": rid, "error": {"code": code, "message": message, "data": data}}

    monkeypatch.setattr(rpc, "get_service", lambda: service)
    rpc.register(method, ok, err)
    return registered


CONTEXT = SimpleNamespace(caller=SimpleNamespace(kind="console", device_id="device-1"))


def test_run_get_maps_a_hosted_room_refusal_to_a_typed_reason(engine, monkeypatch):
    service, _ctx = engine
    run = begin(service)
    view = wait_until(lambda: settled(service, run))
    handler = _handlers(service, monkeypatch)["runtime.discussion.run.get"]
    params = {"workspace_id": "ws", "run_id": run["run_id"]}

    ahead = handler(1, {**params, "since_seq": view["log"]["latest_seq"] + 50}, CONTEXT)

    assert ahead["error"]["code"] == 4090
    assert ahead["error"]["data"] == {"reason": "room_unavailable"}
    # No raw exception text on the wire, and never the generic crash reason.
    assert "since_seq" not in ahead["error"]["message"]
    # Positive control: the same handler, same run, a cursor that is in range.
    assert handler(2, {**params, "since_seq": 0}, CONTEXT)["result"]["run"]["run_id"] == run["run_id"]


def test_run_get_maps_a_policy_validation_refusal_to_a_typed_reason(engine, monkeypatch):
    service, _ctx = engine
    run = begin(service)
    wait_until(lambda: settled(service, run))
    handler = _handlers(service, monkeypatch)["runtime.discussion.run.get"]
    params = {"workspace_id": "ws", "run_id": run["run_id"]}
    assert handler(1, params, CONTEXT)["result"]["run"]["run_id"] == run["run_id"]

    def malformed(*_args, **_kwargs):
        raise DiscussionValidationError("room roster member 'ops' is malformed")

    monkeypatch.setattr(service, "view", malformed)
    refused = handler(2, params, CONTEXT)

    assert refused["error"]["code"] == 4090
    assert refused["error"]["data"] == {"reason": "discussion_invalid"}
    assert "malformed" not in refused["error"]["message"]


def test_typed_definition_refusals_are_unchanged_by_the_new_arms(engine, monkeypatch):
    """The added arms sit BELOW the existing ones; ordering is the risk."""
    service, _ctx = engine
    handler = _handlers(service, monkeypatch)["runtime.discussion.table.get"]

    missing = handler(1, {"workspace_id": "ws", "table_id": "absent"}, CONTEXT)

    assert missing["error"]["code"] == -32602
    assert missing["error"]["data"]["reason"] == "definition_not_found"
