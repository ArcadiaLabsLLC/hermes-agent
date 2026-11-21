"""Pure resolution table for the workspace-scoping authority.

``agent_runtime.workspace_scope`` decides which persona placements are
addressable from a given workspace. The contract: a ``None`` workspace pointer
is runtime-global (visible everywhere), a non-None pointer belongs to exactly
one workspace, and a ``None`` scope disables filtering. No I/O, so the table is
asserted directly against value objects.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_runtime import workspace_scope


def _inst(workspace_id="__unset__", **overrides):
    base = {"id": "personainst_x", "persona_id": "dev"}
    base.update(overrides)
    if workspace_id != "__unset__":
        base["workspace_id"] = workspace_id
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# instance_in_scope: the (candidate_ws, scope_ws) -> in/out table              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "candidate_ws, scope_ws, expected",
    [
        # Runtime-global candidate is addressable from every workspace.
        (None, "ws_a", True),
        # Same workspace: in scope.
        ("ws_a", "ws_a", True),
        # Different workspace: out of scope.
        ("ws_b", "ws_a", False),
        # No active workspace at all: everything is in scope (no hiding).
        ("ws_a", None, True),
        (None, None, True),
        # A blank/whitespace pointer collapses to runtime-global.
        ("", "ws_a", True),
        ("   ", "ws_a", True),
        # Surrounding whitespace does not defeat an otherwise-matching id.
        (" ws_a ", "ws_a", True),
    ],
)
def test_instance_in_scope_table(candidate_ws, scope_ws, expected):
    assert workspace_scope.instance_in_scope(candidate_ws, scope_ws) is expected


# --------------------------------------------------------------------------- #
# effective_workspace_id: own pointer wins, else active fallback              #
# --------------------------------------------------------------------------- #


def test_effective_workspace_id_prefers_own_pointer():
    inst = _inst(workspace_id="ws_b")
    assert workspace_scope.effective_workspace_id(inst, active_workspace_id="ws_a") == "ws_b"


def test_effective_workspace_id_falls_back_to_active_when_global():
    inst = _inst(workspace_id=None)
    assert workspace_scope.effective_workspace_id(inst, active_workspace_id="ws_a") == "ws_a"


def test_effective_workspace_id_none_when_neither_set():
    inst = _inst(workspace_id=None)
    assert workspace_scope.effective_workspace_id(inst, active_workspace_id=None) is None


def test_effective_workspace_id_tolerates_missing_attribute():
    # A value object without a workspace_id attribute is treated as global.
    inst = _inst()  # no workspace_id key at all
    assert workspace_scope.effective_workspace_id(inst, active_workspace_id="ws_a") == "ws_a"


def test_effective_workspace_id_blank_pointer_falls_back():
    inst = _inst(workspace_id="   ")
    assert workspace_scope.effective_workspace_id(inst, active_workspace_id="ws_a") == "ws_a"


def test_exact_scoped_instance_ids_excludes_globals_and_other_workspaces():
    instances = [
        _inst(workspace_id="ws_a", id="personainst_a_two"),
        _inst(workspace_id=None, id="personainst_global"),
        _inst(workspace_id="ws_b", id="personainst_b"),
        _inst(workspace_id=" ws_a ", id="personainst_a_one"),
    ]

    assert workspace_scope.exact_scoped_instance_ids(
        instances,
        workspace_id="ws_a",
    ) == ["personainst_a_one", "personainst_a_two"]


# --------------------------------------------------------------------------- #
# scope_roster: filter to scope, preserve input order, never mutate           #
# --------------------------------------------------------------------------- #


def test_scope_roster_keeps_scope_and_global_in_input_order():
    a = _inst(workspace_id="ws_a", id="a")
    b = _inst(workspace_id="ws_b", id="b")
    c = _inst(workspace_id=None, id="c")
    d = _inst(workspace_id="ws_a", id="d")
    scoped = workspace_scope.scope_roster([a, b, c, d], scope_workspace_id="ws_a")
    # ws_b row dropped; ws_a + global rows kept in original order.
    assert [i.id for i in scoped] == ["a", "c", "d"]


def test_scope_roster_none_scope_keeps_everything():
    a = _inst(workspace_id="ws_a", id="a")
    b = _inst(workspace_id="ws_b", id="b")
    scoped = workspace_scope.scope_roster([a, b], scope_workspace_id=None)
    assert [i.id for i in scoped] == ["a", "b"]


def test_scope_roster_empty_input_is_empty():
    assert workspace_scope.scope_roster(None, scope_workspace_id="ws_a") == []
    assert workspace_scope.scope_roster([], scope_workspace_id="ws_a") == []


def test_scope_roster_all_out_of_scope_yields_empty():
    b = _inst(workspace_id="ws_b", id="b")
    assert workspace_scope.scope_roster([b], scope_workspace_id="ws_a") == []


# --------------------------------------------------------------------------- #
# addressable_roster: scope, then drop held hidden copies                       #
# (RT-HERMES-STOPS-MAKING-A-HIDDEN-COPY-OF-EVERY-AGENT retired the canonical    #
# shadow and exclusion rules with the predicate they took)                      #
# --------------------------------------------------------------------------- #


def _row(id, persona_id, *, workspace_id=None, stamp=None):
    return SimpleNamespace(id=id, persona_id=persona_id, workspace_id=workspace_id, adopted_from_global=stamp)


def test_addressable_roster_scopes_and_drops_held_copies_in_input_order():
    held = _row("personainst_qa", "qa", stamp="2026-11-21")
    adopted = _row("personainst_dev", "dev", workspace_id="ws_a", stamp="2026-11-21")
    elsewhere = _row("personainst_dev_agent_2", "dev", workspace_id="ws_b")
    unseated = _row("personainst_dev_k1", "dev")
    rows = [held, adopted, elsewhere, unseated]
    assert [i.id for i in workspace_scope.addressable_roster(rows, scope_workspace_id="ws_a")] == [
        "personainst_dev", "personainst_dev_k1"]
    assert [i.id for i in workspace_scope.addressable_roster(rows, scope_workspace_id=None)] == [
        "personainst_dev", "personainst_dev_agent_2", "personainst_dev_k1"]
    assert workspace_scope.addressable_roster(None, scope_workspace_id="ws_a") == []


# --------------------------------------------------------------------------- #
# lane_workspace: which workspace a lane's turn is in, and its name            #
# --------------------------------------------------------------------------- #

_WORKSPACES = (
    SimpleNamespace(id="ws_a", name="Alpha"),
    SimpleNamespace(id="ws_b", name="Beta"),
)


def test_a_placed_lane_is_in_its_own_workspace_whatever_is_active():
    lane = workspace_scope.lane_workspace(
        _inst("ws_a"), active_workspace_id="ws_b", workspaces=_WORKSPACES
    )

    assert lane == workspace_scope.LaneWorkspace(id="ws_a", name="Alpha")


def test_a_runtime_global_lane_is_in_the_active_workspace():
    lane = workspace_scope.lane_workspace(
        _inst(None), active_workspace_id="ws_b", workspaces=_WORKSPACES
    )

    assert lane == workspace_scope.LaneWorkspace(id="ws_b", name="Beta")


def test_a_pointer_to_an_unlisted_workspace_keeps_its_id_and_has_no_name():
    lane = workspace_scope.lane_workspace(
        _inst("ws_gone"), active_workspace_id="ws_b", workspaces=_WORKSPACES
    )

    assert lane == workspace_scope.LaneWorkspace(id="ws_gone", name=None)


def test_no_pointer_and_nothing_active_is_no_workspace_at_all():
    lane = workspace_scope.lane_workspace(
        _inst(None), active_workspace_id=None, workspaces=_WORKSPACES
    )

    assert lane == workspace_scope.LaneWorkspace()
    assert lane.id is None and lane.name is None
