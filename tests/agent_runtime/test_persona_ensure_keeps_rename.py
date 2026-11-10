"""An operator rename of a canonical instance survives ``ensure_for_persona``.

RT-PERSONA-ENSURE-REVERTS-INSTANCE-RENAME (launcher MC-PROFILE-NAME-REVERTED-ON-RELAUNCH):
every snapshot build runs ``ensure_for_personas``, which wrote the persona's own
name over an Edit-profile rename, so the agent read its old name after relaunch.
"""

from __future__ import annotations

from dataclasses import replace

from agent_runtime.models import AgentPersona
from agent_runtime.persona_assignments import PersonaInstanceStore


def _persona(display_name: str = "Base") -> AgentPersona:
    return AgentPersona(
        id="base",
        display_name=display_name,
        role="dev",
        model=None,
        provider=None,
        api_mode=None,
        hermes_profile="alpha",
    )


def test_ensure_keeps_an_operator_rename_of_the_canonical_instance(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    persona = _persona()
    minted = store.ensure_for_persona(persona)
    assert minted.display_name == "Base"

    store.update_profile(minted.id, display_name="Renamed")
    after = store.ensure_for_persona(persona)

    assert after.display_name == "Renamed"
    assert store.get(minted.id).display_name == "Renamed"


def test_ensure_still_names_an_unrenamed_instance_after_the_persona(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    minted = store.ensure_for_persona(_persona())
    assert minted.display_name == "Base"
    assert minted.display_name_custom is False

    renamed_persona = replace(_persona(), display_name="Base Two")
    assert store.ensure_for_persona(renamed_persona).display_name == "Base Two"


def test_a_renamed_instance_keeps_its_name_when_the_persona_is_renamed(isolate_agent_runtime_root):
    store = PersonaInstanceStore()
    minted = store.ensure_for_persona(_persona())
    store.update_profile(minted.id, display_name="Renamed")

    assert store.ensure_for_persona(_persona("Base Two")).display_name == "Renamed"
