"""FH-ONE-HOST-TOOL-RESOLVER: the fork's own modules find git, node, uv and python in ONE place.

``agent_runtime/host_tools.py`` answers "which tool on this host"; a fork production module that
spells the lookup itself — ``which("git")`` through ANY binding (``shutil.which``, an inline
``import shutil`` inside a function, ``__import__("shutil").which``, a ``from shutil import which``
alias), or a bare ``["git", ...]`` argv — is refused here unless it is on the shrink-only baseline
``tests/fixtures/host_tool_lookups_baseline.json``. The baseline only shrinks: a fixed site must leave
it (the stale-row case), and a new one is never added (owner 2026-11-15, "Fix all 7 design flaws").

Why a fork test beside upstream's ``tests/test_managed_runtime_resolution.py``: that scan keys
``shutil.which`` on a module-level ``shutil`` binding, so ``__import__("shutil").which("git")`` left it
green (seen 2026-11-15, w1115e-h9, FH-RESOLUTION-SCAN-MISSES-AN-INLINE-SHUTIL-IMPORT), and it does not
cover git at all; it is an upstream file, edited only with the owner's words. This scan matches the
``which`` CALL by its argument, whatever object it hangs off, over the fork's files only
(``scripts/god_file_probe.py::fork_production_files``: tracked, not in the upstream manifest),
product modules only.

Reading source is the right tool here for the same reason the upstream scan gives: the property is
"no call site anywhere in the fork spells it this way", which no runtime seam can observe.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import god_file_probe as probe

pytestmark = pytest.mark.gate

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "tests" / "fixtures" / "host_tool_lookups_baseline.json"
RESOLVER = "agent_runtime/host_tools.py"
#: Product code only: ``scripts/`` and ``tests/`` are standalone developer tools and fixtures (the upstream
#: scan exempts them for the same reason), which spawn the developer's own git.
_OUT_OF_SCOPE = ("scripts/", "tests/")
#: The host tools the resolver answers for; a bare spelling of any of them elsewhere is a site.
HOST_TOOLS = frozenset({"git", "node", "npm", "npx", "pnpm", "uv", "python", "python3"})


def host_tool_sites(tree: ast.AST) -> set[tuple[str, str, str]]:
    """``(symbol, kind, tool)`` for every bare host-tool lookup in *tree*.

    ``bare_which``: a call named ``which`` (attribute or name, any receiver) whose first argument is a
    host tool. ``bare_argv``: a list literal whose FIRST element is a host tool's bare name (an argv;
    a tuple is a table row — ``("git", step_git)`` names a step, it spawns nothing).
    The symbol is the enclosing ``def`` / ``class`` path (``<module>`` at top level), so a line move
    inside a function keeps its baseline row.
    """
    sites: set[tuple[str, str, str]] = set()

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = (*scope, node.name)
        symbol = ".".join(scope) or "<module>"
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            first = node.args[0]
            if name == "which" and isinstance(first, ast.Constant) and first.value in HOST_TOOLS:
                sites.add((symbol, "bare_which", first.value))
        if isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant) and first.value in HOST_TOOLS:
                sites.add((symbol, "bare_argv", first.value))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, ())
    return sites


def _live_sites() -> set[tuple[str, str, str, str]]:
    found: set[tuple[str, str, str, str]] = set()
    for path in probe.fork_production_files(REPO_ROOT):
        if path == RESOLVER or path.startswith(_OUT_OF_SCOPE):
            continue
        tree = probe._tree(REPO_ROOT, path)
        if tree is None:
            continue
        found |= {(path, symbol, kind, tool) for symbol, kind, tool in host_tool_sites(tree)}
    return found


def _baseline() -> set[tuple[str, str, str, str]]:
    rows = json.loads(BASELINE.read_text(encoding="utf-8"))["sites"]
    return {(row["path"], row["symbol"], row["kind"], row["tool"]) for row in rows}


def _render(sites: set[tuple[str, str, str, str]]) -> str:
    return "\n".join(f"  {path}::{symbol} ({kind} {tool})" for path, symbol, kind, tool in sorted(sites))


@pytest.fixture(scope="module")
def live() -> set[tuple[str, str, str, str]]:
    return _live_sites()


def test_no_new_bare_host_tool_lookup_in_fork_modules(live):
    new = live - _baseline()
    assert not new, (
        "A fork module looks up a host tool itself:\n" + _render(new)
        + "\nAsk agent_runtime.host_tools instead (git_command / git_resolution / git_runs / node_executable);"
        " the baseline is shrink-only and is never added to."
    )


def test_the_baseline_only_shrinks(live):
    stale = _baseline() - live
    assert not stale, "These sites moved onto the resolver; remove their baseline rows:\n" + _render(stale)


@pytest.mark.parametrize(
    "planted",
    [
        'import shutil\nshutil.which("git")\n',
        'def f():\n    import shutil\n    return shutil.which("git")\n',
        'def f():\n    return __import__("shutil").which("git")\n',
        'from shutil import which as w\nw.__call__\nwhich("node")\n',
        'import subprocess\nsubprocess.run(["git", "status"])\n',
    ],
)
def test_every_spelling_of_a_bare_lookup_is_a_site(planted):
    """The plants the upstream scan misses (an inline import, ``__import__``) are sites here too."""
    assert host_tool_sites(ast.parse(planted))


def test_a_lookup_through_the_resolver_is_not_a_site():
    planted = (
        "from agent_runtime.host_tools import git_command\n"
        "import subprocess\n"
        'subprocess.run([git_command(), "status"])\n'
        'shutil.which("llama-server")\n'
    )
    assert host_tool_sites(ast.parse(planted)) == set()
