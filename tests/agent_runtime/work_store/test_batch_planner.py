"""The batching policy (dispatcher plan §3.1): thick lanes by domain, sized by row effort, sequenced on a
shared file, a persona per lane by assignee or roster role match, one landing.

Killing mutation (plan §6 B2): ``planner.plan`` groups by row instead of ``Domain`` (key
``row.ref`` in place of ``domain_of(row)``) → ``test_one_lane_per_domain`` red (6 lanes, not 2).

RT-BATCH-GATE-PER-SLOT-COMMAND (p10-work §3 G1): ``plan`` gives the landing lane every slot's gate
(``Lane.gates``) and the wire round-trips it. Killing mutation, red recorded in its commit body: ``Lane.wire``
drops ``gates`` → ``test_the_landing_lane_carries_one_gate_per_slot_and_round_trips_the_wire`` red.
"""

from __future__ import annotations

import pytest

from agent_runtime.batch.gate import slot_gate
from agent_runtime.batch.planner import (
    LANDING_GATE, LANDING_ID, Budget, Lane, LaneKind, Member, Plan, plan, row_effort, touched_files,
)
from agent_runtime.work_store.reasons import Reason, WorkRefused
from agent_runtime.work_store.source import Domain

from batch_support import NOTE, WS, qrow

ROSTER = [Member("inst-cody", "cody", "engineer"), Member("inst-quinn", "quinn", "qa")]


def test_one_lane_per_domain():
    rows = [qrow(f"RT-F{i}", files=[f"agent_runtime/f{i}.py"]) for i in range(3)]
    rows += [qrow(f"RT-S{i}", heading="Seams", files=[f"tools/s{i}.py"]) for i in range(3)]
    made = plan(rows, workspace_id=WS)
    assert [lane.domain for lane in made.lanes] == [Domain("hermes", NOTE, "Fork-owned"), Domain("hermes", NOTE, "Seams")]
    assert [[r.id for r in lane.rows] for lane in made.lanes] == [["RT-F0", "RT-F1", "RT-F2"], ["RT-S0", "RT-S1", "RT-S2"]]
    assert made.landing.kind is LaneKind.LANDING and made.landing.id == LANDING_ID
    assert made.landing.after == ("L1", "L2") and made.landing.rows == ()


def test_effort_counts_files_touched_and_skips_citations():
    row = qrow("RT-A", files=["agent_runtime/batch/{planner,machine}.py", "docs/agent-runtime-harness/x.md",
                              "Harness_Brain/30 — Decisions/0011.md", "tests/a/test_x.py::test_y"])
    assert touched_files(row) == ("agent_runtime/batch/planner.py", "agent_runtime/batch/machine.py", "tests/a/test_x.py")
    assert row_effort(row) == 3
    assert row_effort(qrow("RT-B")) == 1


def test_a_lane_is_budgeted_by_effort_not_by_row_count():
    light = [qrow(f"RT-L{i}") for i in range(65)]
    assert len(plan(light, workspace_id=WS).lanes) == 1, "65 one-file rows fit one lane"
    roomy = Budget(max_effort_per_lane=1000)
    assert len(plan([*light, qrow("RT-L65")], workspace_id=WS, budget=roomy).lanes) == 2, "65 rows is a ceiling"
    heavy = [qrow(f"RT-H{i}", files=[f"{area}/m{i}_{k}.py" for k in range(8)])
             for i, area in enumerate(["agent_runtime", "agent_runtime", "tools", "tools", "hermes_cli", "scripts"])]
    lanes = plan(heavy, workspace_id=WS, budget=Budget(max_effort_per_lane=16)).lanes
    assert [[r.id for r in lane.rows] for lane in lanes] == [["RT-H0", "RT-H1"], ["RT-H4", "RT-H5"], ["RT-H2", "RT-H3"]]
    assert all(lane.effort <= 16 for lane in lanes)


def test_a_shared_file_sequences_the_later_lane():
    rows = [qrow("RT-A", files=["agent_runtime/shared.py"]), qrow("RT-B", heading="Seams", files=["agent_runtime/shared.py"]),
            qrow("RT-C", heading="Upstream-owned", files=["cron/x.py"])]
    lanes = plan(rows, workspace_id=WS).lanes
    assert [lane.after for lane in lanes] == [(), ("L1",), ()]


def test_persona_by_assignee_then_role_match_then_ask():
    by_instance = plan([qrow("RT-A", assignee="inst-quinn")], workspace_id=WS, roster=ROSTER)
    assert by_instance.lanes[0].persona == "inst-quinn"
    by_persona = plan([qrow("RT-A", assignee="cody")], workspace_id=WS, roster=ROSTER)
    assert by_persona.lanes[0].persona == "inst-cody"
    by_role = plan([qrow("RT-A")], workspace_id=WS, roster=ROSTER, slot_roles={"hermes": "qa"})
    assert by_role.lanes[0].persona == "inst-quinn" and by_role.asks == ()
    asked = plan([qrow("RT-A")], workspace_id=WS, roster=ROSTER, slot_roles={"hermes": "designer"})
    assert asked.lanes[0].persona is None and asked.asks == ("L1", LANDING_ID)
    answered = asked.with_personas({"L1": "inst-cody"})
    assert answered.asks == () and answered.landing.persona == "inst-cody" and answered.id == asked.id
    with pytest.raises(WorkRefused) as mixed:
        plan([qrow("RT-A", assignee="cody"), qrow("RT-B", assignee="quinn")], workspace_id=WS, roster=ROSTER)
    assert mixed.value.reason is Reason.PLAN_REFUSED and "mixed_assignees" in mixed.value.detail


def test_heavy_and_quiet_box_rows_mark_their_lane():
    lanes = plan([qrow("RT-A", extra=" after the release merge"), qrow("RT-B", heading="Flakes", extra=" a flaky timeout"),
                  qrow("RT-C", heading="Plain")], workspace_id=WS).lanes
    assert [(lane.domain.heading, lane.heavy, lane.quiet_box) for lane in lanes] == [
        ("Flakes", False, True), ("Fork-owned", True, False), ("Plain", False, False)]


def test_the_plan_id_is_the_rows_and_nothing_ready_refuses():
    rows = [qrow("RT-A"), qrow("RT-B", heading="Seams")]
    first, again = plan(rows, workspace_id=WS), plan(list(reversed(rows)), workspace_id=WS)
    assert first.id == again.id and first.id.startswith("BATCH-") and len(first.id) == 12
    assert plan([*rows, qrow("RT-C")], workspace_id=WS).id != first.id
    with pytest.raises(WorkRefused) as none:
        plan([], workspace_id=WS)
    assert none.value.reason is Reason.PLAN_REFUSED


def test_the_landing_lane_carries_one_gate_per_slot_and_round_trips_the_wire():
    declared = {"toolchain": {"kind": "python"}, "context": {"gate": ["bash scripts/lint.sh", "bash scripts/t.sh"]}}
    slot_gates = {"hermes": slot_gate(declared, is_default=False),
                  "launcher": slot_gate({"toolchain": {"kind": "flutter"}}, is_default=False),
                  "backend": slot_gate({"toolchain": {"kind": "rust"}}, is_default=False),
                  "unused": (LANDING_GATE,)}
    rows = [qrow("RT-H"), qrow("RT-L", slot="launcher"), qrow("RT-B", slot="backend")]
    made = plan(rows, workspace_id=WS, slot_gates=slot_gates)
    assert dict(made.landing.gates) == {
        "backend": None,
        "hermes": ("bash scripts/lint.sh", "bash scripts/t.sh"),
        "launcher": ("dart tool/heavy_run/run.dart -- dart tool/run_tier.dart",),
    }
    assert all(lane.gates == {} for lane in made.lanes), "only the landing lane carries gates"
    assert "- backend: NO GATE DECLARED" in made.landing.brief.objective
    assert made.landing.brief.tests == ("bash scripts/lint.sh", "bash scripts/t.sh",
                                        "dart tool/heavy_run/run.dart -- dart tool/run_tier.dart")
    wired = made.wire()
    assert wired["landing"]["gates"]["backend"] is None
    again = Plan.from_wire(wired)
    assert again == made and dict(again.landing.gates) == dict(made.landing.gates)
    old = {key: value for key, value in made.landing.wire().items() if key != "gates"}
    assert Lane.from_wire(old).gates == {}, "a manifest from before the gates folds to none (every slot red)"


def test_a_lane_takes_the_union_of_its_rows_skills_and_round_trips_the_wire():
    """p10-work S1: ``Lane.skills`` is the union of the rows' ``skills:`` segments, named in the brief."""

    from agent_runtime.work_store.grammar import parse_row

    def lent(row_id, *skills):
        line = f"- **`{row_id}` — t** · `agent_runtime/{row_id}.py` · skills: " + ", ".join(f"`{s}`" for s in skills)
        return parse_row(line + " · READY 2026-10-19", slot="hermes", note=NOTE, line_no=1, heading="Fork-owned")

    made = plan([lent("RT-A", "git-workflow", "eternia/qa"), lent("RT-B", "eternia/qa", "pytest"), qrow("RT-C")],
                workspace_id=WS)
    [lane] = made.lanes
    assert lane.skills == ("git-workflow", "eternia/qa", "pytest")
    assert "Skills lent for this lane (preloaded): git-workflow, eternia/qa, pytest" in lane.brief.objective
    assert lane.files == ("agent_runtime/RT-A.py", "agent_runtime/RT-B.py"), "a lent skill is not a touched file"
    assert "`eternia/qa`" not in lane.brief.inputs
    assert Plan.from_wire(made.wire()).lanes[0].skills == lane.skills
    assert made.landing.skills == ()
