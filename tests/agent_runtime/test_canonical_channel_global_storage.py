"""RT-GLOBAL-SINGLETON-CANONICAL S1: a canonical operator channel carries no scene claim.

Plan ``docs/agent-runtime-harness/planned/canonical-channel-global-storage-2026-10-27.md``.
Every assertion on the DECODE reads a pointer the test wrote to disk (so a decode
that passes it through is visible), and every WRITE assertion reads the raw JSON
(so the decode cannot hide a stamped pointer). The placement row is the positive
control throughout: the same bytes, one variable changed (the id is not canonical).
"""

from __future__ import annotations

import json

import pytest

from agent_runtime import paths
from agent_runtime.events import EventLog
from agent_runtime.models import PersonaInstance
from agent_runtime.persona_assignments import PersonaInstanceStore, persona_instance_id_for
from agent_runtime.persona_assignments.identity import is_canonical_persona_channel
from agent_runtime.persona_instance_identity import reconcile_persona_instances
from agent_runtime.serde import to_jsonable
from agent_runtime.states import WorkerSessionState
from agent_runtime.workspace_scope import effective_workspace_id, exclude_global_canonicals

pytestmark = pytest.mark.usefixtures("isolate_agent_runtime_root", "persisted_persona_samples")

PERSONA = "neko_supervisor"
CANONICAL = persona_instance_id_for(PERSONA)
PLACEMENT = f"{CANONICAL}_agent_2"


def _seed(instance_id: str, *, workspace_id: str | None = "ws_a", realm_id: str | None = "realm_a") -> None:
    row = PersonaInstance(
        id=instance_id, persona_id=PERSONA, role=PERSONA, display_name="Neko", profile_id=None,
        runtime_root=str(paths.store_root()), state=WorkerSessionState.IDLE, mode="chat",
        workspace_id=workspace_id, realm_id=realm_id,
    )
    path = paths.persona_instance_path(instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_jsonable(row), indent=2, sort_keys=True), encoding="utf-8")


def _raw(instance_id: str) -> dict:
    return json.loads(paths.persona_instance_path(instance_id).read_text(encoding="utf-8"))


def test_a_stored_canonical_pointer_decodes_as_global_through_get_and_scan_all():
    """Kill-mutation: drop the canonical clause in ``_decode_instance`` → red;
    apply it in ``get`` only (``scan_all`` decoding raw) → the scan half reds."""
    _seed(CANONICAL)
    store = PersonaInstanceStore()
    assert _raw(CANONICAL)["workspace_id"] == "ws_a"  # the claim IS on disk
    for instance in (store.get(CANONICAL), next(i for i in store.scan_all().instances if i.id == CANONICAL)):
        assert instance.workspace_id is None and instance.realm_id is None
        assert effective_workspace_id(instance, active_workspace_id=None) is None
    advertised = exclude_global_canonicals(
        store.list_all(), scope_workspace_id="ws_a", is_canonical=is_canonical_persona_channel)
    assert CANONICAL not in {i.id for i in advertised}


def test_a_placement_pointer_still_decodes_through_get_and_scan_all():
    """Positive control. Kill-mutation: null the pointer for every row → red."""
    _seed(PLACEMENT)
    store = PersonaInstanceStore()
    for instance in (store.get(PLACEMENT), next(i for i in store.scan_all().instances if i.id == PLACEMENT)):
        assert instance.workspace_id == "ws_a" and instance.realm_id == "realm_a"
        assert effective_workspace_id(instance, active_workspace_id=None) == "ws_a"
    advertised = exclude_global_canonicals(
        store.list_all(), scope_workspace_id="ws_a", is_canonical=is_canonical_persona_channel)
    assert PLACEMENT in {i.id for i in advertised}


def test_the_bind_stamps_no_pointer_on_a_canonical_and_stamps_a_placement():
    """Kill-mutation: drop the canonical check in ``_apply_open_fields`` → the first
    half reds; skip stamping for every id → the second half reds."""
    store = PersonaInstanceStore()
    store.open_chat(persona_id=PERSONA, persona_instance_id=CANONICAL,
                    session_id="persona_chat_canon_1", workspace_id="ws_a", realm_id="realm_a")
    assert _raw(CANONICAL).get("workspace_id") is None
    assert _raw(CANONICAL).get("realm_id") is None

    _seed(PLACEMENT, workspace_id=None, realm_id=None)
    store.open_chat(persona_id=PERSONA, persona_instance_id=PLACEMENT,
                    session_id="persona_chat_place_1", workspace_id="ws_a", realm_id="realm_a")
    assert _raw(PLACEMENT)["workspace_id"] == "ws_a"
    assert _raw(PLACEMENT)["realm_id"] == "realm_a"


def test_the_clear_phase_clears_only_canonicals_once_and_dry_run_writes_nothing():
    """Kill-mutation: clear every row's pointer → the placement assertion reds."""
    _seed(CANONICAL)
    _seed(PLACEMENT)
    events = EventLog()
    store = PersonaInstanceStore(event_log=events)

    preview = store.clear_canonical_scope_pointers(apply=False)
    assert [item["persona_instance_id"] for item in preview] == [CANONICAL]
    assert _raw(CANONICAL)["workspace_id"] == "ws_a"

    applied = store.clear_canonical_scope_pointers(apply=True)
    assert [item["action"] for item in applied] == ["canonical_scope_cleared"]
    assert _raw(CANONICAL).get("workspace_id") is None
    assert _raw(PLACEMENT)["workspace_id"] == "ws_a"
    reconciled = [e for e in events.tail(1000) if e.type == "persona_instance.reconciled"]
    assert [e.payload["action"] for e in reconciled] == ["canonical_scope_cleared"]
    assert store.clear_canonical_scope_pointers(apply=True) == []


def test_the_reconciler_runs_the_clear_phase_and_its_dry_run_writes_nothing():
    """Kill-mutation: drop the phase-6 call in ``reconcile_persona_instances`` → red."""
    _seed(CANONICAL)
    dry = reconcile_persona_instances(apply=False)
    assert [item["persona_instance_id"] for item in dry["canonical_scope_cleared"]] == [CANONICAL]
    assert _raw(CANONICAL)["workspace_id"] == "ws_a"
    applied = reconcile_persona_instances(apply=True)
    assert applied["canonical_scope_cleared_count"] == 1
    assert _raw(CANONICAL).get("workspace_id") is None
    assert reconcile_persona_instances(apply=True)["canonical_scope_cleared_count"] == 0
