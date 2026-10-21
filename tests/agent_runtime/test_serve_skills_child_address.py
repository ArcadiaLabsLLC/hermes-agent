"""The serve's ``runtime.conversation.skills.*`` reaches a worker CHILD (RT-SERVE-SKILLS-CHILD-ADDRESS).

A ``child_ref`` from ``runtime.conversation.subagents.list`` is completed with the SAME
``owner_scope`` + ``worker_generation`` the subagents lane sends (``subagents.child_owner``), so
the worker resolves it; ``skills.lend`` reaches ``eternia.skills.lend``; a stale child is the
subagent refusal, never the parent's catalog.
"""

import pytest

from agent_runtime import serve_rpc
from agent_runtime.conversations.model import ConversationError, Refusal as ConversationRefusal
from agent_runtime.subagents.model import ERROR_CODES, Refusal, SubagentError
from tests.agent_runtime.test_native_conversation import runtime as conversations, opened


def _recording(factory, monkeypatch, reply=None):
    peer, seen = factory.workers[0], []

    def call(method, params, **_):
        seen.append((method, dict(params)))
        if reply is not None:
            raise reply
        return {"data": {"generation": "g"} if method.startswith("eternia.subagents.") else {"skills": []}}

    monkeypatch.setattr(peer, "call", call)
    return seen


def test_a_child_read_carries_the_subagent_lanes_owner(conversations, monkeypatch):
    service, factory, _ = conversations
    scope, sid = opened(conversations)
    seen = _recording(factory, monkeypatch)
    service.subagents(scope, sid, "list", {})
    service.skills(scope, sid, "list", {"child_ref": "child-1"})
    service.skills(scope, sid, "list", {})
    (_, roster), (skills_method, child), (_, own) = seen
    assert skills_method == "eternia.skills.list"
    assert {k: child[k] for k in ("owner_scope", "worker_generation")} == \
        {k: roster[k] for k in ("owner_scope", "worker_generation")}
    assert child["child_ref"] == "child-1" and child["session_id"] == roster["session_id"]
    assert not {"owner_scope", "worker_generation", "child_ref"} & set(own)


def test_lend_reaches_the_worker_lend_verb(conversations, monkeypatch):
    service, factory, _ = conversations
    scope, sid = opened(conversations)
    seen = _recording(factory, monkeypatch)
    service.skills(scope, sid, "lend", {"child_ref": "child-1", "skills": ["review"], "request_id": "r1"})
    [(method, request)] = seen
    assert method == "eternia.skills.lend"
    assert (request["child_ref"], request["skills"], request["mode"], request["request_id"]) == \
        ("child-1", ["review"], "lend", "r1")
    with pytest.raises(ConversationError):
        service.skills(scope, sid, "lend", {"child_ref": "child-1", "skills": ["x"], "request_id": "r",
                                            "mode": "borrow"})


def test_a_stale_child_is_the_subagent_refusal(conversations, monkeypatch):
    service, factory, _ = conversations
    scope, sid = opened(conversations)
    _recording(factory, monkeypatch, ConversationError(ConversationRefusal.NATIVE_REFUSAL,
                                                       native_code=ERROR_CODES[Refusal.STALE]))
    with pytest.raises(SubagentError) as caught:
        service.skills(scope, sid, "detail", {"child_ref": "gone", "skill_id": "review"})
    assert caught.value.reason == Refusal.STALE


def test_the_manifest_publishes_the_child_address_and_the_lend_verb():
    manifest = serve_rpc.manifest()
    assert "runtime.conversation.skills.lend" in manifest["methods"]
    assert manifest["tiers"]["runtime.conversation.skills.lend"] == "console"
    for operation in ("list", "detail", "history", "lend"):
        assert "child_ref" in manifest["params"]["runtime.conversation.skills." + operation]


_NOT_LOADABLE = {"reason": "skills_not_loadable", "rejected_skills": {"ghost": "missing"}}


def test_a_lend_refusal_reaches_the_caller_with_its_data(conversations, monkeypatch):
    """RT-NATIVE-PEER-DROPS-ERROR-DATA: the worker's ``eternia.skills.lend`` refusal (error
    ``data``) survives NativePeer.call, call_child and the serve's error reply."""
    from agent_runtime.conversations import rpc
    from agent_runtime.conversations.native_peer import PeerCore
    from agent_runtime.conversations.worker_skills import _skills_error

    class _Worker(PeerCore):
        alive = True

        def _send(self, frame, encoded):
            self._route(_skills_error(frame["id"], 4090, "One or more skills are not loadable.", _NOT_LOADABLE))

    with pytest.raises(ConversationError) as peer_refusal:
        _Worker(receive=lambda f: None, lost=lambda: None).call("eternia.skills.lend", {}, timeout=5)
    assert (peer_refusal.value.native_code, peer_refusal.value.native_data) == (4090, _NOT_LOADABLE)

    service, factory, _ = conversations
    scope, sid = opened(conversations)
    _recording(factory, monkeypatch, peer_refusal.value)
    with pytest.raises(ConversationError) as served:
        service.skills(scope, sid, "lend", {"child_ref": "child-1", "skills": ["ghost"], "request_id": "r1"})
    assert served.value.native_data == _NOT_LOADABLE

    handlers = {}
    monkeypatch.setattr(rpc, "execute", lambda *a, **k: (_ for _ in ()).throw(served.value))
    monkeypatch.setattr(rpc, "defer_or_refuse", lambda rid, name, context, run, **_: run())
    rpc.register(lambda name, tier: lambda fn: handlers.setdefault(name, fn),
                 ok=lambda rid, result: result, err=lambda rid, code, message, data: data)
    data = handlers["runtime.conversation.skills.lend"]("r", {}, type("C", (), {"caller": None, "launcher_request": None})())
    assert data["native_data"] == _NOT_LOADABLE and data["native_code"] == 4090


def test_a_lend_whose_outcome_is_unproven_stays_unknown(conversations, monkeypatch):
    """Control for the pass-through above: a write refusal with no typed reason is still unknown."""
    service, factory, _ = conversations
    scope, sid = opened(conversations)
    _recording(factory, monkeypatch, ConversationError(ConversationRefusal.NATIVE_REFUSAL, native_code=4090))
    with pytest.raises(SubagentError) as caught:
        service.skills(scope, sid, "lend", {"child_ref": "child-1", "skills": ["x"], "request_id": "r1"})
    assert caught.value.reason == Refusal.UNKNOWN
