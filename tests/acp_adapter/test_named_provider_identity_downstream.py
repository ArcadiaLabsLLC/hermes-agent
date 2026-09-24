"""Named ACP endpoints retain routing identity, not just the generic transport."""
import json
from types import SimpleNamespace

import pytest

from acp_adapter.server import HermesACPAgent
from acp_adapter.session import SessionManager, agent_provider_identity
from hermes_constants import get_hermes_home
from hermes_state import SessionDB


@pytest.fixture
def routed_session(monkeypatch, tmp_path):
    config = {
        'model': {'provider': 'custom:east', 'default': 'shared-model'},
        'providers': {
            name: {'name': name, 'base_url': f'http://127.0.0.1:{port}/v1',
                   'api_key': f'test-{name}', 'models': ['shared-model'],
                   'discover_models': False}
            for name, port in [('east', 18081), ('west', 18082)]
        },
        'platform_toolsets': {'acp': []},
        'mcp_servers': {},
    }
    (get_hermes_home() / 'config.yaml').write_text(json.dumps(config), encoding='utf-8')

    def agent(**kwargs):
        kwargs.setdefault('requested_provider', kwargs.get('provider'))
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr('run_agent.AIAgent', agent)
    monkeypatch.setattr('hermes_cli.mcp_startup.ensure_mcp_discovery_before_agent_build', lambda **kw: None)
    database = SessionDB(tmp_path / 'sessions.db')
    manager = SessionManager(db=database)
    state = manager.create_session(cwd=str(tmp_path))
    state.history = [{'role': 'user', 'content': 'Local route regression.'}]
    try:
        yield HermesACPAgent(session_manager=manager), manager, state, database
    finally:
        database.close()


def assert_west(server, state):
    assert state.agent.provider == 'custom'
    assert state.agent.requested_provider == 'custom:west'
    assert state.agent.base_url == 'http://127.0.0.1:18082/v1'
    assert state.agent.api_key == 'test-west'
    assert server._build_model_state(state).current_model_id == 'custom:west:shared-model'


def test_named_route_survives_apply_fork_and_restart(routed_session):
    server, manager, state, database = routed_session
    server._switch_model(state, 'custom:west:shared-model')
    assert_west(server, state)
    manager.save_session(state.session_id)
    metadata = json.loads(database.get_session(state.session_id)['model_config'])
    assert metadata['provider'] == 'custom'
    assert metadata['requested_provider'] == 'custom:west'
    assert 'api_key' not in metadata
    forked = manager.fork_session(state.session_id, cwd=state.cwd)
    assert_west(server, forked)
    assert forked.history[0]['content'] == state.history[0]['content']
    restored = SessionManager(db=database).get_session(state.session_id)
    assert_west(server, restored)
    assert restored.history[0]['content'] == state.history[0]['content']

    # Automatic selection and canonical aliases must still report the resolved route.
    for provider, requested in [('openrouter', 'auto'), ('custom', 'auto'), ('anthropic', 'claude')]:
        assert agent_provider_identity(SimpleNamespace(provider=provider, requested_provider=requested)) == provider


def test_unqualified_switch_keeps_named_route_and_failed_rebuild_keeps_agent(routed_session, monkeypatch):
    server, manager, state, database = routed_session
    server._switch_model(state, 'custom:west:shared-model')
    server._switch_model(state, 'shared-model', keep_endpoint=True)
    assert_west(server, state)
    previous = state.agent
    def fail_build(**kwargs):
        raise RuntimeError('Test construction failure')

    monkeypatch.setattr(manager, '_make_agent', fail_build)
    with pytest.raises(RuntimeError, match='Test construction failure'):
        server._switch_model(state, 'custom:east:shared-model')
    assert state.agent is previous
    assert_west(server, state)
