"""Exercise the registered worker door against native session and child owners."""
import json
from types import SimpleNamespace

import pytest

from tools.delegate_tool_child_run import _register_child
from tools.delegate_tool_registry import _unregister_subagent
from tools.delegation_live_log import LiveTranscriptWriter
from tests.tui_gateway.test_subagent_snapshot import runtime as gateway
from tests.agent_runtime.test_native_conversation import runtime as conversations, opened


class Child:
    def __init__(self, key):
        self._subagent_id, self._delegate_depth, self.model = key, 1, "actual-model"


def registered(owner, transport, key="child"):
    child = Child(key)
    _register_child(child, None, "Review api_key=secret123", owner_session_id="ui-owner",
                    owner_transport=transport, owner_session_record=owner)
    return child


def request(call, operation, **params):
    return call("eternia.subagents." + operation, owner_scope="owned-route",
                worker_generation="worker-1", **params)


def test_native_owner_generation_and_recycled_child(gateway, tmp_path):
    server, owner, transport, call = gateway
    assert request(call, "capabilities")["result"]["data"]["operations"] == ["list", "tail", "steer", "stop", "receipt"]
    assert "error" in request(call, "history")
    child = registered(owner, transport)
    writer = LiveTranscriptWriter("delegation", 0, "task", root=tmp_path)
    child._live_transcript_path = str(writer.path)
    writer.thinking("HIDDEN_REASONING")
    writer.assistant_text("Visible progress")
    writer.tool_result("terminal", "token=private-value")
    roster = request(call, "list")["result"]["data"]
    ref = roster["children"][0]["child_ref"]
    assert roster["children"][0]["model"] == "actual-model"
    assert "secret123" not in json.dumps(roster)
    params = dict(child_ref=ref, expected_generation=roster["generation"])
    tail = request(call, "tail", **params)["result"]["data"]
    assert "Visible progress" in tail["text"]
    assert "HIDDEN_REASONING" not in tail["text"] and "private-value" not in tail["text"]
    assert "path" not in tail
    assert "error" in request(call, "tail", **{**params, "expected_generation": "stale"})
    assert "error" in request(call, "tail", via=SimpleNamespace(write=lambda _: True), **params)
    old = child
    _unregister_subagent("child", agent=child)
    child = registered(owner, transport)
    assert child is not old
    assert "error" in request(call, "tail", **params)
    server._sessions["ui-owner"] = {**owner}
    assert "error" in request(call, "list", expected_generation=roster["generation"])


def test_child_replaced_during_tail_never_returns_new_or_old_output(gateway, monkeypatch):
    from agent_runtime.subagents import native
    _, owner, transport, call = gateway
    child = registered(owner, transport)
    roster = request(call, "list")["result"]["data"]
    replacement = []

    def racing_read(agent):
        assert agent is child
        _unregister_subagent("child", agent=child)
        replacement.append(registered(owner, transport))
        return {"available": True, "text": "stale output", "truncated": False}

    monkeypatch.setattr(native, "read_public_tail", racing_read)
    result = request(call, "tail", child_ref=roster["children"][0]["child_ref"],
                     expected_generation=roster["generation"])
    assert "error" in result and "stale output" not in json.dumps(result)


def test_tail_drops_partial_unknown_and_thinking_lines(tmp_path):
    from agent_runtime.subagents.output import read_public_tail
    path = tmp_path / "child.log"
    path.write_text("header\n12:00:00 think    | hidden\n12:00:00 system   | private\n"
                    "12:00:00 assistant| public\n12:00:00 assistant| unfinished", encoding="utf-8")
    result = read_public_tail(SimpleNamespace(_live_transcript_path=str(path)))
    assert result["text"] == "12:00:00 assistant| public"
    path.write_text("x" * 17000 + "\n12:00:00 result   | complete\n", encoding="utf-8")
    result = read_public_tail(SimpleNamespace(_live_transcript_path=str(path)))
    assert result["truncated"] is True and result["text"] == "12:00:00 result   | complete"


def test_service_to_native_dispatch_roundtrip(conversations, gateway, tmp_path, monkeypatch):
    service, factory, _ = conversations
    scope, sid = opened(conversations)
    server, owner, transport, _ = gateway
    native_id = "native-0"
    server._sessions[native_id] = owner
    child = Child("native-owned-child")
    _register_child(child, None, "native task", owner_session_id=native_id,
                    owner_transport=transport, owner_session_record=owner)
    writer = LiveTranscriptWriter("native-owned", 0, "task", root=tmp_path)
    writer.assistant_text("native output")
    child._live_transcript_path = str(writer.path)
    peer = factory.workers[0]
    original_call = peer.call

    def dispatch(method, params, **kwargs):
        if not method.startswith("eternia.subagents."):
            return original_call(method, params, **kwargs)
        response = server.dispatch({"id": 1, "method": method, "params": params}, transport)
        assert "error" not in response, response
        return response["result"]

    monkeypatch.setattr(peer, "call", dispatch)
    roster = service.subagents(scope, sid, "list", {})
    selected = dict(child_ref=roster["children"][0]["child_ref"], expected_generation=roster["generation"])
    tail = service.subagents(scope, sid, "tail", selected)
    assert tail["text"].endswith("native output")
    capture = {"capabilities": service.subagents(scope, sid, "capabilities", {}), "list": roster, "tail": tail}
    (tmp_path / "native-subagent-read-capture.json").write_text(json.dumps(capture, indent=2), encoding="utf-8")


def test_lineage_visibility_does_not_cross_profile_databases(gateway, tmp_path):
    from hermes_constants import get_hermes_home
    _, owner, transport, call = gateway
    home = get_hermes_home()
    db = SimpleNamespace(db_path=home / "state.db")
    owner["agent"] = SimpleNamespace(session_id="same-durable-id", _session_db=db)
    child = Child("old-owner-child")
    child._session_db, child.logs_dir = db, home / "sessions"
    old_parent = SimpleNamespace(session_id="same-durable-id")
    _register_child(child, old_parent, "owned lineage", owner_session_id="old-ui",
                    owner_transport=transport, owner_session_record={})
    visible = request(call, "list")["result"]["data"]["children"]
    assert len(visible) == 1 and visible[0]["child_ref"] is None
    child._session_db = SimpleNamespace(db_path=tmp_path / "other" / "state.db")
    child.logs_dir = tmp_path / "other" / "sessions"
    assert request(call, "list")["result"]["data"]["children"] == []


def test_missing_compute_host_refuses_without_creating_supervisor(gateway, monkeypatch):
    server, owner, _, call = gateway
    monkeypatch.setattr(server, "_session_uses_compute_host", lambda session: session is owner)
    monkeypatch.setattr(server, "_compute_host_supervisor", None)
    for operation in ("capabilities", "list"):
        reply = request(call, operation)
        assert reply["error"]["data"]["reason"] == "subagent_unavailable"
        assert server._compute_host_supervisor is None
