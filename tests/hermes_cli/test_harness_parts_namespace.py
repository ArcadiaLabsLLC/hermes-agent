"""The ``hermes_cli/harness_parts/*.py`` command parts are real modules.

Until lane H1 (2026-09-24) ``hermes_cli/harness.py`` exec'd each part into its
own globals, and this file rebuilt that shared namespace to catch shadowing and
unresolvable free names. Each part now imports what it reads and resolves names
in its own globals, so those two failure modes are gone by construction: ruff's
F821 (no per-file ignore for ``harness_parts/``) holds that every free name is
bound, and W0-G4 (``tests/tooling/test_harness_namespace_is_thin.py``) holds
that harness.py neither execs a part nor re-exports one.

What is left to pin is positive: every part on disk imports as a module, binds
every name its ``__all__`` declares, and the parser's handlers are those
modules' own functions.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

import pytest
from hermes_cli.harness_parts import parser as harness_parser
from hermes_cli.harness_parts.parser import lazy

PARTS_DIR = Path(__file__).resolve().parents[2] / "hermes_cli" / "harness_parts"
PART_MODULES = tuple(
    sorted(
        "hermes_cli.harness_parts."
        + p.relative_to(PARTS_DIR).with_suffix("").as_posix().replace("/", ".").removesuffix(".__init__")
        for p in PARTS_DIR.rglob("*.py")
    )
)


@pytest.mark.parametrize("dotted", PART_MODULES)
def test_every_part_is_an_importable_module_that_binds_its_all(dotted: str) -> None:
    module = importlib.import_module(dotted)
    declared = getattr(module, "__all__", None)
    if declared is None:
        pytest.skip(f"{dotted} declares no __all__ yet (not opened by lane H1)")
    missing = [name for name in declared if not hasattr(module, name)]
    assert not missing, f"{dotted}.__all__ names unbound symbols: {missing}"


def test_every_parser_handler_from_a_part_is_that_modules_own_function() -> None:

    parser = argparse.ArgumentParser(prog="harness")
    harness_parser.populate_parser(parser)
    stack, handlers = [parser], []
    while stack:
        current = stack.pop()
        func = current.get_default("func")
        if func is not None:
            handlers.append(func)
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                stack.extend(action.choices.values())
            elif isinstance(action.type, lazy.LazyHandler):
                handlers.append(action.type)
    # The tree binds handlers BY NAME (``parser/lazy.py``), so a misspelled one no
    # longer fails at import: resolving every binding is what proves each names a
    # real function of a real module.
    assert sum(isinstance(f, lazy.LazyHandler) for f in handlers) > 100, "the tree stopped binding by name"
    bound = [lazy.resolve_lazy(f) for f in handlers]
    from_parts = [f for f in bound if getattr(f, "__module__", "").startswith("hermes_cli.harness_parts.")]
    assert from_parts, "no parser handler comes from a part module — the wiring moved"
    for func in from_parts:
        assert getattr(sys.modules[func.__module__], func.__name__) is func, func


def test_building_the_tree_imports_no_handler_and_parsing_imports_only_the_chosen_one() -> None:
    """The lazy binding's point, asked of the RUNTIME in a fresh interpreter: building
    the tree imports no handler module, and parsing ``persona list`` imports that
    verb's module and not another verb's, and hands back the module's own function."""

    import subprocess

    probe = (
        "import argparse, sys\n"
        "from hermes_cli.harness_parts import parser as tree\n"
        "root = argparse.ArgumentParser(prog='hermes')\n"
        "tree.build_parser(root.add_subparsers(dest='command'))\n"
        "built = set(sys.modules)\n"
        "args = root.parse_args(['harness', 'persona', 'list', '--json'])\n"
        "watch = ('hermes_cli.harness_parts.persona.inspect_commands',"
        " 'hermes_cli.harness_parts.runtime_commands', 'agent_runtime.harness_doctor')\n"
        "print(sorted(m for m in watch if m in built), sorted(m for m in watch if m in sys.modules),"
        " args.func.__module__)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == (
        "[] ['hermes_cli.harness_parts.persona.inspect_commands'] "
        "hermes_cli.harness_parts.persona.inspect_commands"
    ), out
