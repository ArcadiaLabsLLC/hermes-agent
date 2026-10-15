"""Worker-owned link lifetime, through construction and the gateway close path."""
from __future__ import annotations

import threading
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from agent_runtime import launcher_app_functions as app
from agent_runtime.conversations import worker_app_functions as worker

_REAL_EMIT = worker._Sink.emit


class Agent:
    # The worker must work with an agent that accepts no fork-owned attributes.
    __slots__ = ('closed',)

    def __init__(self, **kwargs):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    app._reset_for_tests()
    monkeypatch.setattr(worker, 'install', lambda: None)
    requests = []

    def answer(sink, frame):
        requests.append((sink, frame))
        app.CLIENT_REQUESTS.resolve({'id': frame['id'], 'result': {'tools': [{
            'name': 'launcher_generated_list', 'method': 'launcher.generated.list',
            'description': 'Read the component catalog.', 'always_loaded': True,
            'parameters': {'type': 'object', 'properties': {}},
        }]}}, sink)

    monkeypatch.setattr(worker._Sink, 'emit', answer)
    yield requests
    app._reset_for_tests()


def session():
    return {'source': 'eternia_intelligence', 'history_lock': threading.RLock()}


def link_for(sid, owner):
    token = worker.bind(sid, owner)
    try:
        return app.current_launcher_link()
    finally:
        worker.reset(token)


def test_slot_agent_and_replacement_share_the_session_link_without_another_catalog_call(catalog):
    owner = session()
    owner['agent'] = worker.create_agent(Agent, 'sid', owner, enabled_toolsets=[])
    first = link_for('sid', owner)
    owner['agent'] = worker.create_agent(Agent, 'sid', owner, enabled_toolsets=[])
    assert link_for('sid', owner) is first
    assert len(catalog) == 1
    assert app.current_launcher_link() is None


def test_same_sid_in_two_session_records_never_shares_a_link(catalog):
    first, second = session(), session()
    first['agent'] = worker.create_agent(Agent, 'sid', first)
    second['agent'] = worker.create_agent(Agent, 'sid', second)
    assert link_for('sid', first) is not link_for('sid', second)
    assert len(catalog) == 2


def test_wrong_sid_does_not_retarget_or_retire_the_owning_record(catalog):
    owner = session()
    owner['agent'] = worker.create_agent(Agent, 'sid', owner)
    first = link_for('sid', owner)
    assert link_for('foreign', owner) is None
    assert link_for('sid', owner) is first
    assert len(catalog) == 1


@pytest.mark.parametrize('gate', ['_closing', '_finalized'])
def test_retired_session_cannot_rebind_or_reconstruct(gate, catalog):
    owner = session()
    owner['agent'] = worker.create_agent(Agent, 'sid', owner)
    old = link_for('sid', owner)
    owner[gate] = True
    assert link_for('sid', owner) is None
    assert old.sink.closed
    with pytest.raises(RuntimeError, match='closed|unavailable'):
        worker.create_agent(Agent, 'sid', owner)
    assert len(catalog) == 1


def test_losing_native_source_releases_only_that_sessions_cached_catalog(catalog):
    first, other = session(), session()
    first['agent'] = worker.create_agent(Agent, 'first', first)
    other['agent'] = worker.create_agent(Agent, 'other', other)
    retired = link_for('first', first)
    surviving = link_for('other', other)
    first['source'] = 'terminal'
    assert link_for('first', first) is None
    assert retired.sink.closed
    token = app.bind_launcher_link(surviving)
    try:
        assert app.always_loaded_app_function_tools() == {'launcher_generated_list'}
    finally:
        app.reset_launcher_link(token)


def test_first_construction_failure_releases_the_catalog_and_restores_outer_scope(catalog):
    owner = session()
    failed_links = []

    def fail(**kwargs):
        failed_links.append(app.current_launcher_link())
        raise ValueError('factory failed')

    with pytest.raises(ValueError, match='factory failed'):
        worker.create_agent(fail, 'sid', owner)
    assert failed_links[0].sink.closed
    assert not app._state.catalog
    assert app.current_launcher_link() is None
    owner['agent'] = worker.create_agent(Agent, 'sid', owner)
    assert link_for('sid', owner) is not failed_links[0]
    assert len(catalog) == 2


def test_failed_replacement_retains_the_live_agents_binding(catalog):
    owner = session()
    owner['agent'] = worker.create_agent(Agent, 'sid', owner)
    first = link_for('sid', owner)

    def fail(**kwargs):
        raise ValueError('replacement failed')

    with pytest.raises(ValueError, match='replacement failed'):
        worker.create_agent(fail, 'sid', owner)
    assert link_for('sid', owner) is first
    assert not first.sink.closed
    assert len(catalog) == 1


def test_teardown_during_construction_closes_the_discarded_agent_and_catalog(catalog):
    owner = session()
    built = []

    def factory(**kwargs):
        agent = Agent()
        built.append(agent)
        owner['_closing'] = True
        worker.close(owner)
        return agent

    with pytest.raises(RuntimeError, match='closed|unavailable'):
        worker.create_agent(factory, 'sid', owner)
    assert built[0].closed
    assert not app._state.catalog
    assert app.current_launcher_link() is None


def test_close_can_finish_while_factory_is_running_on_another_thread(catalog):
    owner = session()
    entered, resume = threading.Event(), threading.Event()
    built = []

    def factory(**kwargs):
        built.append(Agent())
        entered.set()
        assert resume.wait(5)
        return built[-1]

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(worker.create_agent, factory, 'sid', owner)
        try:
            assert entered.wait(5)
            owner['_closing'] = True
            worker.close(owner)
        finally:
            resume.set()
        with pytest.raises(RuntimeError, match='closed|unavailable'):
            future.result(timeout=5)
    assert built[0].closed
    assert not app._state.catalog


def test_close_after_discovery_reply_cannot_resurrect_the_catalog(monkeypatch, catalog):
    owner = session()
    answer = worker._Sink.emit

    def reply_then_close(sink, frame):
        answer(sink, frame)
        owner['_closing'] = True
        worker.close(owner)

    monkeypatch.setattr(worker._Sink, 'emit', reply_then_close)
    with pytest.raises(RuntimeError, match='closed|unavailable'):
        worker.create_agent(lambda **kw: pytest.fail('closed discovery built an agent'), 'sid', owner)
    assert len(catalog) == 1
    assert not app._state.catalog
    assert app.current_launcher_link() is None


def test_unlinked_factory_preserves_its_arguments_without_discovery(catalog):
    seen = []
    owner = {'source': 'terminal'}
    agent = worker.create_agent(lambda **kw: seen.append(kw) or Agent(), 'sid', owner, enabled_toolsets=['file'])
    assert isinstance(agent, Agent)
    assert seen == [{'enabled_toolsets': ['file']}]
    assert not catalog
    assert link_for('sid', owner) is None


def test_gateway_teardown_releases_the_exact_link_even_when_agent_close_raises(monkeypatch, catalog):
    from tui_gateway import server
    owner, other = session(), session()
    owner['agent'] = worker.create_agent(Agent, 'sid', owner)
    other['agent'] = worker.create_agent(Agent, 'other', other)
    retired = link_for('sid', owner)
    survivor = link_for('other', other)
    monkeypatch.setattr(server, '_finalize_session', lambda *a, **kw: None)
    monkeypatch.setattr(server, '_announce_session_reclaimed', lambda *a, **kw: None)
    monkeypatch.setattr(server, '_session_profile_runtime_scope', lambda _: nullcontext())

    class BrokenClose:
        def close(self):
            raise RuntimeError('close failed')

    owner['agent'] = BrokenClose()
    server._teardown_session(owner)
    server._teardown_session(owner)
    assert retired.sink.closed
    assert not survivor.sink.closed
    token = app.bind_launcher_link(survivor)
    try:
        assert app.always_loaded_app_function_tools() == {'launcher_generated_list'}
    finally:
        app.reset_launcher_link(token)


def test_closed_sink_refuses_locally_without_a_server_request(monkeypatch):
    from tui_gateway import server_requests
    sink = worker._Sink('sid')
    # Exercise the real emitter rather than the catalog fixture's responder.
    monkeypatch.setattr(worker._Sink, 'emit', _REAL_EMIT)
    sink.close()
    replies = []
    monkeypatch.setattr(worker, 'resolve_response', lambda reply, _: replies.append(reply))
    monkeypatch.setattr(server_requests, 'send', lambda *a, **kw: pytest.fail('retired connection sent a request'))
    worker._Sink.emit(sink, {'id': 'closed', 'method': app.LIST_METHOD})
    assert replies[0]['error']['code'] == -32000


@pytest.fixture
def gateway(monkeypatch):
    from tui_gateway import server
    from agent import shell_hooks
    import run_agent

    monkeypatch.setattr(server, '_sessions', {})
    monkeypatch.setattr(run_agent, 'AIAgent', lambda **kw: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(shell_hooks, 'register_from_config', lambda cfg: None)
    for name, value in {
        '_load_cfg': {}, '_startup_system_prompt': '', '_load_provider_routing': {},
        '_load_reasoning_config': None, '_load_service_tier': None,
        '_load_enabled_toolsets': [], '_load_disabled_toolsets': [], '_load_fallback_model': None,
        '_load_prefill_messages': [], '_agent_cbs': {}, '_load_show_reasoning': False,
        '_load_tool_progress_mode': 'off', '_completion_cwd': '.', '_session_info': {},
    }.items():
        monkeypatch.setattr(server, name, lambda *a, _value=value, **kw: _value)
    monkeypatch.setattr(server, '_resolve_agent_model_runtime', lambda *a: ('test', {}))
    for name in ('_hydrate_session_cwd', '_register_session_cwd', '_wire_session_agent',
                 '_start_session_services', '_emit', '_schedule_mcp_late_refresh', '_session_todo_state'):
        monkeypatch.setattr(server, name, lambda *a, **kw: None)
    monkeypatch.setattr(server, '_profile_build_scope', lambda *a: nullcontext())
    monkeypatch.setattr(server, '_transfer_db_to_agent', lambda *a: False)
    monkeypatch.setattr(server, '_maybe_schedule_auto_continue', lambda *a: None)
    return server


def resume_context():
    return SimpleNamespace(
        mint=lambda: ('resume', 'eternia_intelligence', '.'), restore=lambda: ([], [], []),
        display_prefix=lambda: [], profile_home=None, target='stored', db=None, found={},
        profile_resume_cwd='', owns_db=False, cols=80, rid='request')


def test_real_eager_resume_transfers_the_discovered_link_to_the_registered_session(gateway, monkeypatch, catalog):
    monkeypatch.setattr(gateway, '_find_live_session_by_key', lambda *a: None)
    monkeypatch.setattr(gateway, '_resume_response', lambda *a, **kw: {'result': 'resumed'})
    assert gateway._resume_eager(resume_context()) == {'result': 'resumed'}
    registered = gateway._sessions['resume']
    original_sink = catalog[0][0]
    assert link_for('resume', registered).sink is original_sink
    registered['agent'] = gateway._make_agent('resume', 'stored')
    assert link_for('resume', registered).sink is original_sink
    assert len(catalog) == 1


def test_registered_session_owns_the_connection_before_any_visible_side_effect(gateway, monkeypatch, catalog):
    monkeypatch.setattr(gateway, '_find_live_session_by_key', lambda *a: None)
    monkeypatch.setattr(gateway, '_resume_response', lambda *a, **kw: {'result': 'resumed'})
    observed = []

    def first_registration_io(sid, *a):
        # A resumed client or another turn can see the record at this point.
        observed.append(link_for(sid, gateway._sessions[sid]))

    monkeypatch.setattr(gateway, '_hydrate_session_cwd', first_registration_io)
    assert gateway._resume_eager(resume_context()) == {'result': 'resumed'}
    assert observed[0].sink is catalog[0][0]
    assert link_for('resume', gateway._sessions['resume']) is observed[0]
    assert len(catalog) == 1


def test_duplicate_eager_resume_closes_its_abandoned_connection(gateway, monkeypatch, catalog):
    monkeypatch.setattr(gateway, '_find_live_session_by_key', lambda *a: ('winner', {}))
    monkeypatch.setattr(gateway, '_resume_reuse_live_locked', lambda *a: {'result': 'winner'})
    assert gateway._resume_eager(resume_context()) == {'result': 'winner'}
    assert catalog[0][0].closed
    assert not app._state.catalog

@pytest.mark.parametrize('stage', ['hydrate', 'response'])
def test_eager_resume_failure_releases_the_connection_before_or_after_registration(
        stage, gateway, monkeypatch, catalog):
    monkeypatch.setattr(gateway, '_find_live_session_by_key', lambda *a: None)

    def fail(*a, **kw):
        raise ValueError('registration failed')

    monkeypatch.setattr(gateway, '_hydrate_session_cwd' if stage == 'hydrate' else '_resume_response', fail)
    if stage == 'hydrate':
        assert 'error' in gateway._resume_eager(resume_context())
    else:
        with pytest.raises(ValueError, match='registration failed'):
            gateway._resume_eager(resume_context())
    assert catalog[0][0].closed
    assert not app._state.catalog
    assert link_for('resume', gateway._sessions['resume']) is None
    assert len(catalog) == 1


def test_real_branch_build_has_an_independent_registered_connection(gateway, catalog):
    parent = session()
    parent.update(cwd='.', cols=80)
    parent['agent'] = worker.create_agent(Agent, 'parent', parent)
    parent_link = link_for('parent', parent)
    gateway._build_branch_agent(parent, 'branch', 'stored', [], 'eternia_intelligence')
    branch = gateway._sessions['branch']
    assert link_for('branch', branch).sink is catalog[1][0]
    assert link_for('parent', parent) is parent_link
    assert len(catalog) == 2


@pytest.mark.parametrize('fallback', [False, True])
def test_real_compute_host_transfers_the_link_even_with_minimal_session_fallback(
        fallback, gateway, monkeypatch, catalog):
    from tui_gateway.compute_host import ComputeHost
    host = SimpleNamespace(_transport=SimpleNamespace())
    if fallback:
        def fail(*a, **kw):
            raise ValueError('side machinery failed')
        monkeypatch.setattr(gateway, '_hydrate_session_cwd', fail)
    registered = ComputeHost._build_server_session(host, gateway, {
        'sid': 'host', 'session_key': 'stored', 'source': 'eternia_intelligence'}, 'host')
    assert link_for('host', registered).sink is catalog[0][0]
    assert registered['source'] == 'eternia_intelligence'
    registered['agent'] = gateway._make_agent('host', 'stored')
    assert len(catalog) == 1
