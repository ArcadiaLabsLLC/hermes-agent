"""The update receipt reads both published roster shapes as one roster (RT-UPDATE-FLEET-ROSTER-DROPPED).

Runtime status publishes ``served_profiles`` as bare names; the unified runtime's ``identify``
publishes ``{"profile_id", "home"}`` objects. A live multiplexer answering in either shape must
vouch for the same profiles, and an object naming a home this host does not own must vouch for none.
"""

import pytest

from hermes_cli import update_cmd_fleet, update_fleet_roster, update_receipt


@pytest.fixture
def homes(tmp_path, monkeypatch):
    default = tmp_path / "root"
    coder = default / "profiles" / "coder"
    coder.mkdir(parents=True)
    monkeypatch.setattr(update_receipt, "_profile_homes", lambda: [("default", default), ("coder", coder)])
    return default, coder


def _row(served):
    return update_receipt._fleet_row("default", 7, "new", "1", "new", served_profiles=served)


def test_identity_objects_and_bare_names_give_the_same_roster(homes):
    default, coder = homes
    objects = _row([{"profile_id": str(home), "home": str(home)} for home in (default, coder)])
    names = _row(["default", "coder"])

    assert objects["served_profiles"] == names["served_profiles"] == ["default", "coder"]
    assert update_cmd_fleet._fleet_covered_gateways([objects]) == {("gateway", "default"), ("gateway", "coder")}


@pytest.mark.parametrize("bad", [
    {"profile_id": "/elsewhere/profiles/coder", "home": "/elsewhere/profiles/coder"},
    {"profile_id": "", "home": ""},
    {},
    "",
    3,
])
def test_one_unknown_or_invalid_entry_drops_the_whole_roster(homes, bad):
    default, _ = homes
    roster = [{"profile_id": str(default), "home": str(default)}, bad]
    row = _row(roster)

    assert update_fleet_roster.roster_names(roster) is None
    assert "served_profiles" not in row
    assert update_cmd_fleet._fleet_covered_gateways([row]) == {("gateway", "default")}


def test_an_object_whose_two_fields_name_different_profiles_is_refused(homes):
    default, coder = homes
    assert "served_profiles" not in _row([{"profile_id": str(default), "home": str(coder)}])
