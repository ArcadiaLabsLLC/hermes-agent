"""``hermes <declared plugin command> …`` is parsed without building the other commands' parsers.

``hermes_cli/main_declared_parser.py::declared_command_parser`` (RT-HARNESS-SERVE-SKIP-UPSTREAM-PARSERS): ``main()``
asks it first and builds the whole tree only when it answers None. Each guarantee carries its positive control.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

import hermes_cli.main as main_mod
from hermes_cli import main_declared_parser as declared_parser_mod
from hermes_cli import plugins as plugins_mod


def _write_plugin(root, name, marker_dir, *, broken=False):
    plugin = root / name
    plugin.mkdir()
    (plugin / "plugin.yaml").write_text(textwrap.dedent(f"""\
        name: {name}
        kind: backend
        cli_commands:
          - name: {name}
            help: the {name} command
        """), encoding="utf-8")
    registered, ran = ((marker_dir / f"{name}.{word}").as_posix() for word in ("registered", "ran"))
    setup = 'raise RuntimeError("no parser today")' if broken else f'parser.add_argument("--{name}-flag", action="store_true")'
    (plugin / "__init__.py").write_text(textwrap.dedent(f"""\
        def _setup(parser):
            {setup}

        def _run(args):
            open({ran!r}, "w").close()
            return 0

        def register(ctx):
            open({registered!r}, "w").close()
            ctx.register_cli_command({name!r}, help="h", setup_fn=_setup, handler_fn=_run)
        """), encoding="utf-8")


@pytest.fixture
def bundled(tmp_path, monkeypatch):
    """Three bundled plugins declaring ``alpha``, ``beta`` and ``broken`` (its parser setup raises); the markers dir."""
    root, markers = tmp_path / "bundled", tmp_path / "markers"
    root.mkdir()
    markers.mkdir()
    for name in ("alpha", "beta"):
        _write_plugin(root, name, markers)
    _write_plugin(root, "broken", markers, broken=True)
    monkeypatch.setattr(plugins_mod, "get_bundled_plugins_dir", lambda: root)
    monkeypatch.delenv(declared_parser_mod.DISABLE_ENV, raising=False)
    plugins_mod._reset_plugin_managers_for_tests()
    yield markers
    plugins_mod._reset_plugin_managers_for_tests()


def _ask(argv, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["hermes", *argv])
    return declared_parser_mod.declared_command_parser(main_mod._BUILTIN_SUBCOMMANDS)


def test_a_declared_command_gets_a_parser_holding_only_itself(bundled, monkeypatch):
    """KILLING MUTATION: return None at the head of ``declared_command_parser`` -> no parser for ``alpha``, red."""
    built = _ask(["alpha", "--alpha-flag"], monkeypatch)

    assert built is not None
    parser, subparsers = built
    assert set(subparsers.choices) == {"chat", "alpha"}, "the top-level parser's own chat, and the command argv names"
    assert sorted(p.name for p in bundled.iterdir()) == ["alpha.registered"], "only alpha's plugin was imported"
    args = main_mod._parse_cli_args(parser, subparsers, ["alpha", "--alpha-flag"])
    assert args.command == "alpha" and args.alpha_flag is True and args.func(args) == 0


@pytest.mark.parametrize("argv", [[], ["doctor"], ["config", "alpha"], ["no-such-command-s2p"], ["broken"]],
                         ids=["no command", "a built-in", "a word after a built-in", "nothing declares it",
                              "its parser setup raises"])
def test_any_other_argv_answers_none_so_the_whole_tree_is_built(bundled, monkeypatch, caplog, argv):
    """KILLING MUTATIONS: drop the ``declared is None`` arm -> ``no-such-command-s2p`` is reported as a plugin that
    failed to attach, red; drop the attach guard -> ``broken`` raises, red. (The built-in arm: the next test.)"""
    with caplog.at_level("WARNING", logger=declared_parser_mod.__name__):
        assert _ask(argv, monkeypatch) is None
    assert [r.getMessage() for r in caplog.records] == (
        ["Plugin CLI command 'broken' failed to attach"] if argv == ["broken"] else [])
    # Positive control: the same fixture and the same call DO answer a parser for a declared command.
    assert _ask(["alpha"], monkeypatch) is not None


def test_a_built_in_first_word_never_reads_a_manifest(bundled, monkeypatch):
    """KILLING MUTATION: drop the ``args[0] in builtins`` arm -> the scan runs for ``doctor``, red."""
    scans = []
    real = plugins_mod.discover_declared_cli_commands
    monkeypatch.setattr(plugins_mod, "discover_declared_cli_commands", lambda: scans.append(1) or real())

    assert _ask(["doctor"], monkeypatch) is None and scans == []
    assert _ask(["alpha"], monkeypatch) is not None and scans == [1], "positive control: a declared command scans"


def test_the_switch_turns_it_off(bundled, monkeypatch):
    """KILLING MUTATION: drop the ``DISABLE_ENV`` check -> a parser comes back with the switch set, red."""
    monkeypatch.setenv(declared_parser_mod.DISABLE_ENV, "1")
    assert _ask(["alpha"], monkeypatch) is None
    monkeypatch.setenv(declared_parser_mod.DISABLE_ENV, "0")
    assert _ask(["alpha"], monkeypatch) is not None


def test_main_runs_a_declared_command_without_building_the_whole_tree(bundled, monkeypatch):
    """The seam in ``hermes_cli/main.py::main``. KILLING MUTATION: restore ``parser, subparsers =
    _build_cli_parser()`` there -> the whole tree is built for ``hermes alpha``, red."""
    full = []
    real_build = main_mod._build_cli_parser
    monkeypatch.setattr(main_mod, "_build_cli_parser", lambda: full.append(1) or real_build())
    monkeypatch.setattr(sys, "argv", ["hermes", "alpha", "--alpha-flag"])

    main_mod.main()

    assert full == [], "main() built every command's parser for a declared plugin command"
    assert sorted(p.name for p in bundled.iterdir()) == ["alpha.ran", "alpha.registered"]
    # Positive control: the same counter DOES see the whole tree built when the switch is off.
    monkeypatch.setenv(declared_parser_mod.DISABLE_ENV, "1")
    plugins_mod._reset_plugin_managers_for_tests()
    main_mod.main()
    assert full == [1]
