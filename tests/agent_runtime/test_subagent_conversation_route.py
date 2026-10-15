"""An inspection cannot resurrect an execution owner or escape its route."""
import pytest

from agent_runtime.conversations.model import ConversationError, ConversationScope
from tests.agent_runtime.test_native_conversation import runtime, opened


def test_missing_dead_and_retiring_owner_never_attach(runtime):
    service, factory, root = runtime
    scope, sid = opened(runtime)
    worker = factory.workers[0]
    worker.alive = worker.execution_possible = False
    before = list(worker.calls)
    for operation in ("capabilities", "list"):
        with pytest.raises(ConversationError, match="conversation_worker_lost"):
            service.subagents(scope, sid, operation, {})
    assert len(factory.workers) == 1 and worker.calls == before
    worker.alive = True
    with service._session(scope, sid) as live:
        live.retirement_pending = True
    with pytest.raises(ConversationError, match="conversation_worker_lost"):
        service.subagents(scope, sid, "list", {})
    assert worker.calls == before
    live.retirement_pending = False
    route = service.store.reserve(scope, "never-attached", str(root / "work"), str(root / "a"))[0]
    with pytest.raises(ConversationError, match="conversation_worker_lost"):
        service.subagents(scope, route.id, "list", {})
    assert len(factory.workers) == 1


def test_route_authority_and_generation_reach_the_same_worker(runtime, monkeypatch):
    service, factory, _ = runtime
    scope, sid = opened(runtime)
    worker = factory.workers[0]
    observed = []

    def read(method, params):
        observed.append((method, params))
        return {"data": {"generation": "verified", "version": 1, "children": []}}

    monkeypatch.setattr(worker, "call", read)
    result = service.subagents(scope, sid, "list", {"session_id": "forged", "worker_generation": "forged"})
    assert result["session_id"] == sid and result["profile"] == scope.profile
    method, params = observed[0]
    assert method == "eternia.subagents.list" and params["session_id"] == "native-0"
    assert params["worker_generation"] != "forged" and params["owner_scope"]
    for wrong in (ConversationScope("other", scope.client, scope.profile),
                  ConversationScope(scope.actor, "other", scope.profile),
                  ConversationScope(scope.actor, scope.client, "b")):
        with pytest.raises(ConversationError):
            service.subagents(wrong, sid, "list", {})
    assert len(observed) == 1
