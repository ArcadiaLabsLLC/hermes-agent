"""A monkeypatch on a PACKAGE attribute must reach a reader — no new silent package patches.

Fork-hygiene row (lane B2, 2026-09-25): a package split leaves the package
``__init__`` re-exporting a name its submodules bound by ``from … import`` at
their own module scope. ``monkeypatch.setattr(<package>, "<name>", …)`` then
rebinds only the package attribute; every submodule that bound the name keeps
the original, and the test passes whether or not its seam took. Three lanes hit
it on 2026-09-25 (R1's stream-fixture generator, 2B-A, B2).

What this gate walks (a NEGATIVE guarantee — "no new site like this is
written" — so a source walk is the right instrument and over-approximation is
the safe direction):

* every ``monkeypatch.setattr`` call in ``tests/``, in both spellings —
  ``setattr(<module expr>, "<name>", …)`` (the expression resolved through the
  test file's own imports) and ``setattr("<dotted.module>.<name>", …)``;
* kept when the patched module is a fork PACKAGE (``__init__.py`` of a fork
  production file, ``probe.fork_production_files``) that does NOT define
  ``<name>`` itself but binds it by import (a re-export);
* a SITE when some other fork module binds ``<name>`` by import from the
  package or from the module the package re-exports it from — at module scope
  (either source), or inside a function from the origin (a function-level
  ``from <package> import <name>`` reads the patched attribute, so it is a
  reader the patch reaches and is not counted).

Baseline: ``tests/fixtures/silent_package_patches_grandfathered.json`` — the
sites on the day the gate landed, shrink-only. A fixed site loses its row; a
new one is red. The fix for a site is to patch the module that LOOKS THE NAME
UP (the package map's own rule), never to add a row.
"""

from __future__ import annotations

import ast
import functools
import json
import re
import warnings
from pathlib import Path

from scripts import god_file_probe as probe

FIXTURE = probe.FIXTURES / "silent_package_patches_grandfathered.json"
_SETATTR = re.compile(r"monkeypatch\.setattr\(")
_IDENT = re.compile(r"[A-Za-z_]\w*")


def _parse(path: Path) -> ast.Module | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None


def _absolute(module: str, level: int, importer: str, is_package: bool) -> str:
    """Resolve a (possibly relative) ``from`` import to a dotted module name."""
    if not level:
        return module
    base = importer.split(".")
    base = base if is_package else base[:-1]
    base = base[: len(base) - (level - 1)] if level > 1 else base
    return ".".join(base + ([module] if module else []))


class ForkModules:
    """The fork's production modules, their top-level definitions and their by-name imports."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.paths: dict[str, str] = {}
        for path in probe.fork_production_files(root):
            if path.endswith(".py"):
                self.paths[probe.module_name(path)] = path
        self._trees: dict[str, ast.Module | None] = {}
        self._by_name: dict[str, list[tuple[str, str, bool]]] | None = None

    def tree(self, dotted: str) -> ast.Module | None:
        if dotted not in self._trees:
            path = self.paths.get(dotted)
            self._trees[dotted] = _parse(self.root / path) if path else None
        return self._trees[dotted]

    def is_package(self, dotted: str) -> bool:
        return self.paths.get(dotted, "").endswith("__init__.py")

    def defines(self, dotted: str, name: str) -> bool:
        tree = self.tree(dotted)
        for node in tree.body if tree else ():
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
                return True
            targets = node.targets if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and any(
                isinstance(t, ast.Name) and t.id == name for t in targets
            ):
                return True
        return False

    def bindings(self, dotted: str):
        """``(source module, name, module_scope)`` for every ``from … import`` in *dotted*."""
        tree = self.tree(dotted)
        if tree is None:
            return
        top = set(map(id, tree.body))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                source = _absolute(node.module or "", node.level, dotted, self.is_package(dotted))
                for alias in node.names:
                    yield source, alias.name, id(node) in top


    def binders(self, name: str) -> list[tuple[str, str, bool]]:
        """``(module, source, module_scope)`` for every fork module binding *name* by import."""
        if self._by_name is None:
            self._by_name = {}
            for dotted in self.paths:
                for source, bound, module_scope in self.bindings(dotted):
                    self._by_name.setdefault(bound, []).append((dotted, source, module_scope))
        return self._by_name.get(name, [])


def _test_aliases(tree: ast.Module, modules: ForkModules) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    aliases.setdefault(head, head)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                dotted = f"{node.module}.{alias.name}"
                if dotted in modules.paths:
                    aliases[alias.asname or alias.name] = dotted
    return aliases


def _expr_module(node: ast.AST, aliases: dict[str, str]) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or node.id not in aliases:
        return None
    return ".".join([aliases[node.id], *reversed(parts)])


def patch_sites(tree: ast.Module, modules: ForkModules) -> set[tuple[str, str]]:
    """``(module, name)`` for every ``monkeypatch.setattr`` whose target resolves to a fork module."""
    aliases = _test_aliases(tree, modules)
    sites: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "setattr"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "monkeypatch"
            and node.args
        ):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str) and "." in first.value:
            module, _, name = first.value.rpartition(".")
        elif len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
            module, name = _expr_module(first, aliases) or "", node.args[1].value
        else:
            continue
        if module in modules.paths:
            sites.add((module, name))
    return sites


def silent_readers(modules: ForkModules, package: str, name: str) -> list[str]:
    """Fork modules that bound *name* by import where a patch on *package* cannot reach them."""
    if not modules.is_package(package) or modules.defines(package, name):
        return []
    origins = {source for source, bound, _ in modules.bindings(package) if bound == name}
    if not origins:
        return []
    return sorted(
        {
            dotted
            for dotted, source, module_scope in modules.binders(name)
            if dotted != package and (source in origins or (source == package and module_scope))
        }
    )


@functools.lru_cache(maxsize=None)
def _census(root: Path) -> frozenset[str]:
    return frozenset(silent_package_patches(root))


def silent_package_patches(root: Path = probe.ROOT) -> set[str]:
    modules = ForkModules(root)
    # Only a name some package re-exports to a silent reader can make a site; a
    # test file naming none of them is not parsed (the walk's cost is the parse).
    hot = {
        bound
        for package in modules.paths
        if modules.is_package(package)
        for _, bound, _ in modules.bindings(package)
        if silent_readers(modules, package, bound)
    }
    live: set[str] = set()
    for path in sorted((root / "tests").rglob("*.py")):
        if "fixtures" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        calls = [text[m.end() : m.end() + 240] for m in _SETATTR.finditer(text)]
        if not any(hot.intersection(_IDENT.findall(call)) for call in calls):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        for module, name in patch_sites(tree, modules):
            if silent_readers(modules, module, name):
                live.add(f"{rel}::{module}:{name}")
    return live


def _fixture() -> set[str]:
    return set(json.loads(FIXTURE.read_text(encoding="utf-8"))["sites"])


def test_no_new_silent_package_patch():
    drift = probe.compare_sets("silent package patches", set(_census(probe.ROOT)), _fixture())
    assert not drift.new, (
        "these monkeypatches rebind a PACKAGE attribute that other fork modules bound by import — "
        "patch the module that looks the name up:\n" + drift.render()
    )


def test_a_fixed_site_loses_its_row():
    drift = probe.compare_sets("silent package patches", set(_census(probe.ROOT)), _fixture())
    assert not drift.stale, "delete these rows — the site is gone:\n" + drift.render()


def test_the_walk_finds_a_planted_silent_patch(tmp_path, monkeypatch):
    """Positive control: a real split package, one package-attribute patch, one reader it misses."""
    pkg = tmp_path / "agent_runtime" / "splitpkg"
    pkg.mkdir(parents=True)
    (tmp_path / "agent_runtime" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("from .impl import emit\n", encoding="utf-8")
    (pkg / "impl.py").write_text("def emit():\n    return 1\n", encoding="utf-8")
    (pkg / "user.py").write_text("from .impl import emit\n\ndef run():\n    return emit()\n", encoding="utf-8")
    (pkg / "lazy.py").write_text("def run():\n    from agent_runtime.splitpkg import emit\n    return emit()\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_x.py").write_text(
        "from agent_runtime import splitpkg\n"
        "def test_a(monkeypatch):\n"
        "    monkeypatch.setattr(splitpkg, 'emit', lambda: 2)\n"
        "    monkeypatch.setattr('agent_runtime.splitpkg.impl.emit', lambda: 3)\n",
        encoding="utf-8",
    )
    files = ["agent_runtime/__init__.py", *(f"agent_runtime/splitpkg/{f}" for f in ("__init__.py", "impl.py", "user.py", "lazy.py"))]
    monkeypatch.setattr(probe, "fork_production_files", lambda root, *a, **k: list(files))
    assert silent_package_patches(tmp_path) == {"tests/test_x.py::agent_runtime.splitpkg:emit"}
    assert silent_readers(ForkModules(tmp_path), "agent_runtime.splitpkg", "emit") == ["agent_runtime.splitpkg.user"]
    # Negative control: once the reader looks the name up through the package, the site is gone.
    (pkg / "user.py").write_text("from agent_runtime import splitpkg\n\ndef run():\n    return splitpkg.emit()\n", encoding="utf-8")
    assert silent_package_patches(tmp_path) == set()
