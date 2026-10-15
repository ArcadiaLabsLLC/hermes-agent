"""Run bounded, explicit mutation claims that intersect changed production lines.

**This gate REWRITES SOURCE FILES IN PLACE while it runs** -- the full contract,
the census and the budget doctrine are the docstring of
``scripts/mutation_check/__init__.py``, which is also the map of the package
this ENTRY runs. The entry keeps its path because CI
(``.github/workflows/fork-gates.yml``), ``scripts/unattended_suite_run.ps1``,
``CLAUDE.md`` and the gate's tests name it; it holds ``main`` and re-exports
the names those tests READ. A name a test PATCHES is patched on the module
that reads it (``scripts.mutation_check.run`` / ``.selection`` / ``.anchor``).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if not __package__:  # run as a script: ``scripts/`` is sys.path[0], the repo root is not
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.mutation_check.anchor import _anchor_claim, _qualified_definitions  # noqa: E402
from scripts.mutation_check.run import _acquire_gate_lock, _claims_for, run  # noqa: E402
from scripts.mutation_check.schema import (  # noqa: E402
    DEFAULT_CLAIMS,
    DEFAULT_EXEMPTIONS,
    DEFAULT_WALL_BUDGET_SECONDS,
    DERIVED_AT_KEY,
    EXIT_REFUSED,
    HUNK,
    LOCK_PATH,
    REPO_ROOT,
)
from scripts.mutation_check.selection import (  # noqa: E402
    _changed_lines,
    _changed_sources,
    _commits_since_derivation,
)

__layer__ = "wiring"

__all__ = [
    "DEFAULT_CLAIMS",
    "DERIVED_AT_KEY",
    "HUNK",
    "LOCK_PATH",
    "REPO_ROOT",
    "_acquire_gate_lock",
    "_anchor_claim",
    "_changed_lines",
    "_changed_sources",
    "_claims_for",
    "_commits_since_derivation",
    "_qualified_definitions",
    "main",
    "run",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        # Hand-wrapped, because RawDescriptionHelpFormatter is what keeps the
        # epilog's indented cap doctrine readable and it wraps nothing at all.
        description=(
            "Run bounded, explicit mutation claims that intersect changed\n"
            "production lines.\n"
            "\n"
            "THIS GATE REWRITES SOURCE FILES IN PLACE while it runs. Never run\n"
            "pytest -- or anything else that reads the tree -- in the same\n"
            "worktree during a run: a concurrent test run reads sabotaged source\n"
            "and reds tests that pass in isolation, which at the console is\n"
            "indistinguishable from a real defect. A second MUTATING run against\n"
            "the same tree is refused (.mutation_gate.lock); a concurrent pytest\n"
            "cannot be seen from here."
        ),
        epilog=(
            "budget doctrine (replaced the candidate cap, 2026-09-04):\n"
            "  the bound is WALL CLOCK. --wall-budget-seconds defaults to 900\n"
            "  (fifteen minutes, the ceiling CI's own job timeout already\n"
            "  enforced). The candidate COUNT is reported on every run and\n"
            "  never asserted: symbol-overlap selection raises it by design and\n"
            "  a push-shaped base collapses it, and neither moves the runtime\n"
            "  the bound exists to protect. A long multi-stage LANDING run\n"
            "  passes its own budget explicitly, the way CI does, so the\n"
            "  enforced number is readable beside the command enforcing it:\n"
            "    python scripts/changed_line_mutation_check.py --base <sha> --wall-budget-seconds 1800\n"
            "  See tool/test_quality/README.md."
        ),
    )
    # Not `required=True` any more: `--claims-for` is an inventory question
    # about the registry, and there is no base to diff against when the answer
    # is wanted BEFORE the rewrite that would produce one.
    parser.add_argument("--base")
    parser.add_argument("--claims", type=Path, default=DEFAULT_CLAIMS)
    parser.add_argument("--exemptions", type=Path, default=DEFAULT_EXEMPTIONS)
    parser.add_argument(
        "--wall-budget-seconds",
        type=float,
        default=DEFAULT_WALL_BUDGET_SECONDS,
        help=(
            "stop the run when it has spent N seconds of wall clock (default: "
            "%(default)s). Checked before the mutating phase and between "
            "claims, so an overrun stops with a report rather than being "
            "killed. The candidate count is reported, never asserted."
        ),
    )
    parser.add_argument("--list", action="store_true", dest="list_only")
    parser.add_argument(
        "--claims-for",
        metavar="SYMBOL|PATH|PATH::SYMBOL",
        help="list the claims anchored there and exit; a pre-flight, not a gate",
    )
    args = parser.parse_args(argv)
    if args.claims_for is not None:
        try:
            return _claims_for(args.claims.resolve(), args.claims_for)
        except RuntimeError as error:
            print(f"mutation-check configuration error: {error}", file=sys.stderr)
            return EXIT_REFUSED
    if args.base is None:
        parser.error("--base is required unless --claims-for is given")
    try:
        return run(
            args.base,
            args.claims.resolve(),
            args.exemptions.resolve(),
            args.wall_budget_seconds,
            args.list_only,
        )
    except RuntimeError as error:
        print(f"mutation-check configuration error: {error}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
