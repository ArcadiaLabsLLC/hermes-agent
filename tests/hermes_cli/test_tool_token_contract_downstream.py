"""Direct token-cost contract coverage, with a real registry and deterministic tokenizer boundary.

Builtin discovery is replaced by an inert import; these tests own their registry.
Positive control drops the wire wrapper. Killing mutation freezes generation.
"""
import importlib
import json
import sys
from types import ModuleType

import pytest

import hermes_cli.tools_config as tools_config


@pytest.fixture
def catalog(monkeypatch):
    registry_module = importlib.import_module("tools.registry")
    registry = registry_module.ToolRegistry()
    monkeypatch.setattr(registry_module, "registry", registry)
    monkeypatch.setattr(tools_config, "_tool_token_cache", None)
    monkeypatch.setitem(sys.modules, "model_tools", ModuleType("model_tools"))
    token_inputs = []

    class Encoder:
        def encode(self, text):
            token_inputs.append(text)
            return list(text.encode("utf-8"))

    def get_encoding(name):
        assert name == "cl100k_base"
        return Encoder()

    tokenizer = ModuleType("tiktoken")
    tokenizer.get_encoding = get_encoding
    monkeypatch.setitem(sys.modules, "tiktoken", tokenizer)
    return registry, token_inputs


def schema(description="Find a note"):
    return {"name": "find_note", "description": description,
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                           "required": ["query"]}}


def test_empty_registry_then_registration_counts_full_wire_shape(catalog):
    catalog, token_inputs = catalog
    assert tools_config._estimate_tool_tokens() == {}
    definition = schema()
    catalog.register("find_note", "notes", definition, lambda **kwargs: "")
    wire = json.dumps({"type": "function", "function": definition})
    expected = len(wire.encode("utf-8"))
    result = tools_config._estimate_tool_tokens()
    assert result == {"find_note": expected}
    assert tools_config._estimate_tool_tokens() is result
    assert token_inputs == [wire]


def test_changed_registry_generation_recalculates_cost(catalog):
    catalog, _ = catalog
    catalog.register("find_note", "notes", schema(), lambda **kwargs: "")
    original = tools_config._estimate_tool_tokens()
    catalog.register("find_note", "notes", schema("Find a note. " * 50), lambda **kwargs: "")
    changed = tools_config._estimate_tool_tokens()
    assert changed["find_note"] > original["find_note"]
    assert changed is not original


def test_same_generation_keeps_profile_catalogs_separate(catalog, monkeypatch, tmp_path):
    catalog, _ = catalog
    homes = [tmp_path / "one", tmp_path / "two"]
    for home in homes:
        home.mkdir()
    catalog.register("find_note", "notes", schema(), lambda **kwargs: "", scope=str(homes[0]))
    catalog.register("other_note", "notes", {**schema(), "name": "other_note"},
                     lambda **kwargs: "", scope=str(homes[1]))
    monkeypatch.setenv("HERMES_HOME", str(homes[0]))
    first = tools_config._estimate_tool_tokens()
    monkeypatch.setenv("HERMES_HOME", str(homes[1]))
    second = tools_config._estimate_tool_tokens()
    assert set(first) == {"find_note"}
    assert set(second) == {"other_note"}
    monkeypatch.setenv("HERMES_HOME", str(homes[0]))
    assert tools_config._estimate_tool_tokens() is first


def test_unavailable_tokenizer_returns_empty_costs(catalog, monkeypatch):
    catalog, _ = catalog
    catalog.register("find_note", "notes", schema(), lambda **kwargs: "")
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    assert tools_config._estimate_tool_tokens() == {}
