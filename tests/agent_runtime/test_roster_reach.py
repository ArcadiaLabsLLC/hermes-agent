"""RT-RELAY-TO-ROSTER-AGENT-WITHOUT-PROFILE: the roster offers only agents a message can reach.

Seen live 2026-11-12 (w1112b-cttfu): a ``role: profile`` instance whose Hermes profile was gone was listed in the
Agent Browser and Base's relay to it failed "Hermes profile '…' does not exist". RULED: hide it, with a receipt.
"""

from __future__ import annotations

import logging

import pytest

from agent_runtime.persona_assignments import PersonaInstanceStore
from agent_runtime.snapshot import build_snapshot

pytestmark = pytest.mark.usefixtures("persisted_persona_samples")


def _profile_instance(placement: str, profile: str):
    store = PersonaInstanceStore()
    instance = store.add_instance(persona_id="dev", placement_id=placement, display_name=placement)
    instance.role, instance.profile_id = "profile", profile
    store.update(instance)
    return store.get(instance.id)


def test_an_agent_whose_profile_is_gone_is_not_offered_and_one_whose_profile_exists_is(
    isolate_agent_runtime_root, caplog
):
    """Mutation: drop ``offered`` around ``ensure_for_personas`` in the snapshot -> the orphan is listed, red;
    drop it around the HUD's ``identity_roster`` -> ``test_the_hud_roster...`` red."""
    from agent_runtime.roster_reach import offered

    caplog.set_level(logging.INFO, logger="agent_runtime.roster_reach")
    orphan = _profile_instance("orphan_agent_1", "base_agent_gone")
    live = _profile_instance("live_agent_1", "default")
    listed = build_snapshot()["persona_instances"]
    assert orphan.id not in listed and live.id in listed
    assert any("roster_instance_hidden" in r.getMessage() and orphan.id in r.getMessage() for r in caplog.records)
    assert [i.id for i in offered(PersonaInstanceStore().list_all())].count(orphan.id) == 0
    assert PersonaInstanceStore().get(orphan.id).id == orphan.id  # the record (and its chats) are kept


def test_the_hud_roster_never_offers_an_agent_whose_profile_is_gone(isolate_agent_runtime_root, monkeypatch):
    from agent_runtime.runtime_hud import ambient

    orphan = _profile_instance("orphan_agent_2", "base_agent_gone")
    seen = {}

    def capture(instance, **kwargs):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(ambient, "resolve_situational_hud", capture)
    me = PersonaInstanceStore().list_all()[0]
    ambient.situational_hud_for_instance(me)
    assert orphan.id not in {i.id for i in seen["identity_roster"]}
    assert orphan.id not in {i.id for i in seen["roster"]}
