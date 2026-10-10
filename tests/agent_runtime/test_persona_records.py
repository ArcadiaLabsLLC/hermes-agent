"""The persona-level ``toolsets`` list is gone — refused in config, stripped from the store.

The refusal is a typed issue row, never a raise: on 2026-10-09 the raise took the live
serve's snapshot producer down on every rebuild (five operator profile configs carried
the key; the config read feeds the producer).

Plan: ``docs/agent-runtime-harness/planned/tool-visibility-authority-split-2026-10-08.md``
§3 slice 1 (second half), ruling R2 in §6. The list admitted nothing since S0a A1;
the bound profile's ``toolsets:`` is the one declaration. These pin both carriers:
the root-config key (refused at load, typed) and the store row ``agents/<id>.json``
(the LIVE carrier — Neko's list sat there, not in the root config), migrated once.
"""

from __future__ import annotations

import json
import textwrap

from agent_runtime.config import AgentRuntimeConfig, merge_persisted_personas, persona_records_from_config
from agent_runtime.config.persona_records import legacy_persona_toolsets_issues
from agent_runtime.models import AgentPersona
from agent_runtime.personas import DeclarationIssueKind


_LEGACY_PROFILE_CONFIG = """# operator comment that must survive
model:
  default: gpt-5.5   # inline comment
agent_runtime:
  personas:
    neko_supervisor:
      hermes_profile: gpt-launcher
      toolsets:   # legacy list
        - file
        - terminal
      display_name: Neko
"""


def _active_profile_config(monkeypatch, body: str):
    """Point the serve's active config (``HERMES_HOME`` = a profile home) at ``body``."""

    from agent_runtime.parse_cache import clear_parse_cache
    from hermes_cli.profiles import get_profile_dir
    from hermes_constants import get_config_path

    home = get_profile_dir("gpt-launcher")
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    path = get_config_path()
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    clear_parse_cache()
    return path


def test_a_profile_config_carrying_the_key_keeps_the_producer_serving(monkeypatch, bundled_persona_profiles):
    """The live failure: a profile config with the key must not raise out of the
    config read the snapshot producer runs; it yields exactly ONE typed issue row."""

    from agent_runtime.config import load_agent_runtime_config
    from agent_runtime.persona_profiles import declared_lane_toolsets

    path = _active_profile_config(monkeypatch, _LEGACY_PROFILE_CONFIG)
    cfg = load_agent_runtime_config()

    records = {persona.id: persona for persona in persona_records_from_config(cfg)}
    merged = {persona.id: persona for persona in merge_persisted_personas([], cfg)}

    assert records["neko_supervisor"].display_name == "Neko"
    assert not hasattr(records["neko_supervisor"], "toolsets")
    assert set(merged) == set(records)
    issues = [
        issue
        for issue in declared_lane_toolsets(records["neko_supervisor"]).issues
        if issue.kind is DeclarationIssueKind.LEGACY_PERSONA_TOOLSETS_KEY
    ]
    assert len(issues) == 1
    row = issues[0].row(entry_point_lane="mission_chat")
    assert row["code"] == "persona_toolsets_key_refused"
    assert row["subject"] == "agent_runtime.personas.neko_supervisor.toolsets"
    assert row["config_path"] == str(path)
    # The refusal names the ONE declaration, so the fix is in the row.
    assert "toolsets:" in row["fix_hint"]


def test_the_issue_scan_names_each_carrier_once():
    personas = {
        "neko_supervisor": {"hermes_profile": "base", "toolsets": ["file", "terminal"]},
        "dev": {"hermes_profile": "base"},
    }

    issues = legacy_persona_toolsets_issues(personas)

    assert [(issue.kind, issue.detail) for issue in issues] == [
        (DeclarationIssueKind.LEGACY_PERSONA_TOOLSETS_KEY, "agent_runtime.personas.neko_supervisor.toolsets")
    ]
    assert legacy_persona_toolsets_issues(personas, persona_id="dev") == ()


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


def test_the_config_migration_strips_the_key_from_every_profile_config(bundled_persona_profiles):
    """The second carrier: ``profiles/*/config.yaml``. Comments and other keys survive; idempotent."""

    from agent_runtime import yaml_io

    from agent_runtime.persona_toolsets_migration import strip_legacy_persona_toolsets_from_configs
    from hermes_cli.profiles import get_profile_dir
    from hermes_constants import get_default_hermes_root

    legacy = get_profile_dir("gpt-launcher") / "config.yaml"
    legacy.write_text(_LEGACY_PROFILE_CONFIG, encoding="utf-8")
    clean = get_profile_dir("qa") / "config.yaml"
    clean.write_text("# untouched\nagent_runtime:\n  personas:\n    qa: {hermes_profile: qa}\n", encoding="utf-8")
    clean_before = clean.read_bytes()

    report = strip_legacy_persona_toolsets_from_configs(get_default_hermes_root())

    assert report == {"stripped": [{"path": str(legacy), "persona_id": "neko_supervisor"}], "errors": []}
    text = legacy.read_text(encoding="utf-8")
    assert "# operator comment that must survive" in text
    assert "# inline comment" in text
    loaded = yaml_io.load(text)
    assert loaded["model"] == {"default": "gpt-5.5"}
    assert loaded["agent_runtime"]["personas"]["neko_supervisor"] == {
        "hermes_profile": "gpt-launcher",
        "display_name": "Neko",
    }
    assert clean.read_bytes() == clean_before
    after = legacy.read_bytes()
    assert strip_legacy_persona_toolsets_from_configs(get_default_hermes_root()) == {"stripped": [], "errors": []}
    assert legacy.read_bytes() == after
