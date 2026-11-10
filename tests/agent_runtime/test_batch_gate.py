"""``gate.slot_gate`` — which landing-gate commands a slot runs (p10-work §3 G1, RT-BATCH-GATE-PER-SLOT-COMMAND).

Owner ruling 2026-10-19: a slot with no gate declared and no toolchain-kind match is None (the lane executor's
RED receipt "no gate declared"), never a skip. Killing mutation, red recorded in its commit body:
``slot_gate`` consults ``GATES_BY_TOOLCHAIN_KIND`` before ``context.gate`` →
``test_slot_gate_order_declared_kind_brain_none`` red (the declared commands lose to the kind's).
"""

from __future__ import annotations

from agent_runtime.batch.gate import GATE_NONE, GATES_BY_TOOLCHAIN_KIND, slot_gate
from agent_runtime.batch.planner import LANDING_GATE


def test_slot_gate_order_declared_kind_brain_none():
    declared = {"toolchain": {"kind": "flutter"}, "context": {"role": "frontend", "gate": ["make check"]}}
    # (1) the declared context.gate wins over the kind, and over being the default brain.
    assert slot_gate(declared, is_default=True) == ("make check",)
    # ... and an empty declaration stays empty ("declared none": the runner's red, not the kind's command).
    assert slot_gate({"toolchain": {"kind": "python"}, "context": {"gate": []}}, is_default=False) == ()
    # (2) the toolchain kind's table entry, case-insensitive.
    assert slot_gate({"toolchain": {"kind": "Flutter"}}, is_default=False) == GATES_BY_TOOLCHAIN_KIND["flutter"]
    assert slot_gate({"toolchain": {"kind": "hermes"}, "context": {}}, is_default=False) == (LANDING_GATE,)
    assert slot_gate({"toolchain": {"kind": "brain"}}, is_default=False) == (GATE_NONE,)
    # (3) the default brain: the green no-op.
    assert slot_gate(None, is_default=True) == (GATE_NONE,)
    assert slot_gate({"toolchain": {"kind": "rust"}}, is_default=True) == (GATE_NONE,)
    # (4) nothing: None, the red "no gate declared".
    assert slot_gate({"toolchain": {"kind": "rust"}, "context": {"role": "x"}}, is_default=False) is None
    assert slot_gate(None, is_default=False) is None


def test_the_serve_reads_each_boards_gate_from_its_slot(monkeypatch):
    """``dispatcher._slot_gates``: one entry per board; the default brain (not a declared slot) is the no-op."""

    from types import SimpleNamespace

    from agent_runtime import workspace_slots
    from agent_runtime.batch import dispatcher
    from agent_runtime.work_store import board

    slots = {"hermes": {"toolchain": {"kind": "python"}, "context": {}},
             "site": {"toolchain": {"kind": "rust"}, "context": {"gate": ["cargo test"]}},
             "odd": {"toolchain": {"kind": ""}, "context": {}}}
    monkeypatch.setattr(workspace_slots, "load_document", lambda _ws: {"slots": slots})
    monkeypatch.setattr(workspace_slots, "live_slots", lambda document: document["slots"])
    monkeypatch.setattr(board, "boards", lambda _ws: [SimpleNamespace(slot=name, is_default=False) for name in slots]
                        + [SimpleNamespace(slot="brain", is_default=True)])
    assert dispatcher._slot_gates("ws-1") == {"hermes": (LANDING_GATE,), "site": ("cargo test",), "odd": None,
                                              "brain": (GATE_NONE,)}
