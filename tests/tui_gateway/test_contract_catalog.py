"""The contract seam: the generated catalog answers the gateway's runtime contract questions as pydantic does.

``tui_gateway/contract_seam.py`` hands the gateway either the pydantic registry or, under
``tui_gateway.pydantic_contracts: false`` (the phone), ``tui_gateway/contract_catalog.py``
over data rendered from the same models. Measured here, against the pydantic registry,
never against an expectation typed in this file:

* the committed data is what the generator renders from the live models (freshness);
* ``validate_params`` answers the unknown-key ``4000`` identically for an unknown key at
  EVERY nesting path of EVERY method and server request (probes enumerated from the models);
* a server request's answer the shape rejects, pydantic rejects too (value TYPES are the
  documented gap: a well-shaped answer with a wrong-typed value passes the catalog);
* every method admits ``profile`` under both (the in-process worker's routing question).

Killing mutations (applied, red recorded, reverted — see the commit message):

* ``shape_errors`` skips nested fields (``elif spec is not None`` arm removed) -> nested-probe parity red.
* ``_one`` locates a discriminated member by model name instead of its tag   -> nested-probe parity red.
* ``_one`` refuses a non-object for an open union (``RecordRepoItem | str``)  -> smart-union control red.
* ``contract_registry`` ignores the switch                                    -> seam test red.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _generator():
    spec = importlib.util.spec_from_file_location("gen_contract_catalog", REPO / "scripts" / "gen_contract_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_catalog_is_the_live_models():
    generator = _generator()
    rendered = generator.render()
    assert rendered == generator.TARGET.read_text(encoding="utf-8"), "run scripts/gen_contract_catalog.py"
    assert "'eternia.skills.detail'" in rendered and "'session.create'" in rendered  # control: fork + upstream


def _probe_values(model: str, depth: int = 0):
    """Every object that is ``model``-shaped except for ONE unknown key, placed at each nesting path."""
    from tui_gateway import contract_catalog_data as data

    yield {"zz_unknown": 1}
    if depth >= 3:
        return
    for wire, spec in data.MODELS[model]["fields"].items():
        if spec is None:
            continue
        members = [(spec["model"], None)] if "model" in spec else list(
            zip(spec["union"], [None] * len(spec["union"])) if spec["discriminator"] is None
            else [(m, t) for t, m in spec["mapping"].items()])
        for member, tag in members:
            for inner in _probe_values(member, depth + 1):
                value = dict(inner, **({spec["discriminator"]: tag} if tag is not None else {}))
                wrapped = {"list": [value], "dict": {"k": value}}.get(spec["arity"], value)
                yield {wire: wrapped}


def _contracts(table: str):
    from tui_gateway import contract_catalog
    from tui_gateway.contracts import registry

    from agent_runtime.conversations.worker_skills import declare_contracts

    declare_contracts()
    return getattr(registry, table), getattr(contract_catalog, table)


@pytest.mark.parametrize("table", ["METHODS", "SERVER_REQUESTS"])
def test_an_unknown_key_anywhere_is_refused_with_pydantics_words(table):
    from tui_gateway import contract_catalog
    from tui_gateway.contracts import registry

    pydantic_side, catalog_side = _contracts(table)
    assert set(catalog_side) == set(pydantic_side)
    refused = nested = 0
    for name, contract in sorted(pydantic_side.items()):
        for probe in _probe_values(catalog_side[name].params.__name__):
            expected = registry.validate_params(contract, probe)
            assert contract_catalog.validate_params(catalog_side[name], probe) == expected, (name, probe)
            if expected[1] is not None:
                refused += 1
                loc = expected[1].removeprefix(f"invalid params for {name}: ").split(": Extra")[0]
                nested += "." in loc
    assert refused >= len(pydantic_side) and nested > 0  # control: probes reached pydantic, nested ones too


def test_a_smart_union_passes_when_a_member_does():
    """Positive control for the union walk: ``RecordRepoItem | str`` takes a string; a discriminated
    owner takes its own member's keys."""
    from tui_gateway import contract_catalog
    from tui_gateway.contracts import registry

    pydantic_side, catalog_side = _contracts("METHODS")
    for name, params in (("projects.record_repos", {"repos": ["plain-string"]}),
                         ("connectors.list", {"owner": {"type": "session", "session_id": "s"}})):
        assert registry.validate_params(pydantic_side[name], params)[1] is None
        assert contract_catalog.validate_params(catalog_side[name], params) == (params, None)
        pydantic_side[name].params.model_validate(params)  # the whole shape passes, not only the extra check
        assert catalog_side[name].params.model_validate(params) == params


def test_an_answer_the_shape_refuses_pydantic_refuses_too():
    pydantic_side, catalog_side = _contracts("SERVER_REQUESTS")
    checked = 0
    for name, contract in sorted(pydantic_side.items()):
        for probe in [{}, *_probe_values(catalog_side[name].result.__name__)]:
            try:
                catalog_side[name].result.model_validate(probe)
            except ValueError:
                with pytest.raises(ValueError):
                    contract.result.model_validate(probe)
                checked += 1
    assert checked > len(pydantic_side)
    approval = {"choice": "once", "all": None}
    assert catalog_side["approval"].result.model_validate(approval) == approval  # control: a real answer passes
    contract = pydantic_side["approval"]
    contract.result.model_validate(approval)


def _switch(tmp_hermes_home: Path, on: bool) -> None:
    tmp_hermes_home.mkdir(parents=True, exist_ok=True)
    (tmp_hermes_home / "config.yaml").write_text(json.dumps({"tui_gateway": {"pydantic_contracts": on}}),
                                                 encoding="utf-8")


def test_the_seam_follows_the_switch_and_the_worker_routes_profile_identically():
    from agent_runtime.conversations import in_process_peer
    from hermes_constants import get_hermes_home
    from tui_gateway import contract_catalog
    from tui_gateway.contract_seam import contract_registry
    from tui_gateway.contracts import registry

    pydantic_side, _ = _contracts("METHODS")
    home = Path(get_hermes_home())
    _switch(home, on=True)
    assert contract_registry() is registry
    admits = {name: in_process_peer._admits_profile(name) for name in pydantic_side}
    _switch(home, on=False)
    assert contract_registry() is contract_catalog
    assert {name: in_process_peer._admits_profile(name) for name in pydantic_side} == admits
    assert any(admits.values()) and not all(admits.values())  # control: both answers occur
