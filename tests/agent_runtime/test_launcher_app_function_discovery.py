"""Host-owned eager discovery through the real catalog, assembly and wire middleware."""
from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from agent_runtime import launcher_app_functions as app
from tests.agent_runtime.test_launcher_app_functions import _Launcher
from tools.downstream_schema import brief_request_tools
from tools.tool_search import ToolSearchConfig, assemble_tool_defs, dispatch_tool_describe

_CATALOG = [
    {"name": "launcher_generated_list", "method": "launcher.generated.list",
     "description": "Render side-by-side comparisons and mocks directly in chat using this catalog. Full component manual and resource restrictions follow.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
     "always_loaded": True, "reach": "localOnly"},
    {"name": "launcher_generated_create", "method": "launcher.generated.create",
     "description": "Display an editable in-chat output using the catalog's Composition/Text or WebArtifact. Full creation manual and refusal instructions follow.",
     "parameters": {"type": "object", "properties": {"document_json": {"type": "string", "description": "JSON array from the catalog."}}, "required": ["document_json"], "additionalProperties": False},
     "always_loaded": True, "reach": "localOnly"},
    {"name": "launcher_generated_inspect", "method": "launcher.generated.inspect",
     "description": "Read the saved output and full catalog.",
     "parameters": {"type": "object", "properties": {}}, "reach": "localOnly"},
]
_CFG = ToolSearchConfig.from_raw({"enabled": "on", "listing": "full"})


@pytest.fixture(autouse=True)
def clean():
    import model_tools
    app._reset_for_tests()
    model_tools._clear_tool_defs_cache()
    yield
    app._reset_for_tests()
    model_tools._clear_tool_defs_cache()


@contextmanager
def linked(launcher, origin=app.ORIGIN_LOCAL):
    link = app.LauncherLink(launcher, origin)
    app.refresh_app_function_tools(link)
    token = app.bind_launcher_link(link)
    try:
        yield link
    finally:
        app.reset_launcher_link(token)


def raw_defs():
    from tools.registry import registry
    return registry.get_definitions([tool['name'] for tool in _CATALOG], quiet=True)


def names(defs):
    return {tool['function']['name'] for tool in defs}


@pytest.mark.parametrize('flag,expected', [(True, True), (False, False), (None, False), ('true', False), (1, False)])
def test_only_a_boolean_host_opt_in_promotes_a_tool(flag, expected):
    catalog = deepcopy(_CATALOG)
    catalog[0]['always_loaded'] = flag
    with linked(_Launcher(catalog)):
        result = assemble_tool_defs(raw_defs(), config=_CFG)
        assert ('launcher_generated_list' in names(result.tool_defs)) is expected
        assert 'launcher_generated_create' in names(result.tool_defs)
        assert 'launcher_generated_inspect' not in names(result.tool_defs)


def test_generic_host_metadata_wins_over_persona_deferral_without_granting_an_unoffered_tool():
    from dataclasses import replace
    from tools.registry import registry
    catalog = [{**_CATALOG[0], 'name': 'launcher_canvas_publish', 'method': 'launcher.canvas.publish'}]
    with linked(_Launcher(catalog)):
        raw = registry.get_definitions(['launcher_canvas_publish'], quiet=True)
        cfg = replace(_CFG, defer_tools=frozenset({'launcher_canvas_publish', 'launcher_generated_create'}))
        result = assemble_tool_defs(raw, config=cfg)
        assert 'launcher_canvas_publish' in names(result.tool_defs)
        assert 'launcher_generated_create' not in names(result.tool_defs)


def test_promotion_is_owned_by_the_bound_connection_and_origin_and_forgotten_on_close():
    eager = _Launcher(_CATALOG)
    old = _Launcher([{k: v for k, v in tool.items() if k != 'always_loaded'} for tool in _CATALOG])
    with linked(eager):
        assert app.always_loaded_app_function_tools() == {'launcher_generated_list', 'launcher_generated_create'}
        with linked(old):
            assert app.always_loaded_app_function_tools() == set()
        # Registry now holds the old connection: promotion must still come from our bound link.
        assert app.always_loaded_app_function_tools() == {'launcher_generated_list', 'launcher_generated_create'}
        app.forget_launcher_connection(eager)
        assert app.always_loaded_app_function_tools() == set()
    assert app.always_loaded_app_function_tools() == set()
    with linked(eager, app.ORIGIN_PAIRED_DEVICE):
        assert app.always_loaded_app_function_tools() == set()
    paired = _Launcher([{**_CATALOG[0], 'reach': 'pairedDevice'}])
    with linked(paired, app.ORIGIN_PAIRED_DEVICE):
        assert app.always_loaded_app_function_tools() == {'launcher_generated_list'}


def test_memo_keeps_linked_unlinked_and_other_connection_definitions_separate(monkeypatch):
    import model_tools
    monkeypatch.setattr('tools.tool_search.load_config', lambda: _CFG)
    # All unrelated plugin discovery is already done by model_tools' import.
    eager = _Launcher(_CATALOG)
    with linked(eager):
        first = model_tools.get_tool_definitions([app.APP_FUNCTIONS_TOOLSET], quiet_mode=True)
        cache = dict(model_tools._tool_defs_cache)
        assert {'launcher_generated_list', 'launcher_generated_create'} <= names(first)
        assert model_tools.get_tool_definitions([app.APP_FUNCTIONS_TOOLSET], quiet_mode=True) == first
        assert model_tools._tool_defs_cache == cache  # warm hit, no new key or wire read
    unlinked = model_tools.get_tool_definitions([app.APP_FUNCTIONS_TOOLSET], quiet_mode=True)
    assert not (names(unlinked) & {t['name'] for t in _CATALOG})
    # Same catalog/generation: proves the connection key, not registry invalidation.
    other = _Launcher(_CATALOG)
    with linked(other):
        assert model_tools._tool_defs_cache_key([app.APP_FUNCTIONS_TOOLSET], None, False) not in cache
    assert len(eager.sent) == 1


def test_redeclaration_changes_the_memo_scope_even_when_the_registry_is_unchanged(monkeypatch):
    import model_tools
    monkeypatch.setattr('tools.tool_search.load_config', lambda: _CFG)
    first = _Launcher(_CATALOG)
    legacy = [{k: v for k, v in tool.items() if k != 'always_loaded'} for tool in _CATALOG]
    # Another link's prewarm may sync its catalog before our constructor runs.
    with linked(first) as link:
        app.refresh_app_function_tools(app.LauncherLink(_Launcher(legacy), app.ORIGIN_LOCAL))
        eager = model_tools.get_tool_definitions([app.APP_FUNCTIONS_TOOLSET], quiet_mode=True)
        assert 'launcher_generated_create' in names(eager)
        old_key = model_tools._tool_defs_cache_key([app.APP_FUNCTIONS_TOOLSET], None, False)
        app.forget_launcher_connection(first)
        first.tools = legacy
        app.refresh_app_function_tools(link)
        new_key = model_tools._tool_defs_cache_key([app.APP_FUNCTIONS_TOOLSET], None, False)
        assert new_key != old_key, 'a retired catalog must not lend its discovery policy to its replacement'
        current = model_tools.get_tool_definitions([app.APP_FUNCTIONS_TOOLSET], quiet_mode=True)
        assert 'launcher_generated_create' not in names(current)


@pytest.mark.parametrize('shape', ['chat', 'responses', 'anthropic'])
def test_provider_wire_is_brief_and_structural_schema_and_full_manual_are_preserved(shape):
    with linked(_Launcher(_CATALOG)):
        raw = raw_defs()
        assembled = assemble_tool_defs(raw, config=_CFG).tool_defs
        if shape == 'chat':
            wire = brief_request_tools({'tools': assembled})['tools']
            entry = next(t['function'] for t in wire if t['function']['name'] == 'launcher_generated_create')
            params = entry['parameters']
        else:
            converted = [{**t['function'], **({'input_schema': t['function']['parameters']} if shape == 'anthropic' else {}), 'type': 'function'} for t in assembled]
            wire = brief_request_tools({'tools': converted})['tools']
            entry = next(t for t in wire if t['name'] == 'launcher_generated_create')
            params = entry['input_schema'] if shape == 'anthropic' else entry['parameters']
        assert 'Composition/Text' in entry['description']
        assert 'Full creation manual' not in entry['description']
        assert params == _CATALOG[1]['parameters']
        full = dispatch_tool_describe({'names': ['launcher_generated_create']}, current_tool_defs=raw, config=_CFG)
        assert 'Full creation manual' in json.dumps(full)
        assert _CATALOG[1]['description'] == next(t['function']['description'] for t in raw if t['function']['name'] == 'launcher_generated_create')


def test_continued_and_restarted_sessions_append_entry_points_to_the_existing_prefix(monkeypatch):
    from tools.mcp_tool_agent import restore_agent_tool_prefix
    monkeypatch.setattr('tools.mcp_tool_agent.tool_pin_version', lambda: 'new-code')
    with linked(_Launcher(_CATALOG)):
        fresh = assemble_tool_defs(raw_defs(), config=_CFG).tool_defs
        old = [t for t in fresh if t['function']['name'] not in {'launcher_generated_list', 'launcher_generated_create'}]
        for version in ['new-code', 'previous-code']:
            agent = SimpleNamespace(tools=fresh[:], valid_tool_names=names(fresh), enabled_toolsets=[app.APP_FUNCTIONS_TOOLSET], disabled_toolsets=None)
            restore_agent_tool_prefix(agent, {'version': version, 'tools': old})
            assert {'launcher_generated_list', 'launcher_generated_create'} <= names(agent.tools)
            assert agent.tools[:len(old)] == old


def test_eager_call_still_uses_the_single_dispatcher_and_honors_refusal():
    from tools.registry import registry
    launcher = _Launcher(_CATALOG, refuse={'launcher.generated.create'})
    with linked(launcher):
        eager = assemble_tool_defs(raw_defs(), config=_CFG).tool_defs
        assert 'launcher_generated_create' in names(eager)
        answer = json.loads(registry.dispatch('launcher_generated_create', {'document_json': '[]'}))
        assert answer['refusal'] == 'permission_refused'
        assert launcher.sent[-1]['method'] == 'launcher.generated.create'
        assert launcher.sent[-1]['params']['_meta']['origin'] == 'local'


def test_native_worker_retains_its_own_relay_and_eager_policy_on_continued_turns(monkeypatch):
    from agent_runtime.conversations import worker_app_functions as worker
    launcher = _Launcher(_CATALOG)
    monkeypatch.setattr(worker, 'install', lambda: None)
    monkeypatch.setattr(worker._Sink, 'emit', lambda sink, frame: app.CLIENT_REQUESTS.resolve(launcher._answer(frame), sink))
    observed = []

    def factory(**kwargs):
        observed.append(kwargs['enabled_toolsets'])
        return SimpleNamespace(tools=assemble_tool_defs(raw_defs(), config=_CFG).tool_defs)

    agent = worker.create_agent(factory, 'native-1', {'source': 'eternia_intelligence'}, enabled_toolsets=[])
    assert observed == [[app.APP_FUNCTIONS_TOOLSET]]
    assert {'launcher_generated_list', 'launcher_generated_create'} <= names(agent.tools)
    original = agent._launcher_app_function_link
    for _ in range(2):
        token = worker.bind('native-1', {'source': 'eternia_intelligence', 'agent': agent})
        try:
            assert app.current_launcher_link() is original
            assert app.always_loaded_app_function_tools() == {'launcher_generated_list', 'launcher_generated_create'}
        finally:
            worker.reset(token)
    token = worker.bind('native-2', {'source': 'eternia_intelligence', 'agent': agent})
    try:
        assert app.current_launcher_link() is not original
        assert app.always_loaded_app_function_tools() == set()
    finally:
        worker.reset(token)
    token = worker.bind('native-1', {'source': 'terminal', 'agent': agent})
    try:
        assert app.current_launcher_link() is None
    finally:
        worker.reset(token)
