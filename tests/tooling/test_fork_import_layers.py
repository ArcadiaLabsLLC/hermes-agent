"""W0-G6 — the fork's import graph points DOWN its layers, and never through a back door.

Plan: ``docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md`` rule
16 and §2.4. Layers, lowest first: ``models`` -> ``policy`` -> ``stores`` ->
``lanes`` -> ``wiring`` (``scripts/god_file_probe.py::LAYERS``).

* Every module under ``agent_runtime/``, ``hermes_cli/harness_parts/`` and
  ``plugins/eternia-harness/`` declares its layer — ``__layer__`` in the module,
  or its package ``__init__``'s ``__layers__`` map — or is grandfathered until
  its lane opens it (the list only shrinks).
* A declared module imports only same-or-lower declared layers. The layer is
  read at RUNTIME from the imported module (POSITIVE: the value is bound, not
  merely spelled); the source walk only ENUMERATES which modules declare one.
* No harness part imports ``hermes_cli.harness`` (grandfathered sites shrink).
* No fork module imports a ``_private`` name from an upstream module (the
  second-door rule made mechanical; grandfathered sites shrink).

Baseline: ``tests/fixtures/import_layers_grandfathered.json``.
"""

from __future__ import annotations

import sys

import pytest

from scripts import god_file_probe as probe


def _arm(key: str) -> probe.Drift:
    live = set(probe.layer_census()[key])
    return probe.compare_sets(f"W0-G6 {key}", live, probe.layer_fixture().get(key, set()))


@pytest.mark.parametrize("key", ["undeclared", "harness_imports", "private_upstream_imports"])
def test_no_new_site(key):
    drift = _arm(key)
    assert not drift.new, f"new {key} sites — declare the layer / use the public door:\n" + drift.render()


@pytest.mark.parametrize("key", ["undeclared", "harness_imports", "private_upstream_imports"])
def test_a_fixed_site_loses_its_row(key):
    drift = _arm(key)
    assert not drift.stale, "delete these rows — the site is gone:\n" + drift.render()


def test_declared_layers_are_bound_at_runtime_and_point_down():
    root = probe.ROOT
    declared = probe.declared_modules(root)
    layers = {dotted: probe.runtime_layer(root, path) for path, dotted in declared.items()}
    unbound = sorted(m for m, layer in layers.items() if layer is None)
    assert not unbound, f"these modules spell a layer the runtime does not bind: {unbound}"
    imports = {dotted: probe.module_imports(root, path) for path, dotted in declared.items()}
    assert probe.layer_violations(layers, imports) == []


def test_the_layer_check_reds_an_upward_import_read_at_runtime(tmp_path, monkeypatch):
    """Positive control: a real package, layers read by importing it, one upward import."""
    package = tmp_path / "w0g6pkg"
    package.mkdir()
    (package / "__init__.py").write_text('__layers__ = {"wire": "wiring"}\n', encoding="utf-8")
    (package / "store.py").write_text(
        '_LAYER = "stores"\n__layer__ = _LAYER\nfrom w0g6pkg import wire\n', encoding="utf-8"
    )
    (package / "wire.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "model.py").write_text('__layer__ = "models"\n', encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        paths = {"w0g6pkg/store.py", "w0g6pkg/wire.py", "w0g6pkg/model.py"}
        assert all(probe.declares_layer(tmp_path, p) for p in paths)
        layers = {probe.module_name(p): probe.runtime_layer(tmp_path, p) for p in paths}
        assert layers == {"w0g6pkg.store": "stores", "w0g6pkg.wire": "wiring", "w0g6pkg.model": "models"}
        imports = {probe.module_name(p): probe.module_imports(tmp_path, p) for p in paths}
        assert probe.layer_violations(layers, imports) == [
            "w0g6pkg.store (stores) imports w0g6pkg.wire (wiring) — an upward import"
        ]
        assert probe.layer_violations({**layers, "w0g6pkg.store": "lanes"}, imports) == [
            "w0g6pkg.store (lanes) imports w0g6pkg.wire (wiring) — an upward import"
        ]
        assert probe.layer_violations({**layers, "w0g6pkg.store": "wiring"}, imports) == []
    finally:
        for name in [m for m in sys.modules if m.startswith("w0g6pkg")]:
            del sys.modules[name]
