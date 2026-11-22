"""A setting written in config for an agent the install does not hold lists no agent.

Row ``RT-AN-AGENT-SETTING-IN-CONFIG-FOR-NO-AGENT-LISTS-A-PHANTOM-AGENT`` (review
w1118a.45 D2). Seen on disk 2026-11-19 (w1118a-hbase): a QA namespace's root
``config.yaml`` held only ``agent_runtime.personas.profile_base.chat_lane_restore_toolsets``
and the directory listed a "Profile Base" with a minted channel and no record. An
``agent_runtime.personas.<id>`` entry now declares an agent only when it carries an
identity key (``persona_records.PERSONA_IDENTITY_KEYS``); a settings-only entry
overlays the record of its id and declares nothing alone. The knob itself is read
from config by id, so it still reaches a stored agent of that id.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import instance_catalog, yaml_io
from agent_runtime.config import (
    AgentRuntimeConfig,
    chat_lane_restore_toolsets,
    ensure_persisted_personas,
    persona_records_from_config,
    persona_skill_sources,
)
from agent_runtime.models import AgentPersona
from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.store import AgentStore
from hermes_cli import profiles as profile_mod
from hermes_constants import get_config_path

UNUSED = "unused_helper"


@pytest.fixture
def namespace(monkeypatch):
    """An install with no profiles to discover; the test writes its root config."""

    monkeypatch.setattr(profile_mod, "list_profile_names", lambda: ["default"])
    monkeypatch.setattr(instance_catalog, "read_install_identity", lambda root: SimpleNamespace(install_id="install"))

    def write(personas: dict) -> None:
        from agent_runtime.parse_cache import clear_parse_cache

        config = get_config_path()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(yaml_io.dump({"agent_runtime": {"personas": personas}}, sort_keys=True), encoding="utf-8")
        clear_parse_cache()

    return write


def _directory_ids() -> set[str]:
    return {row["persona_id"] for row in instance_catalog.prepare_instance_catalog()["agents"]}


def _instance_persona_ids() -> set[str]:
    return {instance.persona_id for instance in PersonaInstanceStore().scan_all().instances}


def test_a_setting_for_an_id_no_record_holds_lists_no_agent_and_mints_no_channel(namespace):
    namespace({UNUSED: {"chat_lane_restore_toolsets": ["file", "terminal"]}})

    assert UNUSED not in _directory_ids()
    assert UNUSED not in _instance_persona_ids()
    assert UNUSED not in {persona.id for persona in ensure_persisted_personas()}
    # The setting is still there for the id, read by id.
    assert chat_lane_restore_toolsets(UNUSED) == ["file", "terminal"]


def test_an_entry_with_a_name_and_role_and_no_record_still_lists(namespace):
    namespace({UNUSED: {"role": "custom_helper", "display_name": "Unused Helper"}})

    # A template, not an agent: it lists as a persona to place, and no hidden copy is minted for it
    # (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT), so the instance directory holds nothing yet.
    assert UNUSED not in _instance_persona_ids()
    listed = {persona.id: persona for persona in ensure_persisted_personas()}
    assert (listed[UNUSED].display_name, listed[UNUSED].role) == ("Unused Helper", "custom_helper")


@pytest.mark.parametrize("key, value", [
    ("role", "custom_helper"),
    ("display_name", "Unused Helper"),
    ("hermes_profile", "base"),
    ("system_prompt_path", "prompts/helper.md"),
    ("soul_overlay_path", "souls/helper.md"),
    ("based_on", {"persona_id": "base"}),
])
def test_each_identity_key_declares_an_agent_alone(key, value):
    cfg = AgentRuntimeConfig(personas={UNUSED: {key: value, "iteration_budget": 7}})

    records = {persona.id: persona for persona in persona_records_from_config(cfg)}

    assert records[UNUSED].iteration_budget == 7


def test_the_setting_still_reaches_a_stored_agent_of_that_id(namespace):
    AgentStore().save(AgentPersona(
        id=UNUSED, display_name="Stored Helper", role="custom_helper", model=None, provider=None, api_mode=None,
    ))
    namespace({UNUSED: {"chat_lane_restore_toolsets": ["file", "terminal"], "skills": ["config-only-skill"]}})

    listed = [persona for persona in ensure_persisted_personas() if persona.id == UNUSED]
    assert [persona.display_name for persona in listed] == ["Stored Helper"]
    assert chat_lane_restore_toolsets(UNUSED) == ["file", "terminal"]
    # The config skill the store row does not carry is still named for the stored agent.
    sources = persona_skill_sources()
    assert sources[UNUSED]["catalog_only_skills"] == ["config-only-skill"]


def test_a_skills_setting_for_no_agent_gets_no_skill_source_row(namespace):
    namespace({UNUSED: {"skills": ["config-only-skill"]}})

    assert UNUSED not in persona_skill_sources()
