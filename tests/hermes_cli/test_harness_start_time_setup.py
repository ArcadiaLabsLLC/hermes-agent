"""``hermes harness …`` builds its command line with no plugin load, and the verb runs the start-time setup.

``RT-HARNESS-PARSER-PLUGIN-LOAD-TWICE``: the real ``plugins/eternia-harness/plugin.yaml`` names the parser
setup, so the parse loads nothing and runs no migration; ``hermes_cli.harness._harness_entry`` runs
``hermes_cli.harness_parts.start_time_setup.run_start_time_setup`` before the handler; the migrations run
once per process for one set of stores. Each guarantee carries its positive control.
"""

from __future__ import annotations

import sys

import pytest

import hermes_cli.main as main_mod
from hermes_cli import harness as harness_mod
from hermes_cli import plugins as plugins_mod
from hermes_cli.harness_parts import start_time_setup as start_time

MIGRATIONS = ("migrate_retired_local_llama_id", "migrate_legacy_persona_toolsets", "retire_legacy_harness_blocks",
              "seed_persona_profile_defaults", "migrate_legacy_office_schema", "migrate_shared_character_assignments",
              "retire_persona_assignment_store")


@pytest.fixture
def plugin_loads(monkeypatch):
    """Names of the plugins ``PluginManager._load_plugin`` was asked to load, on fresh managers."""
    loads = []
    real = plugins_mod.PluginManager._load_plugin

    def counting(self, manifest):
        loads.append(manifest.name)
        return real(self, manifest)

    monkeypatch.setattr(plugins_mod.PluginManager, "_load_plugin", counting)
    plugins_mod._reset_plugin_managers_for_tests()
    yield loads
    plugins_mod._reset_plugin_managers_for_tests()


@pytest.fixture
def start_time_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(start_time, "run_start_time_setup", lambda: calls.append("start_time"))
    return calls


def test_the_harness_command_line_is_built_with_no_plugin_load_and_no_start_time_work(
        plugin_loads, start_time_calls, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hermes", "harness", "doctor"])
    parser, subparsers = main_mod._build_cli_parser()

    args = main_mod._parse_cli_args(parser, subparsers, ["harness", "doctor"])

    assert args.harness_command == "doctor" and getattr(args.func, "__harness_entry__", False)
    assert plugin_loads == [] and start_time_calls == []
    # Positive control: `postinstall`, the same plugin's row WITHOUT `setup:`, does load it to attach
    # (and that load's register(ctx) is the start-time setup's other caller).
    monkeypatch.setattr(sys, "argv", ["hermes", "postinstall"])
    plugins_mod._reset_plugin_managers_for_tests()
    main_mod._build_cli_parser()
    assert plugin_loads == ["eternia-harness"] and start_time_calls == ["start_time"]


def test_the_manifest_setup_is_the_function_the_plugin_registers(plugin_loads):
    """One parser whichever way it is attached: the row's ``setup:`` resolves to what ``register(ctx)`` calls."""
    import importlib

    from hermes_cli import plugins_declared_cli as declared_mod

    row = next(c for c in declared_mod.discover_declared_cli_commands() if c["name"] == "harness")
    module, _, function = row["setup"].partition(":")
    named = getattr(importlib.import_module(module), function)
    seen = []
    plugins_mod.discover_plugins()
    registered = plugins_mod.get_plugin_manager()._cli_commands["harness"]["setup_fn"]
    import hermes_cli.harness_cli_setup as setup_mod

    original = setup_mod.setup_harness_parser
    try:
        setup_mod.setup_harness_parser = seen.append
        registered("the parser")
    finally:
        setup_mod.setup_harness_parser = original
    assert named is original and seen == ["the parser"]


def test_a_harness_verb_runs_the_start_time_setup_before_its_handler(start_time_calls, monkeypatch):
    monkeypatch.setattr("agent_runtime.core_cache.home.capture_for_harness_command",
                        lambda args: start_time_calls.append("capture"))

    def handler(args):
        start_time_calls.append("handler")
        return 3

    assert harness_mod._harness_entry(handler)("args") == 3
    assert start_time_calls == ["start_time", "capture", "handler"]


@pytest.fixture
def counted_migrations(monkeypatch):
    ran = []
    for name in MIGRATIONS:
        monkeypatch.setattr(start_time, name, lambda _n=name: ran.append(_n))
    monkeypatch.setattr(start_time, "_MIGRATED", set())
    for name in ("bind_mission_chat_door",):
        monkeypatch.setattr(f"hermes_cli.harness_parts.mission_chat_door_binding.{name}", lambda: ran.append("door"))
    monkeypatch.setattr("agent_runtime.harness_toolset.ensure_harness_core", lambda: ran.append("harness_core"))
    monkeypatch.setattr("agent_runtime.running_work.process_presence.install_process_presence", lambda: None)
    monkeypatch.setattr("agent_runtime.guardrail_mcp_names.add_registry_spelled_filesystem_reads", lambda: None)
    return ran


def test_two_calls_run_each_migration_once_and_the_globals_twice(counted_migrations, tmp_path, monkeypatch):
    start_time.run_start_time_setup()
    start_time.run_start_time_setup()  # the serve: the verb's entry, then post-ready register(ctx)

    assert [n for n in counted_migrations if n in MIGRATIONS] == list(MIGRATIONS)
    assert counted_migrations.count("door") == 2 and counted_migrations.count("harness_core") == 2
    # Positive control: another profile home is another set of stores, and its migrations DO run.
    other = tmp_path / "other_home"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))
    start_time.run_start_time_setup()
    assert [n for n in counted_migrations if n in MIGRATIONS] == list(MIGRATIONS) * 2


def test_a_frozen_config_worker_runs_only_the_store_migrations(counted_migrations, monkeypatch):
    monkeypatch.setattr(start_time, "_worker_config_frozen", lambda: True)

    start_time.run_start_time_setup()

    assert [n for n in counted_migrations if n in MIGRATIONS] == list(MIGRATIONS[4:])
