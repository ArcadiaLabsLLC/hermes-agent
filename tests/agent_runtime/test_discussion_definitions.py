"""Behavior contracts for table authoring; no claim of room/renderer integration."""
from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import pytest

from agent_runtime.discussions.definitions import (
    DefinitionError, PresetSpec, TableSpec, apply_preset, effective_capacity, plan_seats,
)


def table_value(count=2, capacity="auto"):
    return {
        "name": "Engineering", "style": "round", "capacity": capacity,
        "transform": {"position": [120, 240], "rotation_radians": 0, "scale": 1},
        "configuration": {
            "participants": [{"install_id": "install_A", "instance_id": f"personainst_{i}"} for i in range(count)],
            "settings": {"rounds": 3, "moderator": None, "user_participates": True, "allow_invitations": False},
            "seat_preferences": [],
        },
    }


def test_every_requested_capacity_has_that_many_distinct_logical_seats():
    # User-required capacities, not a copy of the implementation's constant.
    for size in (2, 4, 6, 8, 10, 12):
        table = TableSpec.parse(table_value(size, size))
        plan = plan_seats(table)
        assert len(plan.assignments) == size
        assert {p.participant for p in plan.assignments} == set(table.configuration.participants)
        assert {p.seat for p in plan.assignments} == set(range(size))
        assert not plan.remapped


@pytest.mark.parametrize("count,expected", [(0,2),(1,2),(2,2),(3,4),(4,4),(5,6),(6,6),(7,8),(8,8),(9,10),(10,10),(11,12),(12,12)])
def test_auto_selects_smallest_sufficient_table(count, expected):
    assert effective_capacity("auto", count) == expected


@pytest.mark.parametrize("value", [True, False, 6.0, "6", "AUTO", None, 0, 3, 13, {}, []])
def test_capacity_types_are_not_coerced(value):
    with pytest.raises(DefinitionError) as caught:
        TableSpec.parse(table_value(2, value))
    assert caught.value.reason == "invalid_capacity"


def test_overflow_and_oversized_rosters_refuse_instead_of_truncating():
    for value, reason in [(table_value(5, 4), "capacity_exceeded"), (table_value(13), "invalid_participants")]:
        before = copy.deepcopy(value)
        with pytest.raises(DefinitionError) as caught:
            TableSpec.parse(value)
        assert caught.value.reason == reason
        assert value == before
    assert len(TableSpec.parse(table_value(12)).configuration.participants) == 12


def test_seat_preferences_reserve_valid_slots_and_report_geometry_remaps():
    value = table_value(3, 4)
    people = value["configuration"]["participants"]
    value["configuration"]["seat_preferences"] = [
        {"participant": people[0], "seat": 11}, {"participant": people[1], "seat": 0},
    ]
    table = TableSpec.parse(value)
    first = plan_seats(table)
    assert [p.seat for p in first.assignments] == [1, 0, 2]
    assert first.remapped == (table.configuration.participants[0],)
    assert plan_seats(table) == first
    value["capacity"] = 12
    expanded = plan_seats(TableSpec.parse(value))
    assert [p.seat for p in expanded.assignments] == [11, 0, 1]
    assert not expanded.remapped


def test_participants_are_explicit_instance_addresses_not_profiles():
    value = table_value()
    value["configuration"]["participants"][1]["instance_id"] = "personainst_second"
    assert len(TableSpec.parse(value).configuration.participants) == 2
    # A profile name cannot accidentally substitute for an instance.
    value["configuration"]["participants"][0]["instance_id"] = "researcher"
    with pytest.raises(DefinitionError, match="invalid_instance_id"):
        TableSpec.parse(value)
    value = table_value()
    value["configuration"]["participants"][0]["profile"] = "researcher"
    with pytest.raises(DefinitionError, match="invalid_fields"):
        TableSpec.parse(value)


def test_duplicate_exact_address_refuses_but_install_is_part_of_the_address():
    value = table_value()
    people = value["configuration"]["participants"]
    people[1] = copy.deepcopy(people[0])
    with pytest.raises(DefinitionError, match="duplicate_participant"):
        TableSpec.parse(value)
    people[1]["install_id"] = "install_B"
    assert len(TableSpec.parse(value).configuration.participants) == 2
    # These are configured addresses, not proof that a native/local room admits them.


@pytest.mark.parametrize("coordinate", [float("nan"),float("inf"),float("-inf"),True,"2",10**500,1_000_001])
def test_nonfinite_unbounded_and_non_numeric_coordinates_refuse(coordinate):
    value = table_value()
    value["transform"]["position"][0] = coordinate
    with pytest.raises(DefinitionError, match="invalid_number"):
        TableSpec.parse(value)


@pytest.mark.parametrize("field,value", [("scale",0),("scale",4.1),("rotation_radians",float("nan")),("position",[1]),("position",[1,2,3])])
def test_transform_shape_is_explicit(field, value):
    raw = table_value()
    raw["transform"][field] = value
    with pytest.raises(DefinitionError):
        TableSpec.parse(raw)


def test_visual_scale_does_not_change_agent_capacity_or_count_operator():
    value = table_value(4, 4)
    value["transform"]["scale"] = 4
    assert TableSpec.parse(value).seat_count == 4
    assert len(plan_seats(TableSpec.parse(value)).assignments) == 4


def test_preset_never_contains_topic_or_placement_and_load_never_resizes():
    table = TableSpec.parse(table_value(2, 4))
    value = {"name": "Team", "preferred_capacity": 12, "configuration": table.configuration.to_dict()}
    preset = PresetSpec.parse(value)
    loaded = apply_preset(table, preset)
    assert loaded.transform == table.transform
    assert loaded.style == table.style and loaded.capacity == 4 and loaded.name == table.name
    for key in ("topic", "transform", "preset_origin"):
        with pytest.raises(DefinitionError, match="invalid_fields"):
            PresetSpec.parse({**value, key: "not stored here"})
    oversized = PresetSpec.parse({**value, "configuration": table_value(5)["configuration"]})
    with pytest.raises(DefinitionError, match="capacity_exceeded"):
        apply_preset(table, oversized)


def test_values_and_serialization_do_not_alias_mutable_inputs():
    raw = table_value()
    table = TableSpec.parse(raw)
    raw["configuration"]["participants"][0]["instance_id"] = "personainst_replaced"
    exported = table.to_dict()
    exported["configuration"]["participants"].clear()
    assert len(table.configuration.participants) == 2
    assert table.configuration.participants[0].instance_id == "personainst_0"
    with pytest.raises(FrozenInstanceError):
        table.name = "mutated"


def test_settings_require_real_booleans_and_moderator_membership():
    raw = table_value()
    raw["configuration"]["settings"]["allow_invitations"] = "false"
    with pytest.raises(DefinitionError, match="invalid_boolean"):
        TableSpec.parse(raw)
    raw = table_value()
    raw["configuration"]["settings"]["moderator"] = {"install_id":"install_A", "instance_id":"personainst_absent"}
    with pytest.raises(DefinitionError, match="moderator_not_member"):
        TableSpec.parse(raw)
    raw["configuration"]["settings"]["moderator"] = raw["configuration"]["participants"][1]
    assert TableSpec.parse(raw).configuration.settings.moderator.instance_id == "personainst_1"


@pytest.mark.parametrize("case", ["duplicate_seat", "duplicate_owner", "foreign_owner", "bool_index"])
def test_invalid_seat_preferences_refuse(case):
    raw = table_value()
    a, b = raw["configuration"]["participants"]
    shapes = {
        "duplicate_seat": [{"participant":a,"seat":0},{"participant":b,"seat":0}],
        "duplicate_owner": [{"participant":a,"seat":0},{"participant":a,"seat":1}],
        "foreign_owner": [{"participant": {**a,"instance_id":"personainst_unknown"},"seat":0}],
        "bool_index": [{"participant":a,"seat":True}],
    }
    raw["configuration"]["seat_preferences"] = shapes[case]
    with pytest.raises(DefinitionError):
        TableSpec.parse(raw)


@pytest.mark.parametrize("name", ["", " ", "unsafe\x00name", "line\nname", "\ud800", "\u202eevil", "x"*257, "🦕"*65])
def test_invalid_names_refuse_without_reflecting_input(name):
    raw = table_value()
    raw["name"] = name
    with pytest.raises(DefinitionError) as caught:
        TableSpec.parse(raw)
    assert str(caught.value) == "invalid_name: name"


def test_unknown_and_non_string_keys_refuse_without_echoing_credentials():
    secret = "api_key=do-not-reflect"
    for unknown in [secret, 1]:
        raw = table_value()
        raw[unknown] = "private"
        with pytest.raises(DefinitionError) as caught:
            TableSpec.parse(raw)
        assert secret not in str(caught.value) and "private" not in str(caught.value)
