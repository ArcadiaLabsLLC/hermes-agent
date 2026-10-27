"""The generator renders the package's import-time catalog, never what a lane declares later.

FH-FORK-CONTRACTS-MUTATE-RENDERED-REGISTRY: importing ``tui_gateway.server`` runs the fork
lanes' ``declare_contracts()``, which grow ``tui_gateway.contracts.registry``'s tables; the
committed TypeScript + OpenRPC must still equal a regeneration from that process.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "scripts" / "gen_gateway_contracts.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_gateway_contracts_rendered", GEN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declare_lane_contracts() -> None:
    from agent_runtime.conversations import worker_subagents
    from tui_gateway.contracts import registry

    if not any(name.startswith("eternia.subagents.") for name in registry.METHODS):
        worker_subagents.declare_contracts()


def test_lane_contracts_reach_the_live_tables_but_not_the_rendered_catalog():
    from agent_runtime.gateway import rendered_contracts
    from tui_gateway.contracts import registry

    _declare_lane_contracts()
    # Positive control: the lane really is in the live tables the gateway validates against.
    assert any(name.startswith("eternia.subagents.") for name in registry.METHODS)
    assert not any(name.startswith("eternia.subagents.") for name in rendered_contracts.METHODS)
    assert set(rendered_contracts.METHODS) < set(registry.METHODS)


def test_generated_files_stay_current_after_a_lane_declared_its_contracts():
    _declare_lane_contracts()
    gen = _load_generator()
    rendered = gen.render_all()
    stale = [path.relative_to(REPO) for path, text in rendered.items()
             if (path.read_text(encoding="utf-8") if path.exists() else None) != text]
    assert not stale, f"the lane's contracts reached the rendered catalog: {stale}"
    ts = rendered[gen.TS_OUT]
    assert "eternia.subagents." not in ts
    assert "tui_gateway_contracts_billing_delegation_pets_SubagentSteerParams" not in ts
