"""A seat of Neko or Base given its own skills, character or name is a change to the agent.

Row ``RT-SHIPPED-AGENT-SEAT-EDIT-COUNTS-AS-A-CHANGE`` (review w1118a.39 D9, owner
answers 2 and 6): ``resolve.py`` is the one owner of "changed" — a seat's
``skill_overrides``, own character and operator rename count beside the persona's
definition, reported per seat through ``directory_fields``; the update that resets
a changed shipped agent clears those three seat fields and leaves the seat's model,
provider and reasoning effort alone. Read through ``runtime.agent.directory``,
``runtime.persona.instance.detail`` and the directory read's own sync.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from agent_runtime import paths, serve_rpc
from agent_runtime.bundled_agents import catalog
from agent_runtime.character_assignment import CharacterAssignmentChange
from agent_runtime.config import load_agent_runtime_config
from agent_runtime.fresh_install_seed import seed_fresh_install_persona
from agent_runtime.gateway_identity import ensure_install_identity
from agent_runtime.persona_assignments import PersonaInstanceStore

NEKO = "neko_supervisor"


def _rpc(method: str, **params) -> dict:
    reply = serve_rpc.handle_request({"jsonrpc": "2.0", "id": "d", "method": method, "params": params})
    assert "result" in reply, reply
    return reply["result"]


def _neko_row() -> dict:
    ensure_install_identity(paths.store_root())
    rows = _rpc("runtime.agent.directory")["agents"]
    return next(row for row in rows if row["persona_id"] == NEKO and row["canonical"])


def _ship_update(monkeypatch, tmp_path) -> None:
    """Stand in for a newer build of Neko: another SOUL, so a new version, same definition."""

    souls = tmp_path / "next-build-souls"
    souls.mkdir()
    (souls / "neko.md").write_text("Neko from the next build.", encoding="utf-8")
    monkeypatch.setattr(catalog, "_SOULS", souls)
    monkeypatch.setitem(catalog._BY_ID, NEKO, replace(catalog.shipped_agent(NEKO)))


@pytest.fixture
def seat():
    seed_fresh_install_persona(load_agent_runtime_config())
    return _neko_row()["instance_id"]


def test_a_seat_with_its_own_skills_reads_changed_and_its_model_alone_does_not(seat):
    store = PersonaInstanceStore()
    store.patch_fields(seat, model="my-model", provider="my-provider", reasoning_effort="high")
    assert _neko_row()["locally_changed"] is False

    store.patch_fields(seat, skill_overrides=["my-own-skill"])

    assert _neko_row()["locally_changed"] is True
    assert _rpc("runtime.persona.instance.detail", instance_id=seat)["locally_changed"] is True


def test_a_seat_given_the_shipped_skills_back_is_not_a_change(seat):
    shipped = list(catalog.shipped_agent(NEKO).definition["skills"])
    PersonaInstanceStore().patch_fields(seat, skill_overrides=list(reversed(shipped)))

    assert _neko_row()["locally_changed"] is False


def test_a_seat_renamed_or_given_its_own_character_reads_changed(seat):
    store = PersonaInstanceStore()
    store.patch_fields(seat, display_name="My Neko", display_name_custom=True)
    assert _neko_row()["locally_changed"] is True

    store.patch_fields(seat, display_name="Neko Mission Lead", display_name_custom=False)
    assert _neko_row()["locally_changed"] is False

    store.set_character_assignment(seat, CharacterAssignmentChange(0, "unassigned", None, "seat-own-character"))
    assert _neko_row()["locally_changed"] is True


def test_the_update_clears_the_seats_definition_and_keeps_its_model(seat, monkeypatch, tmp_path):
    store = PersonaInstanceStore()
    store.patch_fields(
        seat, skill_overrides=["my-own-skill"], display_name="My Neko", display_name_custom=True,
        model="my-model", provider="my-provider", reasoning_effort="high",
    )
    store.set_character_assignment(seat, CharacterAssignmentChange(0, "unassigned", None, "seat-own-character"))
    assert _neko_row()["locally_changed"] is True

    _ship_update(monkeypatch, tmp_path)
    row = _neko_row()  # the directory read runs the update's sync

    after = PersonaInstanceStore().get(seat)
    assert row["locally_changed"] is False
    assert (after.skill_overrides, after.display_name, after.display_name_custom) == (None, "Neko Mission Lead", False)
    assert after.character_assignment["mode"] == "inherit"
    assert (after.model, after.provider, after.reasoning_effort) == ("my-model", "my-provider", "high")
