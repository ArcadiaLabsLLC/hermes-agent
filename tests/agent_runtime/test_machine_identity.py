"""RT-MACHINE-ID / RT-SLOT-MACHINE-ID-IS-NAMESPACE-INSTALL: one machine id per PC, beside the namespaces.

Plan ``docs/agent-runtime-harness/planned/naming-and-address-map-2026-10-25.md`` ruling 3.
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import machine_identity as mi
from agent_runtime import workspace_slots as ws
from agent_runtime.workspace_slots_sync import _held_machine


def _env(tmp_path, namespace: str | None = None) -> dict[str, str]:
    env = {"HERMES_DEPENDENCY_ROOT": str(tmp_path / "base"), "HERMES_NAMESPACES_DIR": str(tmp_path / "ns")}
    if namespace:
        env["HERMES_NAMESPACE"] = namespace
    return env


def test_two_namespaces_and_the_base_root_read_one_machine_id(tmp_path):
    first = mi.ensure_machine_id(_env(tmp_path, "acct-0123456789abcdef"))
    assert first.startswith("mach_")
    assert mi.ensure_machine_id(_env(tmp_path, "stagec-smoke")) == first
    assert mi.read_machine_id(_env(tmp_path)) == first
    record = json.loads((tmp_path / "ns" / mi.MACHINE_ID_FILENAME).read_text(encoding="utf-8"))
    assert record["machine_id"] == first and record["schema"] == mi.MACHINE_ID_SCHEMA


def test_read_never_mints_and_an_unreadable_record_is_never_overwritten(tmp_path):
    env = _env(tmp_path)
    assert mi.read_machine_id(env) is None
    assert not (tmp_path / "ns").exists()
    (tmp_path / "ns").mkdir()
    (tmp_path / "ns" / mi.MACHINE_ID_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(mi.MachineIdentityUnavailable):
        mi.ensure_machine_id(env)
    assert (tmp_path / "ns" / mi.MACHINE_ID_FILENAME).read_text(encoding="utf-8") == "{not json"


def test_a_zero_byte_record_from_a_killed_mint_is_healed(tmp_path):
    (tmp_path / "ns").mkdir()
    (tmp_path / "ns" / mi.MACHINE_ID_FILENAME).write_bytes(b"")
    assert mi.ensure_machine_id(_env(tmp_path)).startswith("mach_")


def test_the_slot_key_is_the_machine_id_not_the_store_roots_install_id():
    me = ws.machine_id()
    assert me.startswith("mach_")
    assert me != ws.install_id()
    assert ws.known_machine_id() == me


def test_a_legacy_install_id_report_is_rekeyed_once_and_never_another_namespaces():
    legacy, other = "bbdb8120-legacy", "e2f5da6d-other"
    document = {"machines": {legacy: {"reported_at": "x", "slots": {"a": {}}}, other: {"reported_at": "y", "slots": {}}}}
    assert ws.rekey_legacy_report(document, "mach_1", legacy) is True
    assert set(document["machines"]) == {"mach_1", other}
    assert document["machines"]["mach_1"]["slots"] == {"a": {}}
    assert ws.rekey_legacy_report(document, "mach_1", legacy) is False  # idempotent


def test_a_peer_report_may_carry_its_namespace_and_a_bad_one_is_refused():
    entry = {"reported_at": "2026-10-25T00:00:00+00:00", "namespace": "acct-0123456789abcdef", "slots": {}}
    assert _held_machine(entry, 4e9, [], "m")["namespace"] == "acct-0123456789abcdef"
    with pytest.raises(Exception):
        _held_machine({**entry, "namespace": "../x"}, 4e9, [], "m")
