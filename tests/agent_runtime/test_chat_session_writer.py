"""R011: real temp writers, request ownership and deferred generation transfer."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import hermes_state_registry as registry
from hermes_state import SessionDB
from agent_runtime.chat_session_scope import (
    ChatHeadSource, ChatSessionScope, SessionDbAccess, open_chat_session_db,
)
from agent_runtime.chat_session_writer import (
    ChatSessionWriterLease, chat_session_writer_owner,
)
from agent_runtime.mission_chat_outcome import MissionChatDeferredFinalization
from agent_runtime.persona_chat_durability import (
    PersonaChatPersistenceError, default_persona_session_db,
)


def scope_at(path):
    return ChatSessionScope(path, ChatHeadSource.ENV_HEAD_HOME)


def assert_closed(db):
    assert db._conn is None
    assert db not in registry.live_shared_session_dbs()


@pytest.fixture
def canonical_scope(tmp_path, monkeypatch):
    import agent_runtime.chat_session_scope as scopes
    import hermes_constants
    scope = scope_at(tmp_path / "operator")
    monkeypatch.setattr(scopes, "resolve_process_chat_scope", lambda: scope)
    monkeypatch.setattr(hermes_constants, "get_hermes_home_override", lambda: None)
    return scope


def test_old_overlapping_opens_three_new_turn_owners_one(canonical_scope, monkeypatch):
    opens = []
    original = SessionDB.__init__
    def counted(self, *args, **kwargs):
        original(self, *args, **kwargs)
        opens.append(self)
    monkeypatch.setattr(SessionDB, "__init__", counted)
    old = [open_chat_session_db(canonical_scope, access=SessionDbAccess.WRITE) for _ in range(3)]
    try:
        assert len({id(db) for db in old}) == len(opens) == 3
    finally:
        for db in old:
            db.close()
    opens.clear()
    barrier = threading.Barrier(3)
    def turn(index):
        with chat_session_writer_owner():
            db = default_persona_session_db()
            assert default_persona_session_db() is db
            barrier.wait(timeout=10)
            db.create_session(f"turn-{index}", "test")
            barrier.wait(timeout=10)
            return db
    with ThreadPoolExecutor(max_workers=3) as pool:
        dbs = list(pool.map(turn, range(3)))
    assert len({id(db) for db in dbs}) == len(opens) == 1
    assert_closed(dbs[0])
    print("writer census: old overlapping opens=3; owned overlapping opens=1; turn references=3; final live=0")


def test_sequential_turns_have_no_assumed_serve_owner(canonical_scope):
    with chat_session_writer_owner():
        first = default_persona_session_db()
    assert_closed(first)
    with chat_session_writer_owner():
        second = default_persona_session_db()
    assert second is not first
    assert_closed(second)


def test_two_roots_and_existing_registry_owner_are_independent(tmp_path):
    first_scope, second_scope = scope_at(tmp_path / "one"), scope_at(tmp_path / "two")
    existing = registry.acquire(first_scope.db_path)
    try:
        with chat_session_writer_owner() as owner:
            first, second = owner.acquire(first_scope), owner.acquire(second_scope)
            assert first is existing and second is not first
            first.create_session("one", "test")
            second.create_session("two", "test")
            assert second.get_session("one") is None
        assert first.get_session("one") is not None
        assert_closed(second)
    finally:
        registry.release(existing)
    assert_closed(existing)


@pytest.mark.parametrize("failure", [False, True])
def test_turn_return_or_failure_releases_exactly_once(canonical_scope, monkeypatch, failure):
    released = []
    original = registry.release
    def counted(db):
        released.append(db)
        return original(db)
    monkeypatch.setattr(registry, "release", counted)
    db = None
    def command():
        nonlocal db
        with chat_session_writer_owner():
            db = default_persona_session_db()
            if failure:
                raise RuntimeError("admission failed")
            return 2
    if failure:
        with pytest.raises(RuntimeError, match="admission failed"):
            command()
    else:
        assert command() == 2
    assert released == [db]
    assert_closed(db)


def test_acquire_failure_publishes_no_lease(canonical_scope, monkeypatch):
    def fail(path):
        raise OSError("unavailable")
    monkeypatch.setattr(registry, "acquire", fail)
    baseline = registry.live_shared_session_dbs()
    with chat_session_writer_owner():
        with pytest.raises(PersonaChatPersistenceError) as error:
            default_persona_session_db()
        assert error.value.operation == "session_db_acquire"
    assert registry.live_shared_session_dbs() == baseline


def test_unresolved_override_still_refuses_before_registry(canonical_scope, monkeypatch):
    import agent_runtime.chat_session_scope as scopes
    import hermes_constants
    monkeypatch.setattr(scopes, "resolve_process_chat_scope", lambda: ChatSessionScope(canonical_scope.head_home, ChatHeadSource.AMBIENT_HOME))
    monkeypatch.setattr(hermes_constants, "get_hermes_home_override", lambda: canonical_scope.head_home)
    monkeypatch.setattr(registry, "acquire", lambda path: pytest.fail("unauthorized acquire"))
    with chat_session_writer_owner():
        with pytest.raises(PersonaChatPersistenceError):
            default_persona_session_db()


def test_async_tail_owns_writer_after_real_dispatch_and_turn_exit(canonical_scope, monkeypatch):
    from hermes_cli.harness_parts.persona.chat_turn_message import _run_deferred_tail
    from hermes_cli.harness_parts import serve
    monkeypatch.setattr(serve, "current_serve_request_id", lambda: "test-owned-tail")
    entered, finish, done = threading.Event(), threading.Event(), threading.Event()
    releases = []
    original = registry.release
    def counted(db):
        releases.append(db)
        return original(db)
    monkeypatch.setattr(registry, "release", counted)
    deferred = MissionChatDeferredFinalization()
    worker = None
    try:
        with chat_session_writer_owner():
            db = default_persona_session_db()
            def tail():
                entered.set()
                assert finish.wait(10)
                db.create_session("tail-write", "test")
                done.set()
            deferred.defer(tail)
            _run_deferred_tail(deferred, session_db=db)
            assert entered.wait(10)
        assert db._conn is not None and releases == []
        assert deferred.cancel() is False  # running child still owns it
    finally:
        finish.set()
        for worker in threading.enumerate():
            if worker.name == "chat-turn-deferred":
                worker.join(10)
    assert done.is_set()
    assert releases == [db]
    assert_closed(db)


@pytest.mark.parametrize("mode", ["cancel", "raise", "constructor", "start"])
def test_tail_cancel_failure_or_rejected_launch_releases(canonical_scope, monkeypatch, mode):
    deferred = MissionChatDeferredFinalization()
    calls, releases = [], []
    original = registry.release
    def counted(db):
        releases.append(db)
        return original(db)
    monkeypatch.setattr(registry, "release", counted)
    with chat_session_writer_owner() as owner:
        db = default_persona_session_db()
        def tail():
            calls.append(db.get_session("missing"))
            if mode == "raise":
                raise RuntimeError("title failed")
        deferred.defer(tail)
        assert owner.transfer_to(deferred, db)
        if mode == "cancel":
            assert deferred.cancel()
            assert not deferred.cancel()
            assert not deferred.run_once()
        elif mode == "raise":
            assert not deferred.run_once()
        else:
            class RejectedThread:
                def __init__(self, **kwargs):
                    if mode == "constructor":
                        raise RuntimeError("thread construction rejected")
                def start(self):
                    raise RuntimeError("start rejected")
            monkeypatch.setattr(threading, "Thread", RejectedThread)
            assert deferred.run_off_path() is None
        assert releases == [db]
    assert releases == [db]
    assert calls == ([] if mode == "cancel" else [None])
    assert_closed(db)


def test_no_tail_keeps_turn_owner_and_idempotent_lease_close(canonical_scope):
    with chat_session_writer_owner() as owner:
        db = default_persona_session_db()
        assert not owner.transfer_to(MissionChatDeferredFinalization(), db)
    assert_closed(db)
    lease = ChatSessionWriterLease(canonical_scope)
    lease.close()
    lease.close()
    assert_closed(lease.db)


def test_replacement_generation_does_not_steal_transferred_reference(canonical_scope, monkeypatch):
    # Simulate the external file identity transition at the registry's OS probe;
    # both generations remain real temp SQLite writers, no private ref mutation.
    original_identity = registry._stat_db_file_identity
    changed = False
    def identity(path):
        actual = original_identity(path)
        return ("replacement", actual) if changed else actual
    monkeypatch.setattr(registry, "_stat_db_file_identity", identity)
    deferred = MissionChatDeferredFinalization()
    with chat_session_writer_owner() as first:
        old = default_persona_session_db()
        deferred.defer(lambda: old.create_session("old-tail", "test"))
        assert first.transfer_to(deferred, old)
    changed = True
    with chat_session_writer_owner():
        new = default_persona_session_db()
        assert new is not old
        assert old._conn is not None
        assert deferred.run_once()
        assert_closed(old)
        assert new._conn is not None
        new.create_session("new-turn", "test")
    assert_closed(new)


@pytest.mark.usefixtures("persisted_persona_samples")
def test_real_command_early_refusal_closes_its_canonical_writer(canonical_scope, monkeypatch, capsys, isolate_agent_runtime_root):
    from tests.agent_runtime.test_chat_lease_finalization_tail import _install_chat_lane, _args
    from hermes_cli.harness_parts.persona import chat_turn_message
    _install_chat_lane(monkeypatch)
    opened = []
    def real_factory():
        db = default_persona_session_db()
        opened.append(db)
        return db
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", real_factory)
    args = _args("writer-early-refusal")
    args.session_id = "persona_chat_missing_writer_test"
    assert chat_turn_message._cmd_mission_chat_message(args) == 2
    assert "unknown_chat_session" in capsys.readouterr().out
    assert len(opened) == 1
    assert_closed(opened[0])


@pytest.mark.parametrize("boundary", ["cancel", "run"])
def test_concurrent_tail_consumers_release_once(canonical_scope, monkeypatch, boundary):
    deferred = MissionChatDeferredFinalization()
    released, called = [], []
    original = registry.release
    def release(db):
        released.append(db)
        return original(db)
    monkeypatch.setattr(registry, "release", release)
    with chat_session_writer_owner() as owner:
        db = default_persona_session_db()
        deferred.defer(lambda: called.append(db.get_session("missing")))
        assert owner.transfer_to(deferred, db)
        barrier = threading.Barrier(4)
        def consume(_):
            barrier.wait(10)
            return deferred.cancel() if boundary == "cancel" else deferred.run_once()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(consume, range(4)))
        assert results.count(True) == 1
        assert released == [db]
    assert called == ([] if boundary == "cancel" else [None])
    assert released == [db]
    assert_closed(db)


def test_interrupted_launch_releases_before_propagating(canonical_scope, monkeypatch):
    deferred = MissionChatDeferredFinalization()
    with chat_session_writer_owner() as owner:
        db = default_persona_session_db()
        deferred.defer(lambda: pytest.fail("interrupted tail must not run"))
        assert owner.transfer_to(deferred, db)
        def interrupt(**kwargs):
            raise KeyboardInterrupt()
        monkeypatch.setattr(threading, "Thread", interrupt)
        with pytest.raises(KeyboardInterrupt):
            deferred.run_off_path()
        assert_closed(db)


@pytest.mark.usefixtures("persisted_persona_samples")
def test_real_command_exception_after_acquisition_releases(canonical_scope, monkeypatch, isolate_agent_runtime_root):
    from tests.agent_runtime.test_chat_lease_finalization_tail import _install_chat_lane, _args
    from hermes_cli.harness_parts.persona import chat_turn_message
    _install_chat_lane(monkeypatch)
    opened = []
    def real_factory():
        db = default_persona_session_db()
        opened.append(db)
        return db
    monkeypatch.setattr(chat_turn_message, "_default_persona_session_db", real_factory)
    def fail_store(**kwargs):
        raise RuntimeError("pre-admission preparation failed")
    monkeypatch.setattr(chat_turn_message, "PersonaInstanceStore", fail_store)
    with pytest.raises(RuntimeError, match="pre-admission preparation failed"):
        chat_turn_message._cmd_mission_chat_message(_args("writer-exception"))
    assert len(opened) == 1
    assert_closed(opened[0])


def test_writer_close_must_not_leave_resident_actor_with_closed_generation(canonical_scope):
    """Actual fork reuse retains an independently owned constructor generation."""
    from types import SimpleNamespace
    from unittest.mock import Mock
    from agent_runtime.persona_chat_continuity.runtime_registry import PersonaChatRuntimeRegistry
    from tests.agent_runtime.test_resident_chat_writer import owned_execution
    actors = PersonaChatRuntimeRegistry()
    try:
        with chat_session_writer_owner():
            first_db = default_persona_session_db()
            first = owned_execution(actors, first_db, lambda: SimpleNamespace(_session_db=first_db, close=Mock()))
        with chat_session_writer_owner():
            second_db = default_persona_session_db()
            second = owned_execution(actors, second_db, lambda: SimpleNamespace(_session_db=second_db, close=Mock()))
            assert second.agent is first.agent  # actual fork reuse path
            assert second.agent._session_db._conn is not None, "resident actor retained a closed turn writer"
    finally:
        actors.evict("root")
