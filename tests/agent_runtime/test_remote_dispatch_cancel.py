"""D1.07 S2 — the sender's leg: a Stop on a cross-install dispatch asks the install running it.

The far install is a fake connection, as in ``test_remote_dispatch_leg``: what is
under test is the leg — one dial, the peer's typed answer passed through, the
row's durable mark that keeps this install's own supervisor from re-sending the
execute. The owner side is ``test_peer_agent_chat_cancel``.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.dispatch_store import (
    REMOTE_UNREACHABLE_REASON,
    STATE_CANCELLED,
    STATE_ERROR,
    STATE_RUNNING,
    get_dispatch,
    record_dispatch,
    request_dispatch_cancel,
)
from agent_runtime.running_work import cancel_work
from tools import agent_chat_dispatch

SENDER_ROOT = "persona_chat_personainst_neko_aaaaaaaaaaaa"
DISPATCH_ID = "dispatch-remote1"


@pytest.fixture
def remote_row(tmp_path, monkeypatch):
    home = tmp_path / "bg-home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_HEAD_HOME", str(home))
    monkeypatch.setattr(agent_chat_dispatch.remote.time, "sleep", lambda _s: None)
    record_dispatch(
        dispatch_id=DISPATCH_ID,
        sender_session_id=SENDER_ROOT,
        target_persona="@workstation/dev",
        ask="go",
        remote_install_id="install-b",
    )
    return DISPATCH_ID


class _FakeConnection:
    def __init__(self, frames):
        self._frames = list(frames)
        self.sent: list[dict] = []
        self.closed = False

    def send(self, message):
        self.sent.append(message)

    def read_frame(self):
        return self._frames.pop(0) if self._frames else None

    def set_timeout(self, seconds):
        pass

    def close(self):
        self.closed = True


def _dial_with(monkeypatch, *connections, on_dial=None):
    dials: list[str] = []
    queue = list(connections)

    def dial(root, install_id, *, timeout_seconds):
        dials.append(install_id)
        if on_dial is not None:
            on_dial()
        if not queue:
            raise ConnectionError("no endpoint answered")
        return queue.pop(0), {"event": "hello_ok"}

    monkeypatch.setattr("agent_runtime.gateway_peers.dial_peer", dial)
    return dials


def _answer(rid, outcome):
    return {"jsonrpc": "2.0", "id": rid, "result": {"outcome": outcome, "dispatch_id": DISPATCH_ID}}


def test_a_cancel_of_a_remote_dispatch_dials_once_and_returns_the_peers_answer(remote_row, monkeypatch):
    """Killing mutation: keep the ``not_owned_here``/elsewhere branch ahead of the
    remote check in ``request_cancel`` → the row is settled ``cancelled`` HERE,
    nothing is dialled, and the turn on B runs on."""

    connection = _FakeConnection([_answer(f"peer-cancel-{remote_row}", "stopping")])
    dials = _dial_with(monkeypatch, connection)

    answer = agent_chat_dispatch.request_cancel(remote_row, reason="operator_stop")

    assert answer["outcome"] == "stopping"
    assert dials == ["install-b"]
    assert connection.sent == [{
        "jsonrpc": "2.0", "id": f"peer-cancel-{remote_row}", "method": "peer.agent_chat.cancel",
        "params": {"dispatch_id": remote_row, "reason": "operator_stop"},
    }]
    assert connection.closed
    row = get_dispatch(remote_row)
    # Running until B's turn reports its end through the supervisor's frames.
    assert (row["state"], row["cancel_requested"]) == (STATE_RUNNING, "operator_stop")


def test_an_unreachable_peer_is_peer_unreachable_after_one_dial_and_the_row_keeps_running(remote_row, monkeypatch):
    dials = _dial_with(monkeypatch)  # nothing answers

    answer = agent_chat_dispatch.request_cancel(remote_row, reason="operator_stop")

    assert answer["outcome"] == REMOTE_UNREACHABLE_REASON
    assert dials == ["install-b"]
    assert get_dispatch(remote_row)["state"] == STATE_RUNNING


def test_an_install_without_the_verb_is_a_typed_refusal(remote_row, monkeypatch):
    rid = f"peer-cancel-{remote_row}"
    _dial_with(monkeypatch, _FakeConnection([{
        "jsonrpc": "2.0", "id": rid,
        "error": {"code": -32601, "message": "method not found", "data": {"reason": "method_not_found"}},
    }]))

    answer = agent_chat_dispatch.request_cancel(remote_row)

    assert (answer["outcome"], answer["detail"]) == ("peer_refused", "method_not_found")


def test_cancel_work_surfaces_the_remote_answers_typed(remote_row, monkeypatch):
    _dial_with(monkeypatch, _FakeConnection([_answer(f"peer-cancel-{remote_row}", "stopping")]))
    result = cancel_work(f"dispatch:{remote_row}", reason="operator_stop")
    assert (result["status"], result["outcome"]) == ("ok", "stopping")

    other = "dispatch-remote2"
    record_dispatch(dispatch_id=other, sender_session_id=SENDER_ROOT, target_persona="@workstation/dev",
                    ask="go", remote_install_id="install-b")
    _dial_with(monkeypatch)
    result = cancel_work(f"dispatch:{other}")
    assert (result["status"], result["code"]) == ("error", REMOTE_UNREACHABLE_REASON)
    assert "could not be reached" in result["detail"]


def _spec():
    return {
        "client_message_id": f"agent-dispatch-{DISPATCH_ID}",
        "remote_install_id": "install-b",
        "remote_display_name": "workstation",
        "remote_target": "dev",
        "message": "go",
        "max_seconds": 60.0,
    }


def _turn(request_id, payload, code):
    lines = [] if payload is None else json.dumps(payload).split("\n")
    return [{"id": request_id, "event": agent_chat_dispatch.SERVE_STDOUT_EVENT, "line": line} for line in lines] + [
        {"id": request_id, "event": "exit", "code": code}
    ]


def _ack(rid):
    return {"jsonrpc": "2.0", "id": rid, "result": {"accepted": True, "request_id": "chat-1"}}


def test_the_supervisor_sends_nothing_after_a_stop(remote_row, monkeypatch):
    dials = _dial_with(monkeypatch)
    request_dispatch_cancel(remote_row, "operator_stop")

    agent_chat_dispatch._run_remote_dispatch(remote_row, _spec())

    assert dials == []
    row = get_dispatch(remote_row)
    assert row["state"] == STATE_CANCELLED
    assert row["result"]["remote"]["reason"] == "cancelled"


def test_a_stop_landing_during_the_accept_is_carried_to_b_and_partial_output_is_kept(remote_row, monkeypatch):
    rid = f"peer-exec-{remote_row}"
    partial = {"ok": False, "reply": "ran 40 of 120 files", "error": "interrupted"}
    connection = _FakeConnection([_ack(rid)] + _turn("chat-1", partial, 130))
    _dial_with(monkeypatch, connection, on_dial=lambda: request_dispatch_cancel(remote_row, "operator_stop"))

    agent_chat_dispatch._run_remote_dispatch(remote_row, _spec())

    assert [frame["method"] for frame in connection.sent] == ["peer.agent_chat.execute", "peer.agent_chat.cancel"]
    row = get_dispatch(remote_row)
    assert row["state"] == STATE_ERROR  # the turn's own verdict
    assert row["result"]["reply"] == "ran 40 of 120 files"  # ruling b: kept


def test_a_stopped_turn_that_wrote_no_reply_settles_cancelled(remote_row, monkeypatch):
    rid = f"peer-exec-{remote_row}"
    connection = _FakeConnection([_ack(rid)] + _turn("chat-1", None, 130))
    _dial_with(monkeypatch, connection, on_dial=lambda: request_dispatch_cancel(remote_row, "operator_stop"))

    agent_chat_dispatch._run_remote_dispatch(remote_row, _spec())

    assert get_dispatch(remote_row)["state"] == STATE_CANCELLED


def test_a_remote_row_supervised_here_is_still_asked_of_b(remote_row, monkeypatch):
    """Before S2 this branch settled the row ``cancelled before it started`` here
    while the turn ran on B; the remote check now precedes the local one."""

    connection = _FakeConnection([_answer(f"peer-cancel-{remote_row}", "not_running")])
    _dial_with(monkeypatch, connection)
    agent_chat_dispatch._mark_supervised(remote_row)
    try:
        answer = agent_chat_dispatch.request_cancel(remote_row)
    finally:
        agent_chat_dispatch._forget_supervised(remote_row)

    assert answer["outcome"] == "not_running"
    assert get_dispatch(remote_row)["state"] == STATE_RUNNING
