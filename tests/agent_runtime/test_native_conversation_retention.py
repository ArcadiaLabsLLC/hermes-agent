"""Binding budgets never substitute for native retirement evidence."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_runtime.conversations.model import ConversationError, ConversationScope, Refusal, TurnState, digest
from agent_runtime.conversations.service import ConversationService
from tests.agent_runtime.conversation_support import WorkerFactory

pytestmark = pytest.mark.timeout(45)
PROMPT = {"text": "Retention proof", "images": []}


@pytest.fixture
def runtime(tmp_path):
    factory, now = WorkerFactory(), [0.0]
    service = ConversationService(tmp_path, "test", profile_home=lambda _: tmp_path,
        worker_factory=factory, retention_options={"clock": lambda: now[0],
            "idle_seconds": 100, "unobserved_seconds": 5, "budget": 3})
    scope = ConversationScope("operator", "test", "a")
    def open_(key):
        return service.open(scope, key=key, cwd=str(tmp_path), expected_home=str(tmp_path))["session_id"]
    yield service, factory, now, scope, open_
    service.close()


def settle(service, scope, sid, worker, turn="turn"):
    service.send(scope, sid, turn, PROMPT)
    native = next(p["session_id"] for m, p in reversed(worker.calls) if m == "prompt.submit")
    worker.event(native, "message.complete", text="preserved", status="complete")
    return native


def test_many_completed_bindings_are_bounded_and_reopen_without_resending(runtime):
    service, factory, now, scope, open_ = runtime
    routes = []
    for index in range(80):
        sid = open_(f"chat-{index}")
        routes.append(sid)
        settle(service, scope, sid, factory.workers[-1])
        now[0] += 6
        service._bindings.sweep()
        assert len(service._bindings._entries) <= 3
        assert len(service._bindings._sessions) <= 3
        assert len(service._workers._workers) == 1
    worker = factory.workers[0]
    assert service.read(scope, routes[0], 0, epoch="expired")["turn"]["state"] == "completed"
    assert len([m for m, _ in worker.calls if m == "prompt.submit"]) == 80
    now[0] += 101
    service._bindings.sweep()
    assert not service._bindings._entries and not service._bindings._sessions
    assert not service._workers._workers and worker.closed
    assert open_("chat-0") == routes[0]
    assert not any(m == "prompt.submit" for m, _ in factory.workers[1].calls)


def test_active_unknown_and_native_protected_work_survives(runtime):
    service, factory, now, scope, open_ = runtime
    running, unknown, waiting = [open_(key) for key in ("running", "unknown", "waiting")]
    worker = factory.workers[0]
    for sid in (running, unknown):
        service.send(scope, sid, "turn", PROMPT)
    service.store.settle(unknown, "turn", TurnState.UNKNOWN)
    native = settle(service, scope, waiting, worker)
    # Native queues, pending questions and delegation remain authoritative.
    worker.protected.add(native)
    now[0] += 1000
    service._bindings.sweep()
    assert set(service._bindings._entries) == {running, unknown, waiting}
    assert not worker.closed
    assert len([m for m, _ in worker.calls if m == "session.retire"]) == 1


def test_observed_and_borrowed_sessions_cannot_be_retired(runtime):
    service, factory, now, scope, open_ = runtime
    sid = open_("observed")
    settle(service, scope, sid, factory.workers[0])
    now[0] += 99
    service.read(scope, sid, 0)
    now[0] += 99
    service._bindings.sweep()
    assert sid in service._bindings._entries
    route = service.store.get(sid, scope)
    with service._bindings.borrow(route):
        now[0] += 101
        service._bindings.sweep()
        assert sid in service._bindings._entries
    now[0] += 101
    service._bindings.sweep()
    assert sid not in service._bindings._entries


def test_lost_retirement_ack_is_reconciled_before_reopening(runtime):
    service, factory, now, scope, open_ = runtime
    sid = open_("lost-ack")
    worker = factory.workers[0]
    settle(service, scope, sid, worker)
    original, drop = worker.call, [True]
    def call(method, params, **kwargs):
        result = original(method, params, **kwargs)
        if method == "session.retire" and drop[0]:
            drop[0] = False
            raise ConversationError(Refusal.UNKNOWN)
        return result
    worker.call = call
    now[0] += 101
    service._bindings.sweep()
    assert service._bindings._entries[sid].live.retirement_pending
    assert open_("lost-ack") == sid
    assert worker.closed
    assert len(factory.workers) == 2
    assert not any(m == "prompt.submit" for m, _ in factory.workers[1].calls)


def test_new_binding_keeps_profile_worker_alive_during_retirement(runtime):
    service, factory, now, scope, open_ = runtime
    first = open_("old")
    worker = factory.workers[0]
    settle(service, scope, first, worker)
    entered, release = threading.Event(), threading.Event()
    original = worker.call
    def call(method, params, **kwargs):
        if method == "session.retire":
            entered.set()
            assert release.wait(5)
        return original(method, params, **kwargs)
    worker.call = call
    now[0] += 101
    new_key = next(f"new-{i}" for i in range(100)
                   if hash("conversation-" + digest([scope.key, f"new-{i}"])) % 64 != hash(first) % 64)
    with ThreadPoolExecutor(max_workers=1) as pool:
        sweeping = pool.submit(service._bindings.sweep)
        assert entered.wait(5)
        try:
            second = open_(new_key)
        finally:
            release.set()
        sweeping.result()
    assert second in service._bindings._entries
    assert not worker.closed and len(factory.workers) == 1
