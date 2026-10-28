"""Shared helpers and the real Console binding, without persona execution."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent_runtime.suggestions.generation import clean_suggestion, generate_suggestion
from agent_runtime.console_suggestions import generation as console
from agent_runtime.console_suggestions.settings import SuggestionRefused, SuggestionSettings, suggestion_home


@pytest.mark.parametrize("raw,expected", [
    ('Suggestion: “Tell me more.”', 'Tell me more.'),
    ('«Sugerencia: Gracias»', 'Gracias'),
    ('Próximo mensaje: ‘好’', '好'),
    ('Next prompt: NULL.', None), ('“N/A!”', None), ('NONE…', None),
    ('NULL handling needs a test', 'NULL handling needs a test'),
    ('[foo] を説明して', '[foo] を説明して'), ('ありがとう', 'ありがとう'),
    ('Show `x[0]`', 'Show `x[0]`'), ('I prefer the second option.', 'I prefer the second option.'),
])
def test_cleaner_distinguishes_wrappers_and_sentinels_from_user_text(raw, expected):
    assert clean_suggestion(raw) == expected


def test_shared_generation_accepts_only_supplied_context_and_returns_actual_usage():
    messages = [{'role': 'user', 'content': '説明して'}, {'role': 'assistant', 'content': 'An English reply'}]
    before = deepcopy(messages)
    calls = []
    def complete(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text='“ありがとう”', provider='actual-provider', model='actual-model',
                               usage=SimpleNamespace(total_tokens=17, cost_usd=None))
    result = generate_suggestion(messages, complete)
    assert messages == before
    assert result == {'text': 'ありがとう', 'provider': 'actual-provider', 'model': 'actual-model',
                      'usage': {'total_tokens': 17, 'cost_usd': None}}
    assert len(calls) == 1
    assert calls[0]['messages'][1:] == messages
    assert "latest user's language" in calls[0]['messages'][0]['content']
    assert 'task' not in calls[0] and 'provider' not in calls[0]


def test_provider_error_reaches_existing_classifier_without_replacement():
    error = TimeoutError('private detail')
    def fail(**kwargs):
        raise error
    with pytest.raises(TimeoutError) as caught:
        generate_suggestion([], fail)
    assert caught.value is error


def test_codex_payload_keeps_complete_suggestion_policy_and_language():
    from agent.auxiliary_client import _CodexCompletionsAdapter
    from agent_runtime.suggestions.generation import SYSTEM
    adapter = _CodexCompletionsAdapter(
        SimpleNamespace(base_url='https://chatgpt.com/backend-api/codex'), 'gpt-5.6-sol')
    payloads = []
    def complete(**kwargs):
        payloads.append(adapter._build_responses_kwargs(kwargs)[0])
        return SimpleNamespace(text='好', provider='openai-codex', model='gpt-5.6-sol',
                               usage=SimpleNamespace(total_tokens=1))
    generate_suggestion([{'role': 'user', 'content': '解释缓存'},
                         {'role': 'assistant', 'content': 'A cache stores reusable data.'}], complete)
    assert SYSTEM in payloads[0]['instructions']
    assert 'even if the assistant replied' in payloads[0]['instructions']


def test_console_binding_keeps_task_scope_and_unload_local(tmp_path, monkeypatch):
    from hermes_cli import plugins
    from hermes_constants import get_hermes_home
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: SimpleNamespace(discover_and_load=lambda: None))
    calls, unloads = [], []
    def complete(**kwargs):
        calls.append((get_hermes_home(), kwargs))
        return SimpleNamespace(text='好', provider='host', model='resolved', usage=SimpleNamespace(total_tokens=1))
    ctx = SimpleNamespace(llm=SimpleNamespace(complete=complete),
                          register_auxiliary_task=lambda *a, **kw: None, on_unload=unloads.append)
    home, other = tmp_path/'one', tmp_path/'two'
    with suggestion_home(home):
        console.register_suggestion_task(ctx)
        assert console.generate_suggestion([{'role': 'user', 'content': '你好'}])['text'] == '好'
    with suggestion_home(other), pytest.raises(SuggestionRefused, match='plugin_unavailable'):
        console.generate_suggestion([])
    assert calls[0][0] == home
    assert calls[0][1]['task'] == 'console_next_prompt'
    assert not {'provider', 'model', 'profile', 'agent_id'} & calls[0][1].keys()
    unloads[0]()
    with suggestion_home(home), pytest.raises(SuggestionRefused, match='plugin_unavailable'):
        console.generate_suggestion([])


def test_console_route_does_not_copy_stock_override_or_persona_model(tmp_path):
    from hermes_cli.config import read_user_config_raw
    original = ('model:\n  default: host-model\n  provider: host-provider\n'
                'auxiliary:\n  next_prompt:\n    provider: stock-provider\n    model: stock-model\n'
                '  console_next_prompt:\n    timeout: 19\n    fallback_model: keep\n')
    path = tmp_path/'config.yaml'
    path.write_text(original, encoding='utf-8')
    policy = SuggestionSettings(tmp_path)
    assert policy.read()['enabled'] is False
    assert policy.read()['auxiliary_override'] is None
    policy.write({'expected_revision': policy.read()['settings_revision'],
                  'auxiliary_override': {'provider': 'override', 'model': 'override-model'}})
    assert policy.read()['auxiliary_override']['model'] == 'override-model'
    policy.write({'expected_revision': policy.read()['settings_revision'], 'auxiliary_override': None})
    with suggestion_home(tmp_path):
        config = read_user_config_raw()
    assert config['model'] == {'default': 'host-model', 'provider': 'host-provider'}
    assert config['auxiliary']['next_prompt'] == {'provider': 'stock-provider', 'model': 'stock-model'}
    assert config['auxiliary']['console_next_prompt'] == {'timeout': 19, 'fallback_model': 'keep'}
    assert policy.read()['enabled'] is False
