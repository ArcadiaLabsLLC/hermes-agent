"""The persona-level ``toolsets`` list is gone — refused in config, stripped from the store.

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md``
§3 slice 1 (second half), ruling R2 in §6. The list admitted nothing since S0a A1;
the bound profile's ``toolsets:`` is the one declaration. These pin both carriers:
the root-config key (refused at load, typed) and the store row ``agents/<id>.json``
(the LIVE carrier — Neko's list sat there, not in the root config), migrated once.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime.config import AgentRuntimeConfig, persona_records_from_config
from agent_runtime.errors import LegacyPersonaToolsetsRefused
from agent_runtime.models import AgentPersona


def test_a_persona_level_toolsets_key_is_refused_at_load():
    cfg = AgentRuntimeConfig(
        personas={"neko_supervisor": {"hermes_profile": "base", "toolsets": ["file", "terminal"]}}
    )

    with pytest.raises(LegacyPersonaToolsetsRefused) as raised:
        persona_records_from_config(cfg)

    assert raised.value.code == "persona_toolsets_key_refused"
    assert raised.value.safe_details["key"] == "agent_runtime.personas.neko_supervisor.toolsets"
    # The refusal names the ONE declaration, so the fix is in the message.
    assert "toolsets:" in str(raised.value)
    assert "file, terminal" in str(raised.value)


def test_the_same_persona_without_the_key_loads():
    """Positive control for the refusal: the key is the cause, not the persona."""

    cfg = AgentRuntimeConfig(personas={"neko_supervisor": {"hermes_profile": "base"}})

    records = {persona.id: persona for persona in persona_records_from_config(cfg)}

    assert records["neko_supervisor"].hermes_profile == "base"
    assert not hasattr(records["neko_supervisor"], "toolsets")


def _legacy_row(store_root, persona_id: str = "neko_supervisor") -> object:
    from agent_runtime.store import AgentStore

    AgentStore().save(
        AgentPersona(
            id=persona_id,
            display_name="Neko Mission Lead",
            role="pm",
            model=None,
            provider=None,
            api_mode=None,
            hermes_profile="base",
        )
    )
    path = store_root / "agents" / f"{persona_id}.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["toolsets"] = ["file", "search", "terminal"]  # what a pre-2026-10-08 writer left
    path.write_text(json.dumps(row, indent=2, sort_keys=True), encoding="utf-8")
    return path


def test_the_store_migration_strips_the_legacy_list(isolate_agent_runtime_root):
    from agent_runtime import paths
    from agent_runtime.persona_toolsets_migration import (
        marker_path,
        migrate_legacy_persona_toolsets_once,
    )
    from agent_runtime.store import AgentStore

    store_root = paths.store_root()
    path = _legacy_row(store_root)
    # The row already LOADS without the attribute (serde keeps declared fields);
    # the migration is what makes the disk agree.
    assert not hasattr(AgentStore().get("neko_supervisor"), "toolsets")

    report = migrate_legacy_persona_toolsets_once()

    assert "toolsets" not in json.loads(path.read_text(encoding="utf-8"))
    assert [row["persona_id"] for row in report["stripped"]] == ["neko_supervisor"]
    assert report["stripped"][0]["toolsets"] == ["file", "search", "terminal"]
    assert report["errors"] == []
    assert AgentStore().get("neko_supervisor").hermes_profile == "base"
    assert marker_path(store_root).exists()
    # One-shot: the marker makes the next start a single stat.
    assert migrate_legacy_persona_toolsets_once() is None


def test_a_row_without_the_key_is_left_byte_identical(isolate_agent_runtime_root):
    """Positive control for the strip: only a row that carries the key is rewritten."""

    from agent_runtime import paths
    from agent_runtime.persona_toolsets_migration import strip_legacy_persona_toolsets
    from agent_runtime.store import AgentStore

    AgentStore().save(
        AgentPersona(id="dev", display_name="Dev", role="dev", model=None, provider=None, api_mode=None)
    )
    clean = paths.store_root() / "agents" / "dev.json"
    before = clean.read_bytes()

    report = strip_legacy_persona_toolsets(paths.store_root())

    assert report["stripped"] == []
    assert clean.read_bytes() == before
