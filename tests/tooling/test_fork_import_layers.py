"""W0-G6 — the fork's import graph points DOWN its layers, and never through a back door.

Plan: ``docs/agent-runtime-harness/planned/god-file-program-2026-09-24.md`` rule
16 and §2.4. Layers, lowest first: ``models`` -> ``policy`` -> ``stores`` ->
``lanes`` -> ``wiring`` (``scripts/god_file_probe.py::LAYERS``).

* Every module under ``agent_runtime/``, ``hermes_cli/harness_parts/``,
  ``plugins/eternia-harness/`` and every fork-only tree under ``agent/`` and
  ``tools/`` (``probe.layered_roots``: DISCOVERED as a directory holding no
  upstream file, never listed here) declares its layer — ``__layer__`` in the module,
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


def _missing_dependency(missing: dict[str, str]) -> str:
    """Name the environment defect: which declared module, which missing import, which extra."""
    import tomllib

    pyproject = tomllib.loads((probe.ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject.get("project", {}).get("optional-dependencies", {})
    lines = ["the test venv cannot import these declared modules — a missing DEPENDENCY, not a layer defect:"]
    for module, name in sorted(missing.items()):
        top = (name or "").split(".")[0]
        fix = f"the `{top}` extra: re-sync with `pip install -e .[{top}]`" if top in extras else "no extra of that name"
        lines.append(f"  {module}: No module named {name!r} ({fix})")
    return "\n".join(lines)


def test_declared_layers_are_bound_at_runtime_and_point_down():
    root = probe.ROOT
    declared = probe.declared_modules(root)
    layers, missing = {}, {}
    for path, dotted in declared.items():
        try:
            layers[dotted] = probe.runtime_layer(root, path)
        except ModuleNotFoundError as exc:
            missing[dotted] = exc.name or str(exc)
    unbound = sorted(m for m, layer in layers.items() if layer is None)
    assert not unbound, f"these modules spell a layer the runtime does not bind: {unbound}"
    imports = {dotted: probe.module_imports(root, path) for path, dotted in declared.items()}
    assert probe.layer_violations(layers, imports) == []
    assert not missing, _missing_dependency(missing)


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


def test_a_fork_submodule_under_an_upstream_package_is_not_a_private_name(tmp_path):
    """Positive control both ways: ``from pkg import _mod`` of a real FILE is a
    module import; ``from pkg import _name`` of a name is the private reach."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("_name = 1", encoding="utf-8")
    (tmp_path / "pkg" / "_mod.py").write_text("", encoding="utf-8")
    upstream = frozenset({"pkg/__init__.py"})
    assert probe.is_private_upstream_import(tmp_path, upstream, "pkg", "_name")
    assert not probe.is_private_upstream_import(tmp_path, upstream, "pkg", "_mod")
    assert not probe.is_private_upstream_import(tmp_path, upstream, "pkg", "public")
    assert not probe.is_private_upstream_import(tmp_path, upstream, "forkpkg", "_name")


def test_fork_only_trees_are_discovered_not_listed():
    """Positive control both ways: a directory with no upstream file is walked; one
    sharing a directory with upstream is not, and the live tree finds the two known."""
    upstream = frozenset({"tools/registry.py", "agent/pet/generate/core.py"})
    assert probe.fork_only_tree("tools/agent_chat_dispatch/child.py", upstream) == "tools/agent_chat_dispatch/"
    assert probe.fork_only_tree("agent/charsheet/sub/x.py", upstream) == "agent/charsheet/"
    assert probe.fork_only_tree("tools/agent_chat_tool.py", upstream) is None
    assert probe.fork_only_tree("agent/pet/generate/fork_only.py", upstream) is None
    roots = probe.layered_roots()
    assert {"agent/charsheet/", "tools/agent_chat_dispatch/"} <= set(roots) - set(probe.LAYERED_ROOTS)


def test_packages_under_scripts_and_downstream_are_walked_and_flat_files_are_not():
    """Q31 (lane B5): a PACKAGE under ``scripts/`` or ``tests/_downstream/`` is a layered
    root — its modules must declare a layer — while a flat script or conftest there is not
    walked. Positive control both ways, from the live tree: the three packages lane B5
    created are found, and the flat gate entry beside them is not under any root."""
    roots = set(probe.layered_roots())
    assert {
        "scripts/mutation_check/",
        "tests/_downstream/id_markers/",
        "tests/_downstream/hermes_cli_conftest/",
    } <= roots
    flat = ("scripts/changed_line_mutation_check.py", "tests/_downstream/conftest_plugin.py")
    assert not [path for path in flat if path.startswith(tuple(roots))]
