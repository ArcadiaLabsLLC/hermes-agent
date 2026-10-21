from agent_runtime.call_authorization import STDIO_OWNER, UNKNOWN_CALLER
from agent_runtime.execution_identity import execution_identity
from agent_runtime.serve_rpc import handle_request, method_tier
from agent_runtime.serve_rpc.protocol import DEFERRED, RpcContext
from agent_runtime.work import rpc as work
from agent_runtime.work_store.reasons import Reason, WorkRefused


def test_work_family_private_deferred_and_execution_guarded(monkeypatch):
    calls, replies = [], []
    def execute(operation, params, caller):
        calls.append(operation)
        return {"version": 1}
    monkeypatch.setattr(work, "execute", execute)
    assert work.OPERATIONS == ("capabilities", "context", "list", "inspect", "start", "assign", "claim",
                               "release", "set_status", "done", "create_brain", "lend_skills")
    for operation in work.OPERATIONS:
        name = "runtime.work." + operation
        request = {"jsonrpc": "2.0", "id": operation, "method": name, "params": {}}
        assert method_tier(name) == "console"
        assert "error" in handle_request(request, RpcContext(caller=UNKNOWN_CALLER))
        context = RpcContext(caller=STDIO_OWNER, spawn_reply=lambda job: replies.append(job) or True)
        assert handle_request(request, context) is DEFERRED
        assert operation not in calls
        assert replies.pop()()["result"] == {"version": 1}
        assert calls[-1] == operation
        wrong = handle_request({**request, "execution_id": "wrong"}, context)
        assert wrong["error"]["data"]["reason"] == "execution_identity_mismatch"
        good = handle_request({**request, "execution_id": execution_identity()["execution_id"]}, context)
        assert good is DEFERRED
        replies.pop()()


def test_work_failure_does_not_leak_native_diagnostics(monkeypatch):
    def fail(*args):
        raise RuntimeError("private prompt and token")
    monkeypatch.setattr(work, "execute", fail)
    reply = work._work_reply("r", "start", {}, STDIO_OWNER)
    assert reply["error"]["data"]["reason"] == "work_outcome_unknown"
    assert "private prompt" not in str(reply)


def test_work_refusal_carries_reason_and_detail(monkeypatch):
    def refuse(*args):
        raise WorkRefused(Reason.ALREADY_TAKEN, "persona:pi_alice_01")
    monkeypatch.setattr(work, "execute", refuse)
    reply = work._work_reply("r", "claim", {}, STDIO_OWNER)
    assert reply["error"]["code"] == 4090
    assert reply["error"]["data"] == {"reason": "already_taken", "detail": "persona:pi_alice_01"}
