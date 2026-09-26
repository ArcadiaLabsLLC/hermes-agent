from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from agent_runtime.conversations.model import ConversationError, ConversationScope, TurnState
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.conversation_support import WorkerFactory

pytestmark = pytest.mark.timeout(45)
PROMPT = {"text": "Review this design", "images": []}


@pytest.fixture
def runtime(tmp_path):
    for name in ("runtime", "work", "a", "b"):
        (tmp_path / name).mkdir()
    factory = WorkerFactory()
    service = ConversationService(tmp_path / "runtime", "install", profile_home=lambda p: tmp_path / p,
                                  worker_factory=factory)
    yield service, factory, tmp_path
    service.close()


def opened(runtime, profile="a", key="thread", client="account-a"):
    service, _, root = runtime
    scope = ConversationScope("operator", client, profile)
    reply = service.open(scope, key=key, cwd=str(root / "work"), expected_home=str(root / profile))
    return scope, reply["session_id"]


def test_exact_account_profile_home_and_independent_sessions(runtime):
    service, factory, root = runtime
    a, first = opened(runtime)
    b, second = opened(runtime, "b")
    again, third = opened(runtime, "a", "another")
    assert len(factory.workers) == 2
    assert len({first, second, third}) == 3
    assert service.facts(a, first)["session_id"] == first
    for wrong in (ConversationScope("other-actor", a.client, a.profile),
                  ConversationScope(a.actor, "other-account", a.profile), b):
        with pytest.raises(ConversationError, match="conversation_unavailable"):
            service.facts(wrong, first)
    with pytest.raises(ConversationError, match="conversation_owner_changed"):
        service.open(a, key="thread", cwd=str(root / "work"), expected_home=str(root / "b"))
    assert service.facts(again, third)["session_id"] == third


def test_dispatch_is_durable_and_replay_never_resubmits(runtime):
    service, factory, _ = runtime
    scope, sid = opened(runtime)
    worker = factory.workers[0]
    worker.on_submit = lambda _: assert_dispatch(service, scope, sid)
    assert service.send(scope, sid, "turn", PROMPT)["state"] == "running"
    assert service.send(scope, sid, "turn", PROMPT)["state"] == "running"
    assert sum(method == "prompt.submit" for method, _ in worker.calls) == 1
    with pytest.raises(ConversationError, match="idempotency_conflict"):
        service.send(scope, sid, "turn", {**PROMPT, "text": "different"})
    with pytest.raises(ConversationError, match="conversation_busy"):
        service.send(scope, sid, "next", PROMPT)
    worker.event("native-0", "message.complete", text="done", status="complete")
    assert service.read(scope, sid, 0, "turn")["turn"]["state"] == "completed"
    worker.on_submit = None
    assert service.send(scope, sid, "next", PROMPT)["state"] == "running"


def assert_dispatch(service, scope, sid):
    assert service.store.turn(service.store.get(sid, scope), "turn").state == TurnState.DISPATCHING


def test_stop_during_admission_waits_for_exact_native_terminal(runtime):
    service, factory, _ = runtime
    scope, sid = opened(runtime)
    entered, release = threading.Event(), threading.Event()
    worker = factory.workers[0]
    def submit(_):
        entered.set()
        assert release.wait(10)
    worker.on_submit = submit
    with ThreadPoolExecutor(max_workers=1) as pool:
        sending = pool.submit(service.send, scope, sid, "turn", PROMPT)
        assert entered.wait(10)
        try:
            assert service.stop(scope, sid, "turn")["state"] == "dispatching"
            assert service.read(scope, sid, 0, "turn")["turn"]["state"] != "stopped"
        finally:
            release.set()
        assert sending.result()["state"] == "running"
    assert [frame["method"] for frame in worker.writes] == ["session.interrupt", "session.interrupt"]
    worker.event("native-other", "message.complete", status="interrupted")
    assert service.read(scope, sid, 0, "turn")["turn"]["state"] == "running"
    worker.event("native-0", "message.complete", status="interrupted")
    assert service.read(scope, sid, 0, "turn")["turn"]["state"] == "stopped"


def test_late_submit_ack_cannot_undo_completion_or_failure(runtime):
    service, factory, _ = runtime
    scope, sid = opened(runtime)
    worker = factory.workers[0]
    worker.on_submit = lambda native: worker.event(native, "message.complete", status="error", text="Unavailable")
    assert service.send(scope, sid, "turn", PROMPT)["state"] == "failed"
    other, other_sid = opened(runtime, "b")
    assert service.send(other, other_sid, "other-turn", PROMPT)["state"] == "running"
    assert service.send(scope, sid, "next", PROMPT)["state"] == "failed"


def test_restart_keeps_unknown_receipt_and_blocks_replay(runtime):
    service, factory, root = runtime
    scope, sid = opened(runtime)
    service.send(scope, sid, "turn", PROMPT)
    recovered = ConversationService(root / "runtime", "install", profile_home=lambda p: root / p,
                                    worker_factory=factory)
    try:
        assert recovered.store.turn(recovered.store.get(sid, scope), "turn").state == TurnState.UNKNOWN
        with pytest.raises(ConversationError, match="turn_outcome_unknown"):
            recovered.open(scope, key="thread", cwd=str(root / "work"),
                           expected_home=str(root / "a"), resume=sid)
        assert len(factory.workers) == 1
    finally:
        recovered.close()


def test_questions_validate_choices_secrets_are_not_replayed(runtime):
    service, factory, _ = runtime
    scope, sid = opened(runtime)
    worker = factory.workers[0]
    service.send(scope, sid, "turn", PROMPT)
    worker.question("native-0", "permission", description="Run command", command="echo test", choices=["once", "deny"])
    with pytest.raises(ConversationError):
        service.respond(scope, sid, "permission", {"choice": "always"})
    assert not worker.writes
    assert service.respond(scope, sid, "permission", {"choice": "once"}) == {"accepted": True}
    worker.question("native-0", "password", "secret", prompt="Credential")
    service.respond(scope, sid, "password", {"value": "must-not-be-replayed"})
    assert "must-not-be-replayed" not in json.dumps(service.read(scope, sid, 0))
    with pytest.raises(ConversationError):
        service.respond(scope, sid, "password", {"value": "duplicate"})


def test_models_are_session_scoped_and_drain_holds_active_work(runtime):
    service, factory, _ = runtime
    scope, a = opened(runtime)
    _, b = opened(runtime, key="another")
    choice = '["local","model-b"]'
    assert service.select_model(scope, a, choice)["current_model_id"] == choice
    assert service.facts(scope, b)["current_model_id"] == '["local","model-a"]'
    service.send(scope, a, "turn", PROMPT)
    assert service.drain_pending(close_idle=True) == ["conversation:turn"]
    assert not factory.workers[0].closed
    with pytest.raises(ConversationError, match="runtime_stopping"):
        service.send(scope, b, "other", PROMPT)
    factory.workers[0].event("native-0", "message.complete", status="complete", text="done")
    assert service.drain_pending(close_idle=True) == []
    assert factory.workers[0].closed
