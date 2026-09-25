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
    import hermes_cli.harness as harness

    parser = argparse.ArgumentParser(prog="harness")
    harness.populate_parser(parser)
    stack, handlers = [parser], []
    while stack:
        current = stack.pop()
        func = current.get_default("func")
        if func is not None:
            handlers.append(func)
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                stack.extend(action.choices.values())
    from_parts = [f for f in handlers if getattr(f, "__module__", "").startswith("hermes_cli.harness_parts.")]
    assert from_parts, "no parser handler comes from a part module — the wiring moved"
    for func in from_parts:
        assert getattr(sys.modules[func.__module__], func.__name__) is func, func
