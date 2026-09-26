"""The Launcher fixture must reflect real producers, including nullable states."""
import json
from pathlib import Path

import pytest

from agent_runtime.discussions.definitions import DefinitionError
from agent_runtime.discussions.rpc import execute
from tests.agent_runtime.discussion_wire_cases import wire_cases
from tests.agent_runtime.test_discussion_runtime import engine, begin

pytestmark = pytest.mark.timeout(90)


def test_producer_fixture(tmp_path):
    cases = wire_cases(tmp_path)
    live, ended = cases["live"], cases["ended"]
    assert len({m["instance_id"] for m in live["members"]}) == 2
    assert len({m["session_id"] for m in live["members"]}) == 2
    assert len({m["profile"] for m in live["members"]}) == 1
    assert ended["run"]["phase"] == "ended"
    assert ended["log"]["events"][:len(live["log"]["events"])] == live["log"]["events"]
    fixture = Path(__file__).parents[1] / "fixtures" / "discussion_wire_v1.json"
    expected = json.loads(Path(fixture).read_text(encoding="utf-8"))
    for key in ("capabilities", "preset", "table", "tables", "roster"):
        assert cases[key] == expected[key], key
    for key in ("live", "ended", "room"):
        assert cases[key].keys() == expected[key].keys()
        assert cases[key]["run"].keys() == expected[key]["run"].keys()
        assert cases[key]["members"][0].keys() == expected[key]["members"][0].keys()
        assert cases[key]["tasks"][0].keys() == expected[key]["tasks"][0].keys()
    assert cases["room"]["run"]["table_id"] is None
    assert cases["room"]["run"]["initial"] == expected["room"]["run"]["initial"]


def test_custom_keeps_configuration_and_obeys_revision_and_live_fences(engine):
    service, _ = engine
    begin(service)
    record = service.definitions.get("table", "ws", "table")
    with pytest.raises(DefinitionError, match="table_busy"):
        execute(service, "table.custom", {"workspace_id": "ws", "table_id": "table",
                                         "expect_revision": record.revision}, actor_id="operator")
    spec = record.spec.to_dict()
    service.definitions.save_table("ws", "custom", spec, expect_revision=0)
    service.definitions.save_preset("ws", "recipe", {"name": "Recipe", "preferred_capacity": "auto",
                                    "configuration": spec["configuration"]}, expect_revision=0)
    loaded = service.definitions.load_preset("ws", "custom", "recipe", expect_table_revision=1, expect_preset_revision=1)
    result = execute(service, "table.custom", {"workspace_id": "ws", "table_id": "custom",
                     "expect_revision": loaded.revision}, actor_id="operator")["record"]
    assert result["spec"] == loaded.spec.to_dict()
    assert result["preset_origin"] is None
    assert result["revision"] == loaded.revision + 1
    with pytest.raises(DefinitionError, match="stale_revision"):
        service.definitions.custom_table("ws", "custom", expect_revision=loaded.revision)
