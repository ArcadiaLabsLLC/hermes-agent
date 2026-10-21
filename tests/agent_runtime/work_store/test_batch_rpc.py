"""``runtime.batch.*`` (dispatcher plan §3, B2): six console methods, deferred off the reader lane,
scoped like Work, refusals typed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import paths
from agent_runtime.batch import rpc as batch_rpc
from agent_runtime.call_authorization import STDIO_OWNER, UNKNOWN_CALLER
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.serve_rpc import handle_request, method_tier
from agent_runtime.serve_rpc.protocol import DEFERRED, RpcContext
from agent_runtime.store import WorkspaceStore
from agent_runtime.work import service
from agent_runtime.work.model import WorkScope
from agent_runtime.work_store.reasons import Reason, WorkRefused


def test_six_console_methods_deferred(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(batch_rpc, "execute", lambda operation, params, caller, dispatcher: calls.append(operation) or {"v": 1})
    assert batch_rpc.OPERATIONS == ("plan", "start", "status", "stop", "land", "approve")
    for operation in batch_rpc.OPERATIONS:
        name = "runtime.batch." + operation
        request = {"jsonrpc": "2.0", "id": operation, "method": name, "params": {}}
        assert method_tier(name) == "console"
        assert "error" in handle_request(request, RpcContext(caller=UNKNOWN_CALLER))
        context = RpcContext(caller=STDIO_OWNER, spawn_reply=lambda job: replies.append(job) or True)
        assert handle_request(request, context) is DEFERRED and operation not in calls
        assert replies.pop()()["result"] == {"v": 1} and calls[-1] == operation


def test_a_refusal_carries_its_reason_and_a_crash_leaks_nothing(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise WorkRefused(Reason.LANDING_IN_PROGRESS, "BATCH-AAAAAA")
    monkeypatch.setattr(batch_rpc, "execute", refuse)
    reply = batch_rpc._batch_reply("r", "land", {}, RpcContext(caller=STDIO_OWNER))
    assert reply["error"]["code"] == 4090
    assert reply["error"]["data"] == {"reason": "landing_in_progress", "detail": "BATCH-AAAAAA"}

    def crash(*_args, **_kwargs):
        raise RuntimeError("private token")
    monkeypatch.setattr(batch_rpc, "execute", crash)
    reply = batch_rpc._batch_reply("r", "plan", {}, RpcContext(caller=STDIO_OWNER))
    assert reply["error"]["data"]["reason"] == "work_outcome_unknown" and "private" not in str(reply)


@pytest.fixture
def scope():
    ws = WorkspaceStore().create(name="Desk").id
    surface = paths.office_surface_path(ws)
    surface.parent.mkdir(parents=True, exist_ok=True)
    surface.write_text("{}", encoding="utf-8")
    install = ensure_install_identity(paths.store_root()).install_id
    assert ws in service.workspace_ids()
    return SimpleNamespace(ws=ws, params={"install_id": install, "owner": WorkScope(install, ws).owner}, install=install)


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return SimpleNamespace(wire=lambda: {"op": name}) if name != "status" else {"batches": []}
        return call


def test_execute_resolves_the_workspace_and_reads_params(scope):
    d = Recorder()
    out = batch_rpc.execute("start", {**scope.params, "batch_id": "BATCH-AAAAAA", "personas": {"L1": "inst-a"}},
                            STDIO_OWNER, dispatcher=d)
    assert out == {"version": 1, "install_id": scope.install, "owner": scope.params["owner"], "batch": {"op": "start"}}
    assert d.calls[-1] == ("start", (scope.ws, "BATCH-AAAAAA"), {"personas": {"L1": "inst-a"}})
    batch_rpc.execute("stop", {**scope.params, "batch_id": "BATCH-AAAAAA"}, STDIO_OWNER, dispatcher=d)
    assert d.calls[-1] == ("stop", (scope.ws, "BATCH-AAAAAA", None), {})
    assert batch_rpc.execute("status", scope.params, STDIO_OWNER, dispatcher=d)["batches"] == []
    for bad in ({**scope.params, "owner": "nobody"}, {**scope.params, "install_id": "other"}):
        with pytest.raises(WorkRefused) as refused:
            batch_rpc.execute("plan", bad, STDIO_OWNER, dispatcher=d)
        assert refused.value.reason is Reason.OWNER_CHANGED
    with pytest.raises(WorkRefused) as denied:
        batch_rpc.execute("plan", scope.params, UNKNOWN_CALLER, dispatcher=d)
    assert denied.value.reason is Reason.DENIED


def test_the_serve_sessions_dispatcher_answers_and_none_refuses_door_unbound(scope):
    """RT-BATCH-RPC-OWN-DISPATCHER. Killing mutation: ``execute`` builds ``default_dispatcher()`` when
    handed none (the pre-fix fallback) — the no-session context answers a plan instead of refusing."""
    d = Recorder()
    session = SimpleNamespace(batch_dispatcher=d)
    with_session = RpcContext(caller=STDIO_OWNER, batch_dispatcher=lambda: session.batch_dispatcher)
    reply = batch_rpc._batch_reply("r", "status", scope.params, with_session)
    assert reply["result"]["batches"] == [] and d.calls[-1][0] == "status"
    for context in (RpcContext(caller=STDIO_OWNER), RpcContext(caller=STDIO_OWNER, batch_dispatcher=lambda: None)):
        reply = batch_rpc._batch_reply("r", "plan", scope.params, context)
        assert reply["error"]["code"] == 4090 and reply["error"]["data"]["reason"] == "door_unbound"


def test_the_persona_turn_executor_reports_every_settle_to_every_listener():
    from agent_runtime.work_store.executor import Outcome, Verdict
    from agent_runtime.work_store.persona_turn import PersonaTurnExecutor

    heard, executor = [], PersonaTurnExecutor()
    first = lambda run, outcome: heard.append(("engine", run.request_id))
    executor.on_settle(first)
    executor.on_settle(first)
    executor.on_settle(lambda run, outcome: (_ for _ in ()).throw(RuntimeError("one listener fails")))
    executor.on_settle(lambda run, outcome: heard.append(("batch", run.request_id)))
    executor._report("BATCH-AAAAAA:L1", "root", "cmid", "now", (), Outcome(Verdict.DONE))
    assert heard == [("engine", "BATCH-AAAAAA:L1"), ("batch", "BATCH-AAAAAA:L1")]
