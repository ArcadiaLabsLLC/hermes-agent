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


def test_plan_rows_plans_only_those(scope):
    """RT-BATCH-PLAN-ROWS: ``runtime.batch.plan`` with ``rows`` plans ONLY the named READY rows, and
    ``start`` with the same set re-plans it (without it the board reads as moved). Killing mutation:
    ``BatchDispatcher.plan`` ignores ``rows`` (plans every READY row) -> the lanes hold all four, red."""
    from dataclasses import replace

    from agent_runtime.batch.planner import Member
    from agent_runtime.work_store.grammar import Claim

    from batch_support import NOTE, dispatcher, qrow
    from contract_fakes import FakeSource

    a, b, c, d_row, taken = (qrow(f"RT-{x}", assignee="inst-a") for x in ("A", "B", "C", "D", "E"))
    source = FakeSource([a, b, c, d_row, replace(taken, taken=Claim("2026-10-18", "persona:inst-b"))])
    d = dispatcher(source, roster=[Member("inst-a", "alice", "engineer"), Member("inst-b", "bob", "engineer")])
    chosen = [["hermes", NOTE, "RT-A"], ["hermes", NOTE, "RT-C"]]
    plan = batch_rpc.execute("plan", {**scope.params, "rows": chosen}, STDIO_OWNER, dispatcher=d)["plan"]
    planned = sorted(ref[2] for lane in plan["lanes"] for ref in lane["rows"])
    assert planned == ["RT-A", "RT-C"]
    everything = batch_rpc.execute("plan", scope.params, STDIO_OWNER, dispatcher=d)["plan"]
    assert sorted(ref[2] for lane in everything["lanes"] for ref in lane["rows"]) == ["RT-A", "RT-B", "RT-C", "RT-D"]
    assert everything["id"] != plan["id"]
    # Start without the set re-plans the whole board: the id no longer matches (the board "moved").
    with pytest.raises(WorkRefused) as moved:
        batch_rpc.execute("start", {**scope.params, "batch_id": plan["id"]}, STDIO_OWNER, dispatcher=d)
    assert moved.value.reason is Reason.CONFLICT
    batch = batch_rpc.execute("start", {**scope.params, "batch_id": plan["id"], "rows": chosen}, STDIO_OWNER,
                              dispatcher=d)["batch"]
    assert batch["id"] == plan["id"]
    claimed = sorted(ref.id for ref, row in source.by_ref.items() if row.taken and row.taken.who == "persona:inst-a")
    assert claimed == ["RT-A", "RT-C"]
    # A ref to a row that is not READY and unclaimed (or not on the board) refuses, naming it.
    for bad in (["hermes", NOTE, "RT-E"], ["hermes", NOTE, "RT-NOPE"]):
        with pytest.raises(WorkRefused) as refused:
            batch_rpc.execute("plan", {**scope.params, "rows": [bad]}, STDIO_OWNER, dispatcher=d)
        assert refused.value.reason is Reason.INVALID and bad[2] in refused.value.detail
    for malformed in ([], [["hermes", "RT-A"]], "RT-A"):
        with pytest.raises(WorkRefused) as refused:
            batch_rpc.execute("plan", {**scope.params, "rows": malformed}, STDIO_OWNER, dispatcher=d)
        assert refused.value.reason is Reason.INVALID


def test_status_prices_each_lane_run():
    """RT-BATCH-LANE-WORKTREES-AND-USAGE: ``status`` answers each lane's ``usage`` — its run's turn record
    (``run_id`` = ``<root>/<cmid>``) totals priced by the injected pricer; a lane with no record is null; an
    unpriceable model answers ``priced: false``. Killing mutation: ``lane_usage`` returns ``priced: True``
    always -> the unpriced case is red."""
    from dataclasses import replace

    from agent_runtime.batch.planner import Member
    from agent_runtime.batch.usage import lane_usage, usage_index

    from batch_support import WS, dispatcher, qrow
    from contract_fakes import FakeExecutor, FakeSource

    executor = FakeExecutor()
    started = executor.start
    executor.start = lambda a: replace(started(a), run_id=f"root-{a.request_id}/cmid")
    records = [{"root_chat_session_id": None, "client_message_id": "x"}]  # no usage, no root: ignored
    priced = lambda usage: {"usd": "0.0123", "status": "estimated"} if usage.get("model") == "m" else None
    source = FakeSource([qrow("RT-A", assignee="inst-a"), qrow("RT-B", heading="Seams", assignee="inst-a")])
    d = dispatcher(source, executor=executor, roster=[Member("inst-a", "alice", "engineer")],
                   turn_records=lambda: records, price=priced)
    batch = d.start(WS, d.plan(WS).id)
    run_l1 = d.load(WS, batch.id).lanes[0].run_id
    root, cmid = run_l1.split("/")
    records.append({"root_chat_session_id": root, "client_message_id": cmid,
                    "provider_usage": {"schema": 1, "model": "m", "input_tokens": 100, "output_tokens": 20,
                                       "cache_read_tokens": 5, "total_tokens": 125}})
    lanes = {lane["id"]: lane for lane in d.status(WS, batch.id)["batches"][0]["lanes"]}
    assert lanes["L1"]["usage"] == {"input_tokens": 100, "output_tokens": 20, "cache_read_tokens": 5,
                                    "cache_write_tokens": 0, "total_tokens": 125, "cost_usd": "0.0123",
                                    "priced": True}
    assert lanes["L2"]["run_id"] and lanes["L2"]["usage"] is None
    assert d.status(WS, batch.id)["batches"][0]["landing"]["usage"] is None
    unpriced = lane_usage("r/c", usage_index([{"root_chat_session_id": "r", "client_message_id": "c",
                                               "provider_usage": {"model": "nobody", "input_tokens": 3}}]), priced)
    assert unpriced["priced"] is False and unpriced["cost_usd"] is None and unpriced["input_tokens"] == 3
