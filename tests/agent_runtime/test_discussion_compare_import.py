"""Local Compare history is retained without becoming replayable native work."""
import base64
import hashlib
import json

import pytest

from agent_runtime.discussions import compare_import_store
from agent_runtime.discussions.compare_archive import CHUNK_BYTES, read_archive
from agent_runtime.discussions.rpc import execute
from agent_runtime.discussions.run_values import DiscussionError
from agent_runtime.persona_assignments import PersonaInstanceStore
from tests.agent_runtime.test_discussion_group_migration import adoption, prepare, OWNER, WORKSPACE
from tests.agent_runtime.test_discussion_profile_groups import sends
from tests.agent_runtime.test_discussion_runtime import wait_until

__all__ = ["adoption"]


def source_archive(a, *, empty=False, padding=0):
    source_members, sessions = [], []
    for member in a.service.runs.members(a.run["run_id"])[:1 if empty else 2]:
        source_members.append({"member_id": member["member_id"], "profile": member["profile"],
            "session_id": None if empty else member["session_id"],
            "participant": {"install_id": a.install, "instance_id": a.agents[member["profile"]].id}})
        if not empty:
            sessions.append({"member": member["member_id"],
                "thread": json.dumps({"threads": [{"session": member["session_id"]}]})})
    raw = json.dumps({"version": 1, "rooms": [{"revision": 8,
        "definition": {"id": "local-compare", "title": "Saved Compare",
            "members": [{"id": m["member_id"]} for m in source_members]}, "sessions": sessions,
        "submissions": [{"old_removed_member": "retained", "delivery": "unknown", "text": "x" * padding}]}]}).encode()
    return {"id": "local-compare", "revision": 8, "name": "Saved Compare", "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(), "members": source_members}, raw


def rpc(a, op, *, owner=OWNER, **fields):
    return execute(a.service, "run." + op, {"workspace_id": WORKSPACE, "client_scope": owner, **fields},
                   actor_id="operator", conversation_actor_id="operator")


def upload(a, source, raw):
    run = rpc(a, "prepare_compare", source=source)["run"]
    for index, start in enumerate(range(0, len(raw), CHUNK_BYTES)):
        rpc(a, "append_compare", run_id=run["run_id"], index=index,
            data=base64.b64encode(raw[start:start + CHUNK_BYTES]).decode())
    return run


def test_archive_survives_partial_completion_and_native_compare_uses_exact_imported_context(adoption, monkeypatch):
    a = adoption
    prepare(a)
    source, raw = source_archive(a, padding=CHUNK_BYTES * 8)
    defaults = {p: PersonaInstanceStore().get(i.id).default_chat_session_id for p, i in a.agents.items()}
    run = upload(a, source, raw)
    assert a.service.pending_count() == 0
    assert not a.service.bindings() or all(b.room_id != run["run_id"] for b in a.service.bindings())
    with pytest.raises(DiscussionError, match="migration in progress"):
        rpc(a, "send", run_id=run["run_id"], expect_revision=run["revision"], idempotency_key="no-replay", message="No")
    with monkeypatch.context() as patch:
        patch.setattr(compare_import_store, "complete", lambda *args: (_ for _ in ()).throw(OSError("crash before switch")))
        with pytest.raises(OSError):
            rpc(a, "finish_compare", run_id=run["run_id"])
    assert a.service.runs.get(run["run_id"])["phase"] == "initializing"
    assert not a.native_calls
    completed = rpc(a, "finish_compare", run_id=run["run_id"])["run"]
    assert completed["phase"] == "paused"
    assert rpc(a, "finish_compare", run_id=run["run_id"])["run"] == completed
    assert rpc(a, "resolve_compare", source_id=source["id"])["run"] == completed
    assert read_archive(a.service, completed) == raw
    assert {p: PersonaInstanceStore().get(i.id).default_chat_session_id for p, i in a.agents.items()} == defaults
    cursor, pages = 0, 0
    while True:
        view = rpc(a, "get", run_id=run["run_id"], since_seq=cursor, limit=200)
        assert len(json.dumps(view).encode()) < 1024 * 1024
        cursor, pages = view["log"]["cursor"], pages + 1
        if not view["log"]["has_more"]:
            break
    assert pages >= 3 and not view["tasks"] and not a.native_calls
    rpc(a, "send", run_id=run["run_id"], expect_revision=completed["revision"], idempotency_key="next",
        message="Continue Compare", response={"mode": "compare", "members": []})
    wait_until(lambda: len(a.native_calls) == 2)
    assert len(sends(a.factory)) == 2


def test_incomplete_or_retargeted_archive_never_admits_execution_and_wrong_account_cannot_read(adoption):
    a = adoption
    source, raw = source_archive(a, empty=True)
    run = rpc(a, "prepare_compare", source=source)["run"]
    with pytest.raises(DiscussionError, match="archive incomplete"):
        rpc(a, "finish_compare", run_id=run["run_id"])
    changed = {**source, "sha256": "b" * 64}
    with pytest.raises(DiscussionError, match="migration target changed"):
        rpc(a, "prepare_compare", source=changed)
    with pytest.raises(DiscussionError, match="conversation owner changed"):
        rpc(a, "append_compare", owner="b" * 64, run_id=run["run_id"], index=0, data=base64.b64encode(raw).decode())
    assert rpc(a, "resolve_compare", owner="b" * 64, source_id=source["id"])["run"] is None
    upload(a, source, raw)
    completed = rpc(a, "finish_compare", run_id=run["run_id"])["run"]
    assert completed["phase"] == "paused"
    assert len(a.service.runs.members(run["run_id"])) == 1
    assert not a.native_calls and not sends(a.factory)
    with pytest.raises(DiscussionError, match="archive sealed"):
        rpc(a, "append_compare", run_id=run["run_id"], index=0, data=base64.b64encode(raw).decode())


def test_digest_failure_keeps_original_routes_executable_and_native_sessions_unminted(adoption):
    a = adoption
    prepare(a)
    source, raw = source_archive(a)
    source["sha256"] = "0" * 64
    run = upload(a, source, raw)
    with pytest.raises(DiscussionError, match="archive digest mismatch"):
        rpc(a, "finish_compare", run_id=run["run_id"])
    assert not a.native_calls
    for member in a.service.runs.members(a.run["run_id"]):
        from agent_runtime.conversations.model import ConversationScope
        route = a.conversations.store.get(member["session_id"], ConversationScope("operator", OWNER, member["profile"]))
        assert a.conversations.store.migration_target(route) is None


def test_prepare_recovers_room_creation_and_cannot_fork_same_source_into_another_workspace(adoption, monkeypatch):
    from agent_runtime.discussions import compare_import
    from tests.agent_runtime.office_seed import seed_workspace_record

    a = adoption
    source, raw = source_archive(a, empty=True)
    with monkeypatch.context() as patch:
        patch.setattr(compare_import, "_ensure_history_room", lambda *args: (_ for _ in ()).throw(OSError("after admission")))
        with pytest.raises(OSError):
            rpc(a, "prepare_compare", source=source)
    found = rpc(a, "resolve_compare", source_id=source["id"])["run"]
    recovered = upload(a, source, raw)
    assert recovered["run_id"] == found["run_id"]
    seed_workspace_record("ws_other_compare")
    with pytest.raises(DiscussionError, match="migration target changed"):
        execute(a.service, "run.prepare_compare", {"workspace_id": "ws_other_compare", "client_scope": OWNER,
            "source": source}, actor_id="operator", conversation_actor_id="operator")
    assert rpc(a, "finish_compare", run_id=recovered["run_id"])["run"]["phase"] == "paused"
    assert not a.native_calls and not sends(a.factory)
