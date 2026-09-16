"""Upstream documentation evolves independently of the fork's wire budget."""

from tools.downstream_schema import brief_schema, registered_full_description


def test_live_upstream_docs_are_preserved_without_mutating_schema(monkeypatch):
    from tools import downstream_schema
    from tools.tool_full_descriptions import full_tool_description

    monkeypatch.setattr(downstream_schema, '_registered_full', {})
    parameters = {'type': 'object', 'properties': {'path': {'type': 'string'}}}
    upstream = {'name': 'write_file', 'description': 'New upstream safety requirement',
                'parameters': parameters}
    wire = brief_schema('write_file', upstream)
    assert wire['description'] != upstream['description']
    assert upstream['description'] == 'New upstream safety requirement'
    assert wire['parameters'] is parameters
    assert full_tool_description('write_file') == upstream['description']
    updated = {**upstream, 'description': 'An additional upstream safety requirement'}
    brief_schema('write_file', updated)
    assert registered_full_description('write_file') == updated['description']


def test_unselected_schema_is_not_rewritten():
    schema = {'name': 'custom_plugin', 'description': 'Plugin-owned description'}
    assert brief_schema('custom_plugin', schema) is schema
