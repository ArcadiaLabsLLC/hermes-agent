"""The two Wave 0 gates that read something other than the census: git history and the live harness.

Split from ``scripts/god_file_probe.py`` (whose population, parse cache and git
helper it imports) so the probe stays under the 800-code-line ceiling it
enforces. W0-G2 reads first-parent history after the Wave 0 landing; W0-G4
reads the runtime ``hermes_cli.harness`` module. Gates:
``tests/tooling/test_refactor_stays_downstream.py`` and
``tests/tooling/test_harness_namespace_is_thin.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.god_file_probe import ROOT, _git, _tree, fork_production_files


# ── W0-G2: the upstream fence on refactor commits ───────────────────────────

FENCE_ANCHOR_SUBJECT = "test(tooling): W0 —"
REFACTOR_PREFIX = "refactor("


def fence_anchor(root: Path = ROOT) -> str | None:
    """The first-parent Wave 0 landing commit: the fence reads history after it."""
    shas = _git(root, "log", "--first-parent", "--format=%H", "--fixed-strings", f"--grep={FENCE_ANCHOR_SUBJECT}", "HEAD")
    for sha in shas.split():
        if _git(root, "log", "-1", "--format=%s", sha).startswith(FENCE_ANCHOR_SUBJECT):
            return sha
    return None


def fence_violations(root: Path, upstream: frozenset[str], base: str) -> list[str]:
    """Every upstream path a first-parent ``refactor(`` commit after ``base`` changed.

    First-parent, because an upstream merge's second parent carries upstream's
    own ``refactor(...)`` commits, which are not the fork's.
    """
    out = []
    for line in _git(root, "log", "--first-parent", "--format=%H %s", f"{base}..HEAD").splitlines():
        sha, _, subject = line.partition(" ")
        if not subject.startswith(REFACTOR_PREFIX):
            continue
        touched = _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-m", "--first-parent", sha).split()
        out += [f"{sha[:10]} {subject!r} touches upstream {path}" for path in sorted(set(touched) & upstream)]
    return out


# ── W0-G4: the thin harness namespace ───────────────────────────────────────

HARNESS_MODULE = "hermes_cli.harness"
#: downstream-god-file-refactor.md §0.4: the names production imports FROM the harness.
HARNESS_ALLOWLIST = frozenset(
    {
        "build_parser",
        "emit_harness_error",
        "_cmd_characters_list",
        "_cmd_characters_status",
        "_cmd_characters_sprite",
        "_cmd_characters_thumb",
    }
)


def is_repo_module(name: str | None, root: Path = ROOT) -> bool:
    if not name:
        return False
    stem = root / name.replace(".", "/")
    return stem.with_suffix(".py").is_file() or (stem / "__init__.py").is_file()


def parser_func_targets(parser) -> list[object]:
    """Every ``func`` default in an argparse tree, walked through its subparsers."""
    import argparse

    found: list[object] = []
    stack = [parser]
    while stack:
        current = stack.pop()
        target = current.get_default("func")
        if target is not None:
            found.append(target)
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                stack.extend(action.choices.values())
    return found


def borrowed_callables(module, func_targets: list[object]) -> list[str]:
    """Callables ``module`` binds that ANOTHER repo module defines, minus the allowlist
    and the ``func=`` targets that live in a ``hermes_cli.harness_parts`` module."""
    import types

    out = []
    for name, value in sorted(vars(module).items()):
        if name.startswith("__") or not callable(value) or isinstance(value, types.ModuleType):
            continue
        owner = getattr(value, "__module__", None)
        if owner == module.__name__ or not is_repo_module(owner) or name in HARNESS_ALLOWLIST:
            continue
        if any(value is t for t in func_targets) and str(owner).startswith("hermes_cli.harness_parts."):
            continue
        out.append(f"{name} (from {owner})")
    return out


def exec_sites(root: Path = ROOT) -> list[str]:
    """Every ``exec(...)`` call in a fork file under ``hermes_cli/``."""
    sites = []
    for path in fork_production_files(root):
        if not path.startswith("hermes_cli/"):
            continue
        tree = _tree(root, path)
        for node in ast.walk(tree) if tree is not None else ():
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "exec":
                sites.append(f"{path}:{node.lineno}")
    return sites
