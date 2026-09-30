from tui_gateway import session_execution as execution
from tui_gateway.execution_result import MAX_RESULT_BYTES, public_result
from tests.tui_gateway.test_native_execution_fence import owner as owner


def finish(session, text, *, status="complete", identity=None):
    params = {"type": "message.complete", "payload": {
        "status": status, "text": text, "reasoning": "private reasoning"}}
    if identity is not None:
        params["execution_id"] = identity
    execution.stamp(session, {"method": "event", "params": params})


def test_public_result_recovers_without_replaying_history_or_private_reasoning(owner):
    session, _ = owner
    execution.admit(session, "first")
    finish(session, "The public answer")
    session.pop("native_execution")
    recovered = execution.snapshot(session, "first")
    assert recovered["result"] == {"text": "The public answer", "truncated": False, "error": None}
    assert recovered["status"] == "complete"


def test_late_completion_cannot_replace_a_committed_result(owner):
    session, _ = owner
    execution.admit(session, "turn")
    finish(session, "The answer")
    finish(session, "late failure", status="error")
    assert execution.snapshot(session, "turn")["result"]["text"] == "The answer"
    assert execution.snapshot(session, "turn")["status"] == "complete"


def test_foreign_completion_does_not_settle_this_execution(owner):
    session, _ = owner
    execution.admit(session, "current")
    finish(session, "foreign", identity="old")
    current = execution.snapshot(session, "current")
    assert current["status"] == "running"
    assert "result" not in current


def test_completion_projection_is_bounded_without_cutting_unicode():
    result = public_result({"text": "🔎" * MAX_RESULT_BYTES, "reasoning": "not public"})
    assert result["truncated"]
    assert len(result["text"].encode("utf-8")) == MAX_RESULT_BYTES
    assert set(result) == {"text", "error", "truncated"}
