"""Manifest-declared plugin CLI commands (seam Stage 1, ``fork: hook-pending``).

``plugin.yaml``'s ``cli_commands:`` rows are attached BEFORE plugin discovery,
each stub materialising only its own plugin. Two guarantees, each with a
positive control so a green negative cannot be a fixture that never reached
the guard:

1. A declared command's stub loads exactly ONE plugin — its own.
2. ``hermes harness <verb>`` builds and parses without ``discover_plugins()``.
"""

from __future__ import annotations

import argparse
import sys
import textwrap

import pytest

import hermes_cli.main as main_mod
from hermes_cli import plugins as plugins_mod


def _write_plugin(root, name, marker_dir):
    plugin = root / name
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text(textwrap.dedent(f"""\
        name: {name}
        kind: backend
        cli_commands:
          - name: {name}
            help: the {name} command
        """), encoding="utf-8")
    marker = (marker_dir / f"{name}.registered").as_posix()
    (plugin / "__init__.py").write_text(textwrap.dedent(f"""\
        def _setup(parser):
            parser.add_argument("--{name}-flag", action="store_true")

        def _run(args):
            return 0

        def register(ctx):
            open({marker!r}, "w").close()
            ctx.register_cli_command({name!r}, help="h", setup_fn=_setup, handler_fn=_run)
        """), encoding="utf-8")


@pytest.fixture
def two_bundled_plugins(tmp_path, monkeypatch):
    bundled, markers = tmp_path / "bundled", tmp_path / "markers"
    bundled.mkdir()
    markers.mkdir()
    for name in ("alpha", "beta"):
        _write_plugin(bundled, name, markers)
    monkeypatch.setattr(plugins_mod, "get_bundled_plugins_dir", lambda: bundled)
    plugins_mod._reset_plugin_managers_for_tests()
    yield markers
    plugins_mod._reset_plugin_managers_for_tests()


def _attach(cmd_info):
    subparsers = argparse.ArgumentParser(prog="hermes").add_subparsers(dest="command")
    main_mod._attach_plugin_cli_command(subparsers, cmd_info)
    return subparsers.choices[cmd_info["name"]]


def test_a_declared_stub_materialises_exactly_its_own_plugin(two_bundled_plugins):
    markers = two_bundled_plugins
    declared = {c["name"]: c for c in plugins_mod.discover_declared_cli_commands()}

    assert set(declared) == {"alpha", "beta"}
    assert not list(markers.iterdir()), "the scan must import no plugin"

    parser = _attach(declared["alpha"])

    assert sorted(p.name for p in markers.iterdir()) == ["alpha.registered"]
    args = parser.parse_args(["--alpha-flag"])
    assert args.alpha_flag is True and args.func(args) == 0
    # Positive control: the same stub mechanism DOES load beta when beta's stub runs.
    _attach(declared["beta"])
    assert sorted(p.name for p in markers.iterdir()) == ["alpha.registered", "beta.registered"]


def _parse_under(argv, monkeypatch):
    calls = []
    monkeypatch.setattr(plugins_mod, "discover_plugins", lambda *a, **k: calls.append("discover_plugins"))
    monkeypatch.setattr(sys, "argv", ["hermes", *argv])
    plugins_mod._reset_plugin_managers_for_tests()
    try:
        parser, subparsers = main_mod._build_cli_parser()
        return calls, parser, subparsers
    finally:
        plugins_mod._reset_plugin_managers_for_tests()


def test_hermes_harness_verb_never_runs_plugin_discovery(monkeypatch):
    calls, parser, subparsers = _parse_under(["harness", "doctor"], monkeypatch)

    assert calls == []
    args = main_mod._parse_cli_args(parser, subparsers, ["harness", "doctor"])
    assert args.command == "harness" and args.harness_command == "doctor"
    assert getattr(args.func, "__harness_entry__", False), args.func

    # Positive control: an undeclared, non-built-in first token DOES reach discovery
    # through the very patch the assertion above relies on.
    calls, _, _ = _parse_under(["no-such-command-s1p"], monkeypatch)
    assert calls == ["discover_plugins"]


def test_cli_commands_is_a_manifest_field_and_invalid_rows_are_skipped(tmp_path):
    from hermes_cli.plugins_manifest import parse_manifest_file

    plugin = tmp_path / "gamma"
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text(textwrap.dedent("""\
        name: gamma
        description: the gamma plugin
        cli_commands:
          - name: gamma
            description: long form
          - name: Not A Name
          - just-a-string
        """), encoding="utf-8")
    manifest = parse_manifest_file(plugin / "plugin.yaml", plugin, "bundled", "")

    assert manifest.cli_commands == [{"name": "gamma", "help": "", "description": "long form", "parent": ""}]
    # Positive control: with no cli_commands key the field is empty, not absent.
    (plugin / "plugin.yaml").write_text("name: gamma\n", encoding="utf-8")
    assert parse_manifest_file(plugin / "plugin.yaml", plugin, "bundled", "").cli_commands == []


def test_the_declared_scan_reads_config_once(two_bundled_plugins, monkeypatch):
    import hermes_cli.config as config_mod

    reads = []

    def _read():
        reads.append(1)
        return {"plugins": {"disabled": ["beta"]}}

    monkeypatch.setattr(config_mod, "load_config_readonly", _read)
    monkeypatch.setattr(plugins_mod, "load_config_readonly", _read)

    names = [c["name"] for c in plugins_mod.discover_declared_cli_commands()]

    assert len(reads) == 1
    # The one read is the one the gate used: beta is disabled by it.
    assert names == ["alpha"]


def test_discovery_after_a_declared_stub_loads_the_plugin_once(two_bundled_plugins):
    """Every ``hermes`` invocation attaches the declared stubs while building its parser, and a
    ``gateway run`` then discovers. The stub's load must not survive into that discovery: a
    second ``register(ctx)`` hits upstream's duplicate-section refusal and the ledger then
    disposes BOTH loads' registrations (alice's gateway, 2026-09-24..29)."""
    bundled = plugins_mod.get_bundled_plugins_dir()
    with open(bundled / "alpha" / "__init__.py", "a", encoding="utf-8") as fh:
        fh.write('\ndef _register_section(ctx):\n'
                 '    ctx.register_system_prompt_section("alpha.guidance", "alpha guidance")\n'
                 '_plain_register = register\n'
                 'def register(ctx):\n'
                 '    _plain_register(ctx)\n'
                 '    _register_section(ctx)\n')
    declared = {c["name"]: c for c in plugins_mod.discover_declared_cli_commands()}

    parser = _attach(declared["alpha"])
    plugins_mod.discover_plugins()

    manager = plugins_mod.get_plugin_manager()
    loaded = manager._plugins["alpha"]
    assert loaded.error is None and loaded.enabled, loaded.error
    assert manager._system_prompt_sections["alpha.guidance"].plugin == "alpha"
    assert manager._cli_commands["alpha"]["plugin_key"] == "alpha"
    # The parser the stub built outlives the stub's load.
    args = parser.parse_args(["--alpha-flag"])
    assert args.alpha_flag is True and args.func(args) == 0


def test_a_built_in_verb_skips_the_declared_scan(monkeypatch):
    """A built-in first token cannot reach a declared command, so the parser build reads
    no ``plugin.yaml`` for it (w3-perf: the scan parses every manifest, ~0.3-1.4 s, and
    materialising ``harness`` loads its plugin). Upstream's own rule, applied to the
    declared pass: plugin commands are already absent from a built-in invocation's tree."""

    scans = []
    real = plugins_mod.discover_declared_cli_commands

    def counting():
        scans.append(1)
        return real()

    monkeypatch.setattr(plugins_mod, "discover_declared_cli_commands", counting)
    _calls, _parser, subparsers = _parse_under(["gateway", "status"], monkeypatch)
    assert scans == [] and "harness" not in subparsers.choices

    # Positive control: the same build for a declared verb does scan and attach it.
    _calls, _parser, subparsers = _parse_under(["harness", "doctor"], monkeypatch)
    assert scans == [1] and "harness" in subparsers.choices
