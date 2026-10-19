"""The vendored Launcher catalog parses as the runtime parses the wire (R10, positive).

``tests/fixtures/launcher_app_functions_catalog.json`` is the Launcher's export, copied
in by ``scripts/vendor_launcher_catalog.py``. Every entry must build an
``AppFunctionEntry`` through the runtime's own ``parse`` (the export's ``id`` is the
wire's ``method``), and every ``name`` must equal ``id.replace(".", "_")`` — the
Launcher's ``appFunctionToolName`` rule, pinned so a change to the rule reds at refresh
instead of on a live turn.

Killing mutation (2026-10-19): set one fixture ``name`` to ``launcher-generated-create``
-> ``test_every_entry_parses_and_names_follow_the_rule`` red naming the entry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_runtime.launcher_app_functions import METHOD_PREFIX, AppFunctionEntry
from scripts.vendor_launcher_catalog import ENTRY_FIELDS, build_fixture, entry_delta, normalize_entries

pytestmark = pytest.mark.gate

CATALOG = Path(__file__).resolve().parents[1] / "fixtures" / "launcher_app_functions_catalog.json"


def _fixture() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _wire(entry: dict) -> dict:
    """The fixture entry as the Launcher's agent projection sends it."""

    return {"name": entry["name"], "method": entry["id"], "read_only": entry["read_only"],
            "always_loaded": entry["always_loaded"], "reach": entry["reach"]}


def test_the_fixture_is_stamped_and_shaped():
    fixture = _fixture()
    assert len(fixture["source_commit"]) == 40, fixture["source_commit"]
    assert fixture["exported_at"]
    assert len(fixture["entries"]) >= 5
    assert normalize_entries(fixture) == fixture["entries"], "the fixture is not in vendored form"


def test_every_entry_parses_and_names_follow_the_rule():
    bad = []
    for entry in _fixture()["entries"]:
        parsed = AppFunctionEntry.parse(_wire(entry))
        if parsed is None:
            bad.append(f"{entry['id']}: AppFunctionEntry.parse refused it")
            continue
        if not entry["id"].startswith(METHOD_PREFIX):
            bad.append(f"{entry['id']}: not a {METHOD_PREFIX} id")
        if parsed.name != entry["id"].replace(".", "_"):
            bad.append(f"{entry['id']}: name {parsed.name!r} is not the id with dots as underscores")
        if parsed.read_only is not entry["read_only"] or parsed.reach != entry["reach"]:
            bad.append(f"{entry['id']}: read_only/reach did not survive parse")
    assert not bad, "the vendored Launcher catalog drifted from the wire hermes parses:\n  " + "\n  ".join(bad)


def test_the_vendor_script_normalizes_and_reports_the_delta():
    raw = {"exported_at": "2026-10-19", "entries": [
        {"id": "launcher.b.x", "name": "launcher_b_x", "read_only": True, "always_loaded": False,
         "reach": "localOnly", "guidance_sha256": "", "permission": "allowed"},
        {"id": "launcher.a.y", "name": "launcher_a_y", "read_only": False, "always_loaded": True,
         "reach": "pairedDevice", "guidance_sha256": "ab"},
    ]}
    fixture = build_fixture(raw, "0" * 40)
    assert [e["id"] for e in fixture["entries"]] == ["launcher.a.y", "launcher.b.x"]
    assert all(list(e) == list(ENTRY_FIELDS) for e in fixture["entries"])
    changed = [dict(fixture["entries"][0], reach="localOnly")]
    assert entry_delta(fixture["entries"], changed) == ["- launcher.b.x", "~ launcher.a.y (reach)"]
    with pytest.raises(ValueError):
        normalize_entries({"entries": [{"id": "launcher.a.y"}]})
