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

And every ``patch_where_bound(monkeypatch, <module expr>, "<name>", …)`` site
(lane W3-D). The helper patches ``<name>`` in the module, its submodules and
every loaded fork module that bound the same object under the SAME name, so
``silent_readers`` is the wrong question for it — those it reaches. What it
cannot reach is a module-scope ``from <that module, a submodule, or its
origin> import <name> as <other>``: the reader looks up ``<other>``, the helper
rebinds ``<name>``. That aliased binder is the site
(``unreachable_readers``).

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

import pytest

from scripts import god_file_probe as probe

FIXTURE = probe.FIXTURES / "silent_package_patches_grandfathered.json"
_SETATTR = re.compile(r"monkeypatch\.setattr\(")
_HELPER = re.compile(r"patch_where_bound\(")
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

    def aliased_bindings(self, dotted: str):
        """``(source module, name)`` for every module-scope ``from … import name as other``."""
        tree = self.tree(dotted)
        for node in tree.body if tree else ():
            if isinstance(node, ast.ImportFrom):
                source = _absolute(node.module or "", node.level, dotted, self.is_package(dotted))
                for alias in node.names:
                    if alias.asname and alias.asname != alias.name:
                        yield source, alias.name

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


def helper_sites(tree: ast.Module, modules: ForkModules) -> set[tuple[str, str]]:
    """``(module, name)`` for every ``patch_where_bound(monkeypatch, <module>, "<name>", …)``."""
    aliases = _test_aliases(tree, modules)
    sites: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        func = node.func if isinstance(node, ast.Call) else None
        called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if called != "patch_where_bound" or len(node.args) < 3:
            continue
        module, name = _expr_module(node.args[1], aliases), node.args[2]
        if module in modules.paths and isinstance(name, ast.Constant) and isinstance(name.value, str):
            sites.add((module, name.value))
    return sites


def unreachable_readers(modules: ForkModules, module: str, name: str) -> list[str]:
    """Fork modules binding *name* under an ALIAS from *module*, a submodule of it, or
    the module *module* imports it from — the readers ``patch_where_bound`` cannot rebind."""
    sources = {module} | {source for source, bound, _ in modules.bindings(module) if bound == name}
    return sorted(
        {
            dotted
            for dotted in modules.paths
            for source, bound in modules.aliased_bindings(dotted)
            if bound == name and (source in sources or source.startswith(module + "."))
        }
    )


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


#: The whole-tree walk is ~13-15 s and lands in whichever ROOT test runs first
#: in the process; every other ROOT test reads this cache. Pinned by
#: ``test_the_census_is_walked_once_per_tree``. The walk is budgeted by the
#: ``_WALK_BUDGET`` mark below, never by the 30 s ``addopts`` default: under
#: load the first caller overran that default in the round-2 tooling run.
@functools.lru_cache(maxsize=None)
def _census(root: Path) -> frozenset[str]:
    return frozenset(silent_package_patches(root))


_WALK_BUDGET = pytest.mark.timeout(120)


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
    aliased = {bound for dotted in modules.paths for _, bound in modules.aliased_bindings(dotted)}
    live: set[str] = set()
    for path in sorted((root / "tests").rglob("*.py")):
        if "fixtures" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        calls = [text[m.end() : m.end() + 240] for m in _SETATTR.finditer(text)]
        helper_calls = [text[m.end() : m.end() + 240] for m in _HELPER.finditer(text)]
        setattr_hot = any(hot.intersection(_IDENT.findall(call)) for call in calls)
        helper_hot = any(aliased.intersection(_IDENT.findall(call)) for call in helper_calls)
        if not (setattr_hot or helper_hot):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        for module, name in patch_sites(tree, modules) if setattr_hot else ():
            if silent_readers(modules, module, name):
                live.add(f"{rel}::{module}:{name}")
        for module, name in helper_sites(tree, modules) if helper_hot else ():
            if unreachable_readers(modules, module, name):
                live.add(f"{rel}::{module}:{name}")
    return live


def _fixture() -> set[str]:
    return set(json.loads(FIXTURE.read_text(encoding="utf-8"))["sites"])


@_WALK_BUDGET
def test_no_new_silent_package_patch():
    drift = probe.compare_sets("silent package patches", set(_census(probe.ROOT)), _fixture())
    assert not drift.new, (
        "these monkeypatches rebind a PACKAGE attribute that other fork modules bound by import — "
        "patch the module that looks the name up:\n" + drift.render()
    )


@_WALK_BUDGET
def test_a_fixed_site_loses_its_row():
    drift = probe.compare_sets("silent package patches", set(_census(probe.ROOT)), _fixture())
    assert not drift.stale, "delete these rows — the site is gone:\n" + drift.render()


@_WALK_BUDGET
def test_the_census_is_walked_once_per_tree(tmp_path, monkeypatch):
    """One walk per tree per process, and never another tree's answer.

    Walks are counted at the walk itself (zero when an earlier test in the
    process already paid it); a cache that ignored its key would hand the
    planted tree the real tree's census.
    """
    walks: list[Path] = []
    walk = silent_package_patches

    def counted(root: Path = probe.ROOT) -> set[str]:
        walks.append(root)
        return walk(root)

    monkeypatch.setitem(globals(), "silent_package_patches", counted)
    _census(probe.ROOT)
    _census(probe.ROOT)
    assert len(walks) <= 1, f"the census walked {len(walks)} times in one process"
    pkg = tmp_path / "agent_runtime" / "splitpkg"
    pkg.mkdir(parents=True)
    (tmp_path / "agent_runtime" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("from .impl import emit\n", encoding="utf-8")
    (pkg / "impl.py").write_text("def emit():\n    return 1\n", encoding="utf-8")
    (pkg / "user.py").write_text("from .impl import emit\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(
        "from agent_runtime import splitpkg\n"
        "def test_a(monkeypatch):\n"
        "    monkeypatch.setattr(splitpkg, 'emit', lambda: 2)\n",
        encoding="utf-8",
    )
    files = ["agent_runtime/__init__.py", *(f"agent_runtime/splitpkg/{f}" for f in ("__init__.py", "impl.py", "user.py"))]
    monkeypatch.setattr(probe, "fork_production_files", lambda root, *a, **k: list(files))
    assert _census(tmp_path) == {"tests/test_x.py::agent_runtime.splitpkg:emit"}


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


def test_the_walk_finds_a_helper_site_only_where_the_helper_cannot_reach(tmp_path, monkeypatch):
    """Positive control for the ``patch_where_bound`` arm (lane W3-D): an aliased
    module-scope binder is a site; a same-name binder (the helper rebinds it) is not."""
    pkg = tmp_path / "agent_runtime" / "splitpkg"
    pkg.mkdir(parents=True)
    (tmp_path / "agent_runtime" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "__init__.py").write_text("from .impl import emit\n", encoding="utf-8")
    (pkg / "impl.py").write_text("def emit():\n    return 1\n", encoding="utf-8")
    reader = tmp_path / "agent_runtime" / "reader.py"
    reader.write_text("from agent_runtime.splitpkg import emit as _emit\n\ndef run():\n    return _emit()\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_y.py").write_text(
        "from tests._downstream.split_package_source import patch_where_bound\n"
        "from agent_runtime import splitpkg\n"
        "def test_b(monkeypatch):\n"
        "    patch_where_bound(monkeypatch, splitpkg, 'emit', lambda: 2)\n",
        encoding="utf-8",
    )
    files = ["agent_runtime/__init__.py", "agent_runtime/reader.py", *(f"agent_runtime/splitpkg/{f}" for f in ("__init__.py", "impl.py"))]
    monkeypatch.setattr(probe, "fork_production_files", lambda root, *a, **k: list(files))
    assert silent_package_patches(tmp_path) == {"tests/test_y.py::agent_runtime.splitpkg:emit"}
    assert unreachable_readers(ForkModules(tmp_path), "agent_runtime.splitpkg", "emit") == ["agent_runtime.reader"]
    # Negative control: the same reader binding the SAME name is reached by the helper.
    reader.write_text("from agent_runtime.splitpkg import emit\n\ndef run():\n    return emit()\n", encoding="utf-8")
    assert silent_package_patches(tmp_path) == set()


def test_patch_where_bound_reaches_a_reader_outside_the_package(monkeypatch):
    """The helper's lane W3-D widening, proven at runtime: ``agent_runtime.migrations``
    binds ``load_agent_runtime_config`` from ``agent_runtime.config`` at module scope,
    outside the package, and a helper stub on the package must reach it."""
    import agent_runtime.config as config
    import agent_runtime.migrations as migrations
    from tests._downstream.split_package_source import patch_where_bound

    assert migrations.load_agent_runtime_config is config.load_agent_runtime_config

    def stub(*_a, **_k):
        return None

    patch_where_bound(monkeypatch, config, "load_agent_runtime_config", stub)
    assert config.load_agent_runtime_config is stub
    assert migrations.load_agent_runtime_config is stub
