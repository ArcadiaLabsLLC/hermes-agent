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
from hermes_cli import plugins_manifest_cli_commands as declared_mod


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
    declared = {c["name"]: c for c in declared_mod.discover_declared_cli_commands()}

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

    names = [c["name"] for c in declared_mod.discover_declared_cli_commands()]

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
    declared = {c["name"]: c for c in declared_mod.discover_declared_cli_commands()}

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
    real = declared_mod.discover_declared_cli_commands

    def counting():
        scans.append(1)
        return real()

    monkeypatch.setattr(declared_mod, "discover_declared_cli_commands", counting)
    _calls, _parser, subparsers = _parse_under(["gateway", "status"], monkeypatch)
    assert scans == [] and "harness" not in subparsers.choices

    # Positive control: the same build for a declared verb does scan and attach it.
    _calls, _parser, subparsers = _parse_under(["harness", "doctor"], monkeypatch)
    assert scans == [1] and "harness" in subparsers.choices


# ── RT-HARNESS-ARGV-MANIFEST-SCAN: the fingerprint cache (T2-T8; T1 is
# tests/hermes_cli/test_declared_cli_cache_superset.py, a gate) ──────────────────────────────

from hermes_cli import plugins_declared_cli_cache as cache_mod  # noqa: E402
from hermes_cli import plugins_discovery as discovery_mod  # noqa: E402
from hermes_cli import plugins_manifest as manifest_mod  # noqa: E402


def _home():
    from hermes_constants import get_hermes_home
    return get_hermes_home()


@pytest.fixture
def counting_parses(monkeypatch):
    """Every ``parse_manifest_file`` call, from the upstream walk or the cache-hit re-parse."""
    calls = []
    real = manifest_mod.parse_manifest_file

    def counting(manifest_file, *a, **k):
        calls.append(str(manifest_file))
        return real(manifest_file, *a, **k)

    monkeypatch.setattr(manifest_mod, "parse_manifest_file", counting)
    monkeypatch.setattr(discovery_mod, "parse_manifest_file", counting)
    return calls


@pytest.fixture
def three_bundled_plugins(two_bundled_plugins):
    """alpha + beta declare a command; gamma declares none (a manifest only the miss parses)."""
    gamma = plugins_mod.get_bundled_plugins_dir() / "gamma"
    gamma.mkdir()
    (gamma / "plugin.yaml").write_text("name: gamma\nkind: backend\n", encoding="utf-8")
    return plugins_mod.get_bundled_plugins_dir()


def _shape(commands):
    return [(c["name"], c["parent"], c["plugin_key"], c["help"]) for c in commands]


def test_a_cache_hit_reparses_only_the_declaring_manifests(three_bundled_plugins, counting_parses):
    """T2: the miss parses all three; the hit parses the two declaring ones and answers the same."""
    first = declared_mod.discover_declared_cli_commands()
    assert len(counting_parses) == 3 and cache_mod.cache_path(_home()).is_file()

    counting_parses.clear()
    second = declared_mod.discover_declared_cli_commands()

    assert sorted(counting_parses) == sorted(str(three_bundled_plugins / n / "plugin.yaml") for n in ("alpha", "beta"))
    assert _shape(second) == _shape(first) == [("alpha", None, "alpha", "the alpha command"),
                                                ("beta", None, "beta", "the beta command")]


def test_a_touched_manifest_is_a_miss_that_rewrites_the_cache(three_bundled_plugins, counting_parses):
    """T3: same bytes, new mtime → the full walk runs again and the cache digest moves."""
    import os

    declared_mod.discover_declared_cli_commands()
    before = cache_mod.read_cache(_home()).digest
    gamma = three_bundled_plugins / "gamma" / "plugin.yaml"
    st = gamma.stat()
    os.utime(gamma, ns=(st.st_atime_ns, st.st_mtime_ns + 7_000_000_000))

    counting_parses.clear()
    declared_mod.discover_declared_cli_commands()

    assert len(counting_parses) == 3
    assert cache_mod.read_cache(_home()).digest != before


def test_a_user_override_without_cli_commands_hides_the_bundled_command(three_bundled_plugins):
    """T4: precedence after a hit — a user copy of alpha that declares nothing shadows bundled alpha."""
    assert {c["name"] for c in declared_mod.discover_declared_cli_commands()} == {"alpha", "beta"}
    assert {c["name"] for c in declared_mod.discover_declared_cli_commands()} == {"alpha", "beta"}  # the hit

    override = _home() / "plugins" / "alpha"
    override.mkdir(parents=True)
    (override / "plugin.yaml").write_text("name: alpha\nkind: backend\n", encoding="utf-8")

    assert {c["name"] for c in declared_mod.discover_declared_cli_commands()} == {"beta"}


def test_the_enable_gate_is_live_on_a_cache_hit(three_bundled_plugins, monkeypatch):
    """T5: the cache holds winners, never a gate verdict; disabling after a hit removes the command."""
    import hermes_cli.config as config_mod

    declared_mod.discover_declared_cli_commands()  # miss, cache written
    assert cache_mod.read_cache(_home()) is not None

    def _disabled():
        return {"plugins": {"disabled": ["alpha"]}}

    monkeypatch.setattr(config_mod, "load_config_readonly", _disabled)
    monkeypatch.setattr(plugins_mod, "load_config_readonly", _disabled)

    assert [c["name"] for c in declared_mod.discover_declared_cli_commands()] == ["beta"]


def test_a_corrupt_cache_is_a_miss_that_rewrites_it(three_bundled_plugins, counting_parses):
    """T6: garbage in the cache file never reaches the parser build."""
    path = cache_mod.cache_path(_home())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert {c["name"] for c in declared_mod.discover_declared_cli_commands()} == {"alpha", "beta"}
    assert len(counting_parses) == 3
    assert cache_mod.read_cache(_home()) is not None


def test_safe_mode_reads_and_writes_no_cache(three_bundled_plugins, monkeypatch):
    """T7: ``HERMES_SAFE_MODE`` answers nothing before any I/O; positive control writes the file."""
    path = cache_mod.cache_path(_home())
    monkeypatch.setenv("HERMES_SAFE_MODE", "1")
    assert declared_mod.discover_declared_cli_commands() == []
    assert not path.exists()

    monkeypatch.delenv("HERMES_SAFE_MODE")
    assert declared_mod.discover_declared_cli_commands()
    assert path.is_file()


def test_an_unwritable_cache_still_answers_the_rows(three_bundled_plugins, monkeypatch):
    """T8: fail-open on write — the cache's parent is a FILE, so its directory cannot be made."""
    blocker = _home() / "cache-blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(cache_mod, "CACHE_RELPATH", "cache-blocker/declared_cli_commands.json")

    for _ in range(2):
        assert {c["name"] for c in declared_mod.discover_declared_cli_commands()} == {"alpha", "beta"}
    assert blocker.is_file()
