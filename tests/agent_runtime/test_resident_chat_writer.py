"""Real SQLite generations through actual fork resident acquisition/retirement."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import hermes_state_registry as writers
from agent_runtime.chat_session_writer import ChatSessionWriterLease, chat_session_writer_owner
from agent_runtime.mission_chat_outcome import MissionChatDeferredFinalization
from agent_runtime.persona_chat_durability import default_persona_session_db
from agent_runtime.persona_chat_continuity import runtime_registry as residents
from agent_runtime.profile_runner.execute import AgentRunExecution
from agent_runtime.profile_runner.models import AgentRunRequest
from tests.agent_runtime.test_chat_session_writer import canonical_scope, assert_closed  # noqa: F401


def owned_execution(registry, db, factory=None, *, root="root", signature="context", revision="revision", tip="tip", prewarm=False):
    request = AgentRunRequest(profile=None, root_chat_session_id=root, session_id=tip,
        persona_chat_runtime_registry=registry, persona_chat_runtime_signature=signature,
        persona_chat_native_revision=revision, prewarm_only=prewarm)
    execution = AgentRunExecution(SimpleNamespace(_session_db=db), None, request)
    execution.runtime = dict(provider="custom", model="test", api_mode="chat_completions")
    execution.construct_agent = factory or (lambda: SimpleNamespace(db=db, close=Mock()))
    execution.acquire_agent()
    return execution


def test_resident_serial_reuse_one_physical_writer(canonical_scope, monkeypatch):
    opens = []
    original = writers._open_session_db
    def opened(path):
        db = original(path); opens.append(db); return db
    monkeypatch.setattr(writers, "_open_session_db", opened)
    actors = residents.PersonaChatRuntimeRegistry()
    try:
        with chat_session_writer_owner():
            first = default_persona_session_db()
            a = owned_execution(actors, first)
            first.create_session("persist", "test")
        assert first._conn is not None
        with chat_session_writer_owner():
            second = default_persona_session_db()
            b = owned_execution(actors, second)
            assert b.agent is a.agent and b.agent.db is first is second
            assert b.agent.db.get_session("persist") is not None
        assert len(opens) == 1
        print("resident serial census: 2 turns, 1 physical writer, 1 resident owner")
    finally: actors.close()
    assert_closed(first)


@pytest.mark.parametrize("retire", ["signature", "revision", "tip", "lru", "ttl", "evict", "close", "reset", "disable", "close-error"])
def test_all_resident_retirement_paths_release_exact_generation(canonical_scope, monkeypatch, retire):
    actors = residents.initialize_persona_chat_runtime_registry(max_entries=1, ttl_seconds=1)
    clock = [1.0]
    monkeypatch.setattr(residents.time, "monotonic", lambda: clock[0])
    releases = []
    original = writers.release
    monkeypatch.setattr(writers, "release", lambda db: (releases.append(db), original(db))[-1])
    close = Mock(side_effect=RuntimeError("close error") if retire == "close-error" else None)
    try:
        with chat_session_writer_owner():
            db = default_persona_session_db()
            first = owned_execution(actors, db, lambda: SimpleNamespace(db=db, close=close))
        assert releases == [db]  # turn reference; resident remains
        if retire in {"signature", "revision", "tip", "lru", "ttl"}:
            clock[0] = 3.0 if retire == "ttl" else 1.0
            changes = {"signature":"changed"} if retire == "signature" else {"revision":"changed"} if retire == "revision" else {"tip":"newtip"} if retire == "tip" else {"root":"other"} if retire == "lru" else {}
            with chat_session_writer_owner():
                current = default_persona_session_db()
                second = owned_execution(actors, current, **changes)
                assert second.agent is not first.agent
                close.assert_called_once()
                assert current._conn is not None  # own current turn/resident unaffected
            actors.close()
        elif retire in {"reset", "disable"}:
            residents.initialize_persona_chat_runtime_registry(enabled=retire != "disable")
        elif retire == "evict": actors.evict("root")
        else: actors.close()
        close.assert_called_once()
        assert_closed(db)
        assert releases.count(db) == (4 if retire in {"signature", "revision", "tip", "lru", "ttl"} else 2)
        actors.close()  # idempotent
    finally: residents.initialize_persona_chat_runtime_registry(enabled=False)


def test_generation_replacement_rebuilds_without_stealing_tail(canonical_scope, monkeypatch):
    original = writers._stat_db_file_identity
    changed = [False]
    monkeypatch.setattr(writers, "_stat_db_file_identity", lambda path: ("replacement", original(path)) if changed[0] else original(path))
    actors = residents.PersonaChatRuntimeRegistry()
    tail = MissionChatDeferredFinalization()
    try:
        with chat_session_writer_owner() as owner:
            old = default_persona_session_db()
            first = owned_execution(actors, old)
            tail.defer(lambda: old.create_session("tail", "test"))
            assert owner.transfer_to(tail, old)
        changed[0] = True
        with chat_session_writer_owner():
            new = default_persona_session_db()
            second = owned_execution(actors, new)
            assert second.agent is not first.agent and new is not old
            assert second.timing["resident_rebuild_writer_generation_changed"] == 1
            assert old._conn is not None  # transferred tail still owns old
            assert tail.run_once()
            assert_closed(old)
            assert new._conn is not None
    finally: tail.cancel(); actors.close()
    assert_closed(new)


def test_pin_mismatch_releases_successor_and_never_constructs(canonical_scope, monkeypatch):
    actors = residents.PersonaChatRuntimeRegistry()
    with chat_session_writer_owner():
        old = default_persona_session_db()
        original = writers._stat_db_file_identity
        monkeypatch.setattr(writers, "_stat_db_file_identity", lambda path: ("changed", original(path)))
        factory = Mock()
        with pytest.raises(RuntimeError, match="generation changed"):
            owned_execution(actors, old, factory)
        factory.assert_not_called()
        assert writers.live_shared_session_dbs() == []  # successor released; old retired
        assert old._conn is not None
    assert_closed(old)
    actors.close()


@pytest.mark.parametrize("failure", ["constructor", "publication", "entry-build"])
def test_failed_construction_or_publication_releases_pin(canonical_scope, monkeypatch, failure):
    actors = residents.PersonaChatRuntimeRegistry()
    close = Mock()
    with chat_session_writer_owner():
        db = default_persona_session_db()
        def factory():
            if failure == "constructor": raise ValueError("failure")
            return SimpleNamespace(db=db, close=close)
        if failure == "publication": monkeypatch.setattr(actors, "_record_transition", Mock(side_effect=ValueError("failure")))
        if failure == "entry-build": monkeypatch.setattr(residents, "now_iso_micro", Mock(side_effect=ValueError("failure")))
        with pytest.raises(ValueError): owned_execution(actors, db, factory)
        assert db._conn is not None
        assert actors._entries == {}
    assert_closed(db)
    if failure != "constructor": close.assert_called_once()
    actors.close()


@pytest.mark.parametrize("mode", ["warmed", "refused", "yield", "yield-after-pin", "failed", "registry-off"])
def test_prewarm_request_owner_releases_or_transfers_to_resident(canonical_scope, monkeypatch, mode):
    from agent_runtime import persona_chat_actor_prewarm as prewarm
    from agent_runtime.profile_runner.errors import PrewarmYielded
    actors = residents.initialize_persona_chat_runtime_registry(enabled=mode != "registry-off")
    opened = []
    monkeypatch.setattr(prewarm, "_stand_down_outcome", lambda: None)
    def prepare(root, instance):
        db = default_persona_session_db(); opened.append(db)
        if mode == "refused": raise prewarm._PrewarmRefused(prewarm.OUTCOME_SKIPPED_PROFILE_UNREADY)
        def run(request):
            if mode == "yield": raise PrewarmYielded("test", "yield")
            if mode == "failed": raise ValueError("construction")
            execution = owned_execution(actors, db, root=root, prewarm=True)
            if mode == "yield-after-pin": raise PrewarmYielded("acquired", "yield")
            return execution.timing
        return SimpleNamespace(), SimpleNamespace(prewarm=run)
    monkeypatch.setattr(prewarm, "_prepare", prepare)
    try:
        outcome = prewarm.prewarm_chat_actor("root")
        if mode == "registry-off": assert not opened
        elif mode in {"warmed", "yield-after-pin"}:
            assert outcome == (prewarm.OUTCOME_WARMED if mode == "warmed" else "yield")
            with chat_session_writer_owner():
                current = default_persona_session_db()
                turn = owned_execution(actors, current)
                assert turn.agent.db is opened[0] is current and turn.timing["resident_actor_reused"] == 1
        else: assert_closed(opened[0])
    finally: residents.initialize_persona_chat_runtime_registry(enabled=False)
    if opened: assert_closed(opened[0])


def test_two_roots_with_different_canonical_heads_are_isolated(tmp_path):
    from tests.agent_runtime.test_chat_session_writer import scope_at
    actors = residents.PersonaChatRuntimeRegistry()
    try:
        with chat_session_writer_owner() as first:
            one = first.acquire(scope_at(tmp_path / "operator-one"))
            a = owned_execution(actors, one, root="one")
            one.create_session("only-one", "test")
        with chat_session_writer_owner() as second:
            two = second.acquire(scope_at(tmp_path / "operator-two"))
            b = owned_execution(actors, two, root="two")
            assert two is not one and b.agent is not a.agent
            assert two.get_session("only-one") is None
        actors.evict("one")
        assert_closed(one)
        assert two._conn is not None
    finally: actors.close()
    assert_closed(two)


def test_registry_reset_does_not_release_inflight_turn_or_transferred_tail(canonical_scope):
    actors = residents.initialize_persona_chat_runtime_registry()
    tail = MissionChatDeferredFinalization()
    with chat_session_writer_owner() as turn:
        db = default_persona_session_db()
        owned_execution(actors, db)
        residents.initialize_persona_chat_runtime_registry(enabled=False)
        assert db._conn is not None  # current turn still owns its reference
        db.create_session("turn-after-reset", "test")
        tail.defer(lambda: db.create_session("tail-after-reset", "test"))
        assert turn.transfer_to(tail, db)
    assert db._conn is not None
    assert tail.run_once()
    assert_closed(db)


def test_resident_refuses_unowned_writer_before_constructor(canonical_scope):
    from hermes_state import SessionDB
    actors = residents.PersonaChatRuntimeRegistry()
    db = SessionDB(db_path=canonical_scope.db_path)
    factory = Mock()
    try:
        with pytest.raises(RuntimeError, match="no request owner"):
            owned_execution(actors, db, factory)
        factory.assert_not_called()
    finally: db.close(); actors.close()


def test_actual_prewarm_runner_and_first_run_keep_constructor_writer(canonical_scope, monkeypatch):
    from agent_runtime import persona_chat_actor_prewarm as prewarm
    from agent_runtime.profile_runner import ProfileAgentRunner
    from tests.agent_runtime.test_persona_chat_actor_prewarm import _Agent, _request
    actors = residents.initialize_persona_chat_runtime_registry()
    agents = []
    def factory(**kwargs):
        agent = _Agent(**kwargs); agent.db = kwargs["session_db"]
        agents.append(agent); return agent
    monkeypatch.setattr("agent_runtime.profile_runner.execute.resolve_runtime_provider", lambda provider, model: dict(provider=provider, model=model, api_mode="chat_completions"))
    monkeypatch.setattr(prewarm, "_stand_down_outcome", lambda: None)
    def prepare(root, instance):
        db = default_persona_session_db()
        return _request(prewarm_only=True, registry=actors, provider="custom"), ProfileAgentRunner(agent_factory=factory, session_db=db)
    monkeypatch.setattr(prewarm, "_prepare", prepare)
    try:
        assert prewarm.prewarm_chat_actor("chat_root_1") == prewarm.OUTCOME_WARMED
        assert len(agents) == 1 and agents[0].conversations == 0
        original = agents[0].db
        assert original._conn is not None
        with chat_session_writer_owner():
            current = default_persona_session_db()
            result = ProfileAgentRunner(agent_factory=factory, session_db=current).run(_request(prewarm_only=False, registry=actors, provider="custom"))
            assert result.profile_timing["resident_actor_reused"] == 1
            assert len(agents) == 1 and agents[0].db is current is original
            assert agents[0].conversations == 1
    finally: residents.initialize_persona_chat_runtime_registry(enabled=False)
    assert_closed(original)


def test_concurrent_turn_tail_and_retirement_keep_independent_references(canonical_scope, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    actors = residents.PersonaChatRuntimeRegistry()
    ready, retire, exited = threading.Event(), threading.Event(), threading.Event()
    tail = MissionChatDeferredFinalization()
    releases = []
    original = writers.release
    monkeypatch.setattr(writers, "release", lambda db: (releases.append(db), original(db))[-1])
    def concurrent_turn(expected):
        with chat_session_writer_owner():
            current = default_persona_session_db()
            assert current is expected
            ready.set()
            assert retire.wait(10)
            current.create_session("concurrent", "test")
        exited.set()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with chat_session_writer_owner() as first:
                db = default_persona_session_db()
                owned_execution(actors, db)
                future = pool.submit(concurrent_turn, db)
                assert ready.wait(10)
                tail.defer(lambda: db.create_session("tail", "test"))
                assert first.transfer_to(tail, db)
            actors.close()  # release only resident; concurrent turn and tail remain
            assert releases == [db] and db._conn is not None
            retire.set()
            future.result(timeout=10)
            assert exited.is_set() and releases == [db, db]
            assert db._conn is not None
            assert tail.run_once()
            assert releases == [db, db, db]
            assert_closed(db)
    finally: retire.set(); tail.cancel(); actors.close()


def test_interrupted_registry_close_drains_every_resident_writer(canonical_scope):
    actors = residents.PersonaChatRuntimeRegistry()
    other_close = Mock()
    with chat_session_writer_owner():
        db = default_persona_session_db()
        owned_execution(actors, db, lambda: SimpleNamespace(db=db, close=Mock(side_effect=KeyboardInterrupt())), root="one")
        owned_execution(actors, db, lambda: SimpleNamespace(db=db, close=other_close), root="two")
    with pytest.raises(KeyboardInterrupt): actors.close()
    other_close.assert_called_once()
    assert_closed(db)
    actors.close()
