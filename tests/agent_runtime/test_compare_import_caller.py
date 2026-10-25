"""Local Compare routes use the authenticated conversation actor, not the room label."""
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from agent_runtime.conversations.model import ConversationError
from agent_runtime.discussions.rpc import execute
from tests.agent_runtime.test_discussion_compare_import import source_archive
from tests.agent_runtime.test_discussion_group_migration import adoption, prepare, OWNER, WORKSPACE
from agent_runtime.call_authorization import LOCAL_CONSOLE
from tests.agent_runtime.test_discussion_rpc_refusals import _handlers

CONTEXT = SimpleNamespace(caller=LOCAL_CONSOLE, launcher_request=None)

__all__ = ["adoption"]


def test_compare_import_preserves_source_actor_across_prepare_and_finish(adoption):
    a = adoption
    prepare(a)
    source, raw = source_archive(a)

    def call(operation, *, source_actor="operator", **fields):
        return execute(a.service, "run." + operation,
            {"workspace_id": WORKSPACE, "client_scope": OWNER, **fields},
            actor_id="console-room-owner", conversation_actor_id=source_actor)

    with pytest.raises(ConversationError, match="conversation_unavailable"):
        call("prepare_compare", source_actor="another-device", source=source)
    run = call("prepare_compare", source=source)["run"]
    assert run["actor_id"] == "console-room-owner"
    call("append_compare", run_id=run["run_id"], index=0, data=base64.b64encode(raw).decode())
    with pytest.raises(ConversationError, match="conversation_unavailable"):
        call("finish_compare", source_actor="another-device", run_id=run["run_id"])
    finished = call("finish_compare", run_id=run["run_id"])["run"]
    assert finished["initial"]["compare_import"]["state"] == "complete"
    assert not a.native_calls


def test_public_compare_handler_uses_the_same_owner_as_direct_conversation_rpc(adoption, monkeypatch):
    from agent_runtime.conversations.model import caller_scope

    a = adoption
    source, raw = source_archive(a)
    archive = json.loads(raw)
    for member, saved in zip(source["members"], archive["rooms"][0]["sessions"]):
        profile = member["profile"]
        opened = a.conversations.open(caller_scope(CONTEXT.caller, OWNER, profile),
            key="saved-compare-" + profile, cwd=str(a.home), resume=None,
            expected_home=str(a.home / "profiles" / profile))
        member["session_id"] = opened["session_id"]
        saved["thread"] = json.dumps({"threads": [{"session": opened["session_id"]}]})
    raw = json.dumps(archive).encode()
    source.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    handlers = _handlers(a.service, monkeypatch)

    def call(operation, **params):
        reply = handlers["runtime.discussion.run." + operation](1,
            {"workspace_id": WORKSPACE, "client_scope": OWNER, **params}, CONTEXT)
        assert "error" not in reply, reply
        return reply["result"]

    run = call("prepare_compare", source=source)["run"]
    call("append_compare", run_id=run["run_id"], index=0, data=base64.b64encode(raw).decode())
    assert call("finish_compare", run_id=run["run_id"])["run"]["phase"] == "paused"
    assert not a.native_calls
