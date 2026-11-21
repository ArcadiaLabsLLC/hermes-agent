"""An agent instance added to a workspace stands on that workspace's office level, whichever door added it.

Eternia row ``MC-AGENTS-A-LEAD-ADDED-LAST-NIGHT-ARE-NOT-ON-THE-OFFICE-LEVEL`` (seen 2026-11-20 on the
owner's install): Neko ran ``hermes harness persona instance create --persona dev --add-instance
--placement-id dev_agent_<hex> --workspace-id ws_testv4_afb811 ...`` from its terminal; the instance
record held the workspace and no office actor was written, so Launcher Dev Agent 2 and 3 stood on no
level. ``runtime.agent.place`` wrote the actor; the argv doors did not. Every witness here is the office
store, read beside the instance store, through the real argparse tree.

Since RT-THE-OLD-CREATE-NO-LONGER-PLACES-OR-COPIES-AN-AGENT (review w1118a.74) the argv door IS the
place: ``--add-instance`` runs ``runtime.agent.place``'s sequence, which writes the seat with the instance
and refuses an unknown workspace before either; ``open-chat --add-instance`` no longer places. The
repair (``seat-unseated``) still seats what the old doors left.

MUTATIONS (each seen red, then restored):
- send ``--add-instance`` back to ``PersonaInstanceStore().add_instance`` -> the create-door test reds
  (no actor, no ``actor_key``);
- drop the ``_stands_in`` check in ``seat_added_instance`` -> the re-seat test reds (a second write).
"""

from __future__ import annotations

import json

from tests.agent_runtime.office_seed import seed_workspace_record
from tests.hermes_cli.test_placement_id_discriminability import (  # the module's fixtures
    _dispatch,
    hermetic_runtime_root,  # noqa: F401 — autouse, re-exported for this file
    qa_persona,  # noqa: F401 — the fixture, re-exported for this file
)

WORKSPACE = "ws_seat_test"


def _seed() -> None:
    from agent_runtime.office_store import OfficeStore

    seed_workspace_record(WORKSPACE)
    OfficeStore().ensure_surface(WORKSPACE, created_by="seed")


def _standing(instance_id: str) -> list:
    from agent_runtime.office_store import OfficeStore

    return [a for a in OfficeStore().scan_actors(WORKSPACE).actors if a.persona_instance_id == instance_id]


def _run(capsys, argv: list[str]) -> dict:
    code = _dispatch(argv)
    data = json.loads(capsys.readouterr().out)
    assert code == 0, data
    return data


def _create(capsys, *extra: str) -> dict:
    return _run(capsys, [
        "harness", "persona", "instance", "create", "--persona", "qa", "--title", "New operator chat",
        "--display-name", "QA Agent", "--add-instance", "--workspace-id", WORKSPACE, "--json", *extra,
    ])


def test_instance_create_add_instance_seats_it_on_its_workspace_level(qa_persona, capsys):
    _seed()
    data = _create(capsys, "--placement-id", "qa_agent_5e1f0a2b")

    (actor,) = _standing(data["persona_instance_id"])
    assert actor.persona_id == "qa"
    assert [item.display_name for item in actor.items if item.kind == "agent"] == [data["display_name"]]
    assert (data["actor_key"], data["workspace_id"]) == (actor.actor_key, WORKSPACE)


def test_a_reseat_of_a_standing_instance_writes_nothing(qa_persona, capsys):
    from agent_runtime.agent_create.seat import seat_added_instance
    from agent_runtime.office_store import OfficeStore
    from agent_runtime.persona_assignments import PersonaInstanceStore

    _seed()
    data = _create(capsys, "--placement-id", "qa_agent_5e1f0a2b")
    (actor,) = _standing(data["persona_instance_id"])

    again = seat_added_instance(PersonaInstanceStore().get(data["persona_instance_id"]))

    assert again.reason == "already_seated"
    assert OfficeStore().get_actor(WORKSPACE, actor.actor_key).revision == actor.revision


def test_an_add_with_no_known_workspace_is_refused_and_writes_nothing(qa_persona, capsys):
    from agent_runtime.persona_assignments import PersonaInstanceStore

    before = {row.id for row in PersonaInstanceStore().list_all()}
    code = _dispatch([  # WORKSPACE is never seeded here
        "harness", "persona", "instance", "create", "--persona", "qa", "--title", "New operator chat",
        "--display-name", "QA Agent", "--add-instance", "--workspace-id", WORKSPACE, "--json",
    ])
    data = json.loads(capsys.readouterr().out)

    assert (code, data["ok"], data["error_kind"]) == (2, False, "workspace_not_found")
    assert {row.id for row in PersonaInstanceStore().list_all()} == before


def test_seat_unseated_lists_on_a_dry_run_then_seats_what_the_old_door_left(qa_persona, capsys):
    from agent_runtime.persona_assignments import PersonaInstanceStore

    _seed()
    # What the argv door wrote before this fix: the record, no actor.
    old = PersonaInstanceStore().add_instance(
        persona_id="qa", placement_id="qa_agent_01d5ea7e", display_name="QA Agent", workspace_id=WORKSPACE,
    )
    assert _standing(old.id) == []

    dry = _run(capsys, ["harness", "persona", "seat-unseated", "--dry-run", "--json"])
    dry.pop("resolution")  # the store root it read (59f30ab791), not a seat
    assert dry == {"dry_run": True, "seats": [
        {"instance_id": old.id, "workspace_id": WORKSPACE, "seated": False, "reason": "would_seat"},
    ]}
    assert _standing(old.id) == []

    applied = _run(capsys, ["harness", "persona", "seat-unseated", "--json"])
    assert [seat["reason"] for seat in applied["seats"]] == ["seated"]
    assert len(_standing(old.id)) == 1
    assert _run(capsys, ["harness", "persona", "seat-unseated", "--dry-run", "--json"])["seats"] == []
