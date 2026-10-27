"""Fork half of ``test_session_policy.py::test_launch_options_reach_the_owner_frozen_and_hooks_consented``.

Upstream counts every ``pre_tool_call`` hook and expects exactly the consented shell hook. In this
fork ``session.create`` discovers plugins, and the always-on ``eternia-harness`` plugin registers
``refuse_tool_call`` (``plugins/eternia-harness/__init__.py``) in the same list. So the guarantee is
split: the consented shell hook registers exactly once, a request-id retry re-registers nothing, and
the fork's refusal hook rides beside it (row FH-SESSION-POLICY-HOOK-COUNT-RED).
"""

import pytest


def _pre_tool_call_hooks():
    from hermes_cli.plugins import get_plugin_manager

    hooks = get_plugin_manager()._hooks.get('pre_tool_call', [])
    shell = [h for h in hooks if getattr(h, '__name__', '').startswith('shell_hook[')]
    return hooks, shell


@pytest.mark.asyncio
async def test_launch_hooks_register_once_beside_the_fork_refusal_hook(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gateway import run
    from gateway.config import GatewayConfig
    from gateway.session import SessionStore
    from gateway.session_authority import initialize_session_authority
    from gateway.session_controls import AuthorityConnection
    from agent import shell_hooks
    from hermes_cli.plugins import get_plugin_manager

    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.delenv('HERMES_ACCEPT_HOOKS', raising=False)
    hook = tmp_path / 'hook.sh'
    hook.write_text('#!/bin/sh\nexit 0\n')
    cfg = {'platform_toolsets': {'cli': []}, 'hooks': {'pre_tool_call': [{'command': str(hook)}]}}
    monkeypatch.setattr(run, '_load_gateway_config', lambda: cfg)
    monkeypatch.setattr(run, '_resolve_gateway_model', lambda config: 'fixture')
    monkeypatch.setattr(get_plugin_manager(), '_hooks', {})
    shell_hooks.reset_for_tests()
    store = SessionStore(tmp_path / 'sessions', GatewayConfig())
    runner = SimpleNamespace(session_store=store, _session_db=store._db, adapters={}, _draining=False,
                             _cached_agent_for=lambda route: None)
    runner._adapter_for_source = lambda source: runner.adapters.get(source.platform)
    authority = await initialize_session_authority(runner, profile_id=str(home), instance_id='first')
    connection = AuthorityConnection(authority, object(), {'user_id': 'human'})

    async def create(request_id):
        reply = await connection.dispatch({'id': 1, 'method': 'session.create', 'params': {
            'request_id': request_id, 'source': 'tui', 'cwd': str(tmp_path), 'accept_hooks': True}})
        return reply.get('result', {}).get('session_id') or reply['error']['message']

    sid = await create('launch')
    assert sid.startswith('local-'), sid
    hooks, shell = _pre_tool_call_hooks()
    assert [h.__name__ for h in shell] == [f'shell_hook[pre_tool_call:{hook}]']
    assert any(getattr(h, '__name__', '') == 'refuse_tool_call' for h in hooks), hooks
    # Retrying the request id resumes the frozen route; nothing re-registers.
    assert await create('launch') == sid
    assert _pre_tool_call_hooks()[0] == hooks
