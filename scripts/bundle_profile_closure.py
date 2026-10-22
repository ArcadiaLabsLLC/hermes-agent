"""Import closure of a bundle profile: which third-party distributions its enabled features pull.

Static walk (``ast``), module-level AND function-level imports (plus
``importlib.import_module("literal")`` calls), from the profile manifest's
``packaging.roots``. The walk never follows an import into
``packaging.switched_off_modules``; a distribution reached only through those
is EXCLUDABLE. Over-approximation is the safe direction for "reached": a lazy
import counts, a ``try: import x`` counts.

A switched-off module that a kept module imports at MODULE level, unguarded, is
loaded anyway — it is reported as "pinned" and its module-level imports count
as reached, because the bundle cannot omit it without a seam. A guarded
module-level import (``try``/``except ImportError``) is a seam already.

What SHIPS is decided by the distribution's declaration in ``pyproject.toml``
(markers evaluated for the bundle target, win_amd64 / CPython 3.14):

* a ``[project].dependencies`` (base) distribution ships, unless the manifest
  lists it in ``packaging.omitted_distributions`` — refused unless every
  import site of it in the kept modules is guarded (``try``/``suppress``
  catching ``ImportError``), because base code may assume a base dependency;
* an optional-extra distribution ships only when the manifest names one of its
  extras in ``packaging.extras``. Extras are lazily installed in full Hermes,
  so their import sites already tolerate absence; the profile turns lazy
  installs off, so an unshipped extra is an unavailable feature, never a
  download;
* an undeclared distribution the walk reaches ships (and is listed, so it is
  seen);
* every shipped distribution's requirements ship with it.

A kept module's lazy import INTO a switched-off module is a runtime
ImportError if the bundle omits that module and the line runs; the unguarded
ones are listed (``unguarded_switched_off_imports``) so each is either behind
the feature's own switch or seamed.

Third-party import names map to distributions through the running
interpreter's ``importlib.metadata`` (run this under the venv you are
measuring), then ``uv.lock``. Sizes: installed distributions are the on-disk
bytes of their RECORD files (measured); the rest are uv.lock wheel bytes
(estimate, compressed).

Usage::

    python scripts/bundle_profile_closure.py --profile bundled-desktop --json out.json [--markdown out.md]
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata as md
import json
import re
import sys
import tomllib
import warnings
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.bundles.closure_platform import dead_for_target
from scripts.bundles.closure_probes import boot_tops, stand_in_answered
from scripts.bundles.closure_report import _mib, render_markdown

NATIVE_SUFFIXES = (".pyd", ".so", ".dll", ".dylib")
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
#: The repo's non-Python trees (the dashboard frontends, the website), skipped at the TOP LEVEL only:
#: skipped anywhere, ``web`` also hid ``plugins/web/`` — every web provider, and the
#: ``plugins.web.firecrawl.provider`` that ``tools.web_tools`` imports at module level.
_SKIP_TOP_DIRS = {"web", "website", "apps", "ui-tui"}

#: Imports a registry makes BY NAME, from a table the AST walk cannot read: importer -> targets.
#: The plugin context's ``register_<kind>_provider`` methods import their registry and base class
#: (``hermes_cli.plugins._SCOPED_PROVIDER_REGISTRARS``); the secret-source registry imports its
#: bundled sources (``agent.secret_sources.registry._BUILTIN_SOURCES``). A kept importer keeps its
#: targets — lazy edges, so a switched-off target is recorded like any lazy import into one.
#: ``tests/scripts/test_bundle_profile_closure.py`` holds this to the tables themselves, read at
#: run time.
DYNAMIC_IMPORTS: dict[str, tuple[str, ...]] = {
    "hermes_cli.plugins": (
        "agent.provider_access",
        "agent.image_gen_registry", "agent.image_gen_provider",
        "agent.video_gen_registry", "agent.video_gen_provider",
        "agent.web_search_registry", "agent.web_search_provider",
        "agent.browser_registry", "agent.browser_provider",
        "agent.terminal_env_registry", "agent.terminal_env_provider",
        "agent.secret_sources.registry", "agent.secret_sources.base",
        "agent.tts_registry", "agent.tts_provider",
        "agent.transcription_registry", "agent.transcription_provider",
        "agent.provider_access",
    ),
    "agent.secret_sources.registry": (
        "agent.secret_sources.bitwarden", "agent.secret_sources.onepassword", "agent.secret_sources.command",
    ),
}


def facade_exports() -> dict[str, dict[str, str]]:
    """PEP 562 facades: package -> {exported name: the module that defines it}.

    ``from pm import install_hint`` reads to the AST as an import of ``pm`` alone; the name
    resolves through ``pm.__getattr__`` to ``pm.extras``, so the walk must follow the facade's
    own table. Read from that table at run time (``pm`` is a light, lazy package), never copied.
    """
    import pm

    return {"pm": dict(pm._HOME)}


#: The bundle target: markers are evaluated for the interpreter the installer ships.
TARGET_ENV = {
    "sys_platform": "win32", "platform_system": "Windows", "platform_machine": "AMD64",
    "os_name": "nt", "python_version": "3.14", "python_full_version": "3.14.0",
    "implementation_name": "cpython", "platform_python_implementation": "CPython",
    "platform_release": "10", "extra": "",
}

#: Every target a profile may name in ``packaging.targets`` -> its marker environment. A profile
#: naming none is packaged for :data:`TARGET_ENV` (the desktop installer's interpreter). The phone
#: targets are CPython 3.14's own mobile platforms (``sys.platform`` ``android`` / ``ios``).
TARGETS = {
    "win_amd64": TARGET_ENV,
    "android_arm64": {**TARGET_ENV, "sys_platform": "android", "platform_system": "Android",
                      "platform_machine": "aarch64", "os_name": "posix", "platform_release": ""},
    "ios_arm64": {**TARGET_ENV, "sys_platform": "ios", "platform_system": "iOS",
                  "platform_machine": "arm64", "os_name": "posix", "platform_release": ""},
}

#: Import names whose distribution name is not derivable from the import name.
IMPORT_ALIASES = {
    "piper": "piper-tts", "PIL": "pillow", "faster_whisper": "faster-whisper", "acp": "agent-client-protocol",
    "azure": "azure-identity", "win32con": "pywin32", "win32file": "pywin32", "win32api": "pywin32",
    "ntsecuritycon": "pywin32", "win32event": "pywin32", "win32process": "pywin32", "pywintypes": "pywin32",
    "winpty": "pywinpty", "jwt": "pyjwt", "dotenv": "python-dotenv", "yaml": "pyyaml",
    "telegram": "python-telegram-bot", "discord": "discord-py", "google": "google-auth",
}

_GUARD_NAMES = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def module_index(root: Path = ROOT, plugins=()) -> dict[str, Path]:
    """Dotted first-party module name -> file.

    ``plugins`` names bundled plugin directories (``plugins/<dir>``). The plugin
    loader imports them by PATH, so a hyphenated directory (``eternia-harness``)
    has no import name; it is indexed as ``plugins.<dir with _>`` so the walk
    can follow its imports, relative ones included.
    """
    index: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if _SKIP_DIRS.intersection(rel.parts[:-1]) or (len(rel.parts) > 1 and rel.parts[0] in _SKIP_TOP_DIRS):
            continue
        parts = list(rel.with_suffix("").parts)
        if plugins and parts[0] == "plugins" and len(parts) > 2 and parts[1] in plugins:
            if {"tests", "test"}.intersection(parts[2:-1]):
                continue  # a plugin's own tests: the loader never imports them
            parts = [p.replace("-", "_") for p in parts]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts and all(p.isidentifier() for p in parts):
            index.setdefault(".".join(parts), path)
    return index


def plugin_roots(manifest) -> tuple[str, ...]:
    """Walk roots for the manifest's bundled plugin directories."""
    return tuple(f"plugins.{name.replace('-', '_')}" for name in getattr(manifest, "packaging_plugins", ()))


def profile_walk(manifest, index: dict[str, Path] | None = None, *,
                 parents: bool = False) -> tuple[Walk, dict[str, Path]]:
    """The profile's one walk: its roots plus its bundled plugins, never into switched-off modules."""
    index = index if index is not None else module_index(plugins=getattr(manifest, "packaging_plugins", ()))
    first_party = {m.split(".")[0] for m in index}
    roots = (*manifest.packaging_roots, *plugin_roots(manifest))
    return Walk(roots, manifest.switched_off_modules, index, first_party, parents=parents), index


def _catches_import_error(handler_type) -> bool:
    if handler_type is None:
        return True
    names = handler_type.elts if isinstance(handler_type, ast.Tuple) else [handler_type]
    return any(isinstance(n, (ast.Name, ast.Attribute)) and
               (n.id if isinstance(n, ast.Name) else n.attr) in _GUARD_NAMES for n in names)


def _suppresses_import_error(item: ast.withitem) -> bool:
    call = item.context_expr
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
    return name == "suppress" and any(_catches_import_error(arg) for arg in call.args)


def _guarded_ids(tree: ast.AST) -> set[int]:
    """ids of every node inside a ``try`` body / ``with suppress(...)`` that absorbs ImportError."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        absorbs = _ABSORBS_IMPORT_ERROR.get(type(node))
        if absorbs is not None and absorbs(node):
            for stmt in node.body:
                guarded.update(id(n) for n in ast.walk(stmt))
    return guarded


#: Statement kind -> whether its BODY may fail to import without it being a load that must succeed:
#: a ``try`` catching ImportError, a ``with suppress(ImportError)``, and ``if TYPE_CHECKING:`` (never
#: runs: an import there is an annotation, not a load).
_ABSORBS_IMPORT_ERROR = {
    ast.Try: lambda node: any(_catches_import_error(h.type) for h in node.handlers),
    ast.With: lambda node: any(_suppresses_import_error(i) for i in node.items),
    ast.AsyncWith: lambda node: any(_suppresses_import_error(i) for i in node.items),
    ast.If: lambda node: _is_type_checking(node.test),
}


def _is_type_checking(test: ast.expr) -> bool:
    """``TYPE_CHECKING`` / ``typing.TYPE_CHECKING`` — the constant that is False at run time."""
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


#: Calls whose first literal argument is a module they import: importlib's, and the
#: ``hermes harness`` parser's handlers bound by name (``hermes_cli/harness_parts/parser/lazy.py``).
_LITERAL_IMPORT_CALLS = frozenset({"import_module", "lazy_module"})


def _literal_import_module(node: ast.AST) -> str | None:
    """``import_module("x")`` / ``lazy_module("x")`` with a literal name -> ``"x"``."""
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    arg = node.args[0]
    if name in _LITERAL_IMPORT_CALLS and isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
            and not arg.value.startswith("."):
        return arg.value
    return None


#: Every file's imports, parsed once per process: ``(path, mtime_ns, size, module, is_pkg)`` -> rows.
#: The packager plans the core and every engine pack in one process and walks the same files many
#: times (the profile walk, the pinned modules' eager imports, the serve probe's table); each walk
#: reads this instead of re-parsing. A rewritten file has a new key, so an edit between walks is seen.
_IMPORTS_CACHE: dict[tuple, tuple] = {}
#: ``parses``: the ``ast.parse`` calls :func:`_imports` made (the cache's misses); ``walks``: the
#: :class:`Walk` objects built in this process. The packager's planning child reports both as its
#: progress, and a test counts the walks: the core plus N engine packs is ONE walk, never N + 1.
COUNTS = {"parses": 0, "walks": 0}


def _imports(path: Path, module: str, is_pkg: bool) -> tuple:
    """``(dotted, eager, guarded, lineno)`` for every import in the file; eager = at module level.

    Parsed once per process per file version (:data:`_IMPORTS_CACHE`)."""
    stat = path.stat()
    platform = tuple(TARGET_ENV.get(k) for k in ("os_name", "sys_platform", "platform_system"))
    key = (str(path), stat.st_mtime_ns, stat.st_size, module, is_pkg, platform)
    rows = _IMPORTS_CACHE.get(key)
    if rows is None:
        COUNTS["parses"] += 1
        rows = _IMPORTS_CACHE[key] = tuple(_parse_imports(path, module, is_pkg))
    return rows


def _parse_imports(path: Path, module: str, is_pkg: bool):
    """Yield :func:`_imports`'s rows from one parse of ``path``; an import a platform branch makes
    unreachable on :data:`TARGET_ENV` is not yielded."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return
    top_level = {id(n) for n in tree.body}
    for stmt in tree.body:
        if isinstance(stmt, (ast.If, ast.Try)):
            top_level.update(id(n) for n in ast.walk(stmt))
    guarded = _guarded_ids(tree)
    dead = dead_for_target(tree, TARGET_ENV)
    package = module if is_pkg else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if id(node) in dead:
            continue
        eager, safe, line = id(node) in top_level, id(node) in guarded, getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, eager, safe, line
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join([*anchor, base] if base else anchor)
            yield base, eager, safe, line
            for alias in node.names:
                yield f"{base}.{alias.name}", eager, safe, line
        elif (dynamic := _literal_import_module(node)) is not None:
            yield dynamic, False, safe, line


def _owner(dotted: str, index: dict[str, Path]) -> str | None:
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in index:
            return candidate
    return None


def _under(module: str, prefixes) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def _import_chain(module: str, parent: dict[str, str]) -> list[str]:
    """Root -> ... -> ``module``: the first import path the walk found."""
    chain = [module]
    while parent.get(chain[-1]):
        chain.append(parent[chain[-1]])
    return chain[::-1]


class Walk:
    """One closure walk: kept modules, third-party tops reached, and the edges into switched-off code."""

    def __init__(self, roots, pruned, index, first_party_tops, *, parents: bool = False):
        """``parents``: importing ``a.b.c`` runs ``a/__init__`` and ``a/b/__init__`` first, so a
        kept module's enclosing packages are reached too (at module level: their imports are
        eager). Off by default — the desktop closure's recorded figures were taken without it; the
        packaging step (``scripts/bundle_profile_package.py``) and the profile gate walk with it,
        because what they ship is what the bundle imports."""
        COUNTS["walks"] += 1
        self.kept: set[str] = set()
        self.tops: dict[str, list[str]] = {}
        self.pinned: set[str] = set()
        self.unguarded_into_pruned: list[dict] = []
        self.import_sites: dict[str, list[dict]] = {}
        facades = facade_exports()
        # A root prefix (``agent_runtime``) must not seed a switched-off module under it.
        queue = deque(m for m in index if _under(m, roots) and not _under(m, pruned))
        parent: dict[str, str] = {m: "" for m in queue}
        while queue:
            module = queue.popleft()
            if module in self.kept:
                continue
            self.kept.add(module)
            path = index[module]
            if parents:
                package = module.rpartition(".")[0]
                while package:
                    if package in index and package not in parent and not _under(package, pruned):
                        parent[package] = module
                        queue.append(package)
                    elif package in index and _under(package, pruned) and not _under(module, pruned):
                        self.pinned.add(package)
                    package = package.rpartition(".")[0]
            dynamic = ((target, False, False, 0) for target in DYNAMIC_IMPORTS.get(module, ()))
            for dotted, eager, guarded, line in (*_imports(path, module, path.name == "__init__.py"), *dynamic):
                owner = _owner(dotted, index)
                if owner in facades and dotted != owner:
                    target = facades[owner].get(dotted[len(owner) + 1:].partition(".")[0])
                    owner = target if target in index else owner
                if owner is None:
                    top = dotted.split(".")[0]
                    if top and top not in first_party_tops and top not in sys.stdlib_module_names:
                        self.tops.setdefault(top, _import_chain(module, parent))
                        self.import_sites.setdefault(top, []).append(
                            {"module": module, "line": line, "guarded": guarded, "eager": eager, "dotted": dotted})
                    continue
                if _under(owner, pruned):
                    if _under(module, pruned):
                        continue
                    if eager and not guarded:
                        self.pinned.add(owner)
                    elif not guarded:
                        self.unguarded_into_pruned.append({"module": module, "line": line, "target": owner})
                    continue
                if owner not in parent:
                    parent[owner] = module
                    queue.append(owner)


def walk(roots, pruned, index, first_party_tops):
    """-> (kept modules, third-party import tops, pinned switched-off modules)."""
    result = Walk(roots, pruned, index, first_party_tops)
    return result.kept, result.tops, result.pinned


def eager_tops(modules, index, first_party_tops) -> set[str]:
    tops = set()
    for module in modules:
        path = index[module]
        for dotted, eager, _guarded, _line in _imports(path, module, path.name == "__init__.py"):
            top = dotted.split(".")[0]
            if eager and _owner(dotted, index) is None and top not in first_party_tops \
                    and top not in sys.stdlib_module_names:
                tops.add(top)
    return tops


# -- declarations (pyproject) and the dependency graph ----------------------------------------------


def _req(raw: str):
    from packaging.requirements import Requirement

    return Requirement(raw)


def declared(path: Path = ROOT / "pyproject.toml", env: dict | None = None) -> tuple[set[str], dict[str, set[str]]]:
    """-> (base distribution names, extra -> distribution names), markers evaluated for the target."""
    project = tomllib.loads(path.read_text(encoding="utf-8-sig"))["project"]
    self_name = _norm(project["name"])
    env = TARGET_ENV if env is None else env

    def names(raws):
        out, refs = set(), set()
        for raw in raws:
            req = _req(raw)
            if req.marker is not None and not req.marker.evaluate(env):
                continue
            if _norm(req.name) == self_name:
                refs.update(req.extras)
            else:
                out.add(_norm(req.name))
        return out, refs

    base, _ = names(project.get("dependencies", []))
    raw_extras = {extra: names(reqs) for extra, reqs in project.get("optional-dependencies", {}).items()}
    extras = {}
    for extra in raw_extras:
        seen, stack, dists = set(), [extra], set()
        while stack:
            current = stack.pop()
            if current in seen or current not in raw_extras:
                continue
            seen.add(current)
            dists |= raw_extras[current][0]
            stack.extend(raw_extras[current][1])
        extras[extra] = dists
    return base, extras


def requested_extras(path: Path = ROOT / "pyproject.toml", env: dict | None = None) -> dict[str, set[str]]:
    """Base distribution -> the extras its declaration requests (``httpx[socks]`` -> {"socks"}).

    A requested extra's requirements ship with the distribution: ``httpx`` loads
    ``socksio`` only when a SOCKS proxy is configured, so no static import reaches it.
    """
    project = tomllib.loads(path.read_text(encoding="utf-8-sig"))["project"]
    env = TARGET_ENV if env is None else env
    out: dict[str, set[str]] = {}
    for raw in project.get("dependencies", []):
        req = _req(raw)
        if req.extras and (req.marker is None or req.marker.evaluate(env)):
            out.setdefault(_norm(req.name), set()).update(req.extras)
    return out


def declared_anywhere(path: Path = ROOT / "pyproject.toml") -> set[str]:
    """Every distribution ``[project]`` declares (base + extras), markers NOT evaluated."""
    project = tomllib.loads(path.read_text(encoding="utf-8-sig"))["project"]
    raws = [*project.get("dependencies", []), *(r for reqs in project.get("optional-dependencies", {}).values()
                                                 for r in reqs)]
    return {_norm(_req(raw).name) for raw in raws} - {_norm(project["name"])}


def _lock(path: Path = ROOT / "uv.lock") -> dict[str, dict]:
    return {_norm(p["name"]): p for p in tomllib.loads(path.read_text(encoding="utf-8-sig")).get("package", [])}


def _wheel_size(package: dict) -> int | None:
    """The Windows wheel's size from uv.lock (preferring cp314, cp312, abi3, then any)."""
    wheels = package.get("wheels", [])
    for tag in ("cp314-win_amd64", "cp312-win_amd64", "abi3-win_amd64", "none-win_amd64", "none-any"):
        for wheel in wheels:
            if wheel["url"].endswith(f"{tag}.whl") and wheel.get("size"):
                return wheel["size"]
    return None


class Graph:
    """Distribution facts: installed metadata first, uv.lock second."""

    def __init__(self, lock: dict[str, dict], extras: dict[str, set[str]] | None = None,
                 placeholders=(), env: dict | None = None):
        self.lock = lock
        #: the marker environment requirements are evaluated for (the bundle target)
        self.env = TARGET_ENV if env is None else env
        #: requirements a placeholder module stands in for: never followed, never shipped
        self.placeholders = {_norm(p) for p in placeholders}
        #: distribution -> extras a declaration requests; their requirements are followed too
        self.extras = extras or {}
        self.installed = {_norm(d.metadata["Name"]): d for d in md.distributions()}
        self.mapping = md.packages_distributions()

    def dist_for_top(self, top: str) -> str | None:
        names = self.mapping.get(top)
        if names:
            return _norm(names[0])
        for candidate in (IMPORT_ALIASES.get(top), top):
            if candidate and (_norm(candidate) in self.installed or _norm(candidate) in self.lock):
                return _norm(candidate)
        return None

    def dist_for_import(self, dotted: str) -> str | None:
        """The distribution providing the import ``dotted``. A namespace top that several
        distributions share (``azure``: azure-core, azure-identity) resolves by its next
        component — the distribution whose files hold ``azure/identity`` — never by the
        mapping's first entry, which shipped azure-core alone for ``import azure.identity``."""
        top, _, rest = dotted.partition(".")
        names = self.mapping.get(top) or []
        if len(set(names)) > 1 and rest:
            sub = rest.partition(".")[0]
            for name in names:
                if sub in self._subpackages(top, name):
                    return _norm(name)
        return self.dist_for_top(top)

    def dists_for_sites(self, top: str, sites) -> set[str]:
        """Every distribution the import ``sites`` of ``top`` reach (one per site's dotted
        name); ``top`` alone when no site names it (a pinned module's eager import)."""
        dists = {self.dist_for_import(site["dotted"]) for site in sites if site.get("dotted")}             or {self.dist_for_top(top)}
        return {d for d in dists if d}

    def _subpackages(self, top: str, name: str) -> set[str]:
        """The names directly under ``top/`` among distribution ``name``'s installed files."""
        cache = self.__dict__.setdefault("_subpackage_cache", {})
        key = (top, _norm(name))
        if key not in cache:
            dist = self.installed.get(_norm(name))
            subs = set()
            for file in (dist.files or []) if dist is not None else []:
                parts = str(file).replace("\\", "/").split("/")
                if len(parts) > 1 and parts[0] == top:
                    subs.add(parts[1].split(".")[0])
            cache[key] = subs
        return cache[key]

    def requires(self, name: str) -> list[str]:
        envs = [self.env, *({**self.env, "extra": e} for e in sorted(self.extras.get(name, ())))]
        dist = self.installed.get(name)
        if dist is not None:
            out = []
            for raw in dist.requires or []:
                req = _req(raw)
                if req.marker is None or any(req.marker.evaluate(env) for env in envs):
                    out.append(_norm(req.name))
            return out
        from packaging.markers import Marker

        out = []
        lock = self.lock.get(name, {})
        deps = [(dep, self.env) for dep in lock.get("dependencies", [])]
        for extra in sorted(self.extras.get(name, ())):
            deps += [(dep, self.env) for dep in lock.get("optional-dependencies", {}).get(extra, [])]
        for dep, env in deps:
            marker = dep.get("marker")
            if marker is None or Marker(marker).evaluate(env):
                out.append(_norm(dep["name"]))
        return out

    def closure(self, roots) -> set[str]:
        found, queue = set(), deque(roots)
        while queue:
            name = queue.popleft()
            if name in found or name in self.placeholders:
                continue
            found.add(name)
            queue.extend(self.requires(name))
        return found

    def facts(self, name: str) -> dict:
        dist = self.installed.get(name)
        lock_version = self.lock.get(name, {}).get("version")
        if dist is None:
            return {"name": name, "lock_version": lock_version, "installed": False,
                    "wheel_bytes_estimate": _wheel_size(self.lock.get(name, {}))}
        size, native = 0, False
        for file in dist.files or []:
            located = Path(dist.locate_file(file))
            if located.is_file():
                size += located.stat().st_size
                native = native or located.suffix.lower() in NATIVE_SUFFIXES
        return {"name": name, "lock_version": lock_version, "installed_version": dist.version,
                "installed": True, "native": native, "size_bytes": size}


# -- the closure --------------------------------------------------------------------------------------


def _dropped(manifest) -> dict[str, set[str]]:
    """distribution -> the requested extras an omitted row drops (``pyjwt[crypto]`` -> {"crypto"})."""
    out: dict[str, set[str]] = {}
    for row in manifest.omitted_distributions:
        for entry in row.get("dropped_extras", ()):
            name, _, extra = entry.partition("[")
            out.setdefault(_norm(name), set()).add(extra.rstrip("]"))
    return out


def without_dropped_extras(requested: dict[str, set[str]], manifest) -> dict[str, set[str]]:
    """``requested`` minus the extras the profile's omitted rows drop: their requirements are not followed.

    An extra is optional to its distribution by construction; whether THIS one's code imports without
    it is not assumed but proven at run time (:func:`dropped_extra_failures`)."""
    dropped = _dropped(manifest)
    return {name: extras - dropped.get(name, set()) for name, extras in requested.items()}


#: Asked in a child interpreter with the omitted imports made unfindable: every top-level module of a
#: distribution that ships without a dropped extra must still import.
_DROPPED_EXTRA_PROBE = r"""
import importlib, json, sys
blocked, tops = set(json.loads(sys.argv[1])), json.loads(sys.argv[2])

class Absent:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in blocked:
            raise ModuleNotFoundError(f"omitted: {name}", name=name)

sys.meta_path.insert(0, Absent())
for name in blocked:
    for loaded in [m for m in sys.modules if m.split(".")[0] == name]:
        del sys.modules[loaded]
failed = {}
for top in tops:
    try:
        importlib.import_module(top)
    except Exception as exc:  # noqa: BLE001 — the answer is the refusal
        failed[top] = f"{type(exc).__name__}: {exc}"
print(json.dumps(failed))
"""


def dropped_extra_failures(manifest, graph: Graph, shipped: set[str]) -> list[str]:
    """``dist[extra] -> reason`` for each dropped extra whose shipped distribution does NOT import with
    the omitted distributions absent (an import error there is a phone that cannot start)."""
    import subprocess

    dropped = _dropped(manifest)
    if not dropped:
        return []
    blocked = sorted({top for row in manifest.omitted_distributions for top in row["imports"]})
    by_dist: dict[str, list[str]] = {}
    for top, names in graph.mapping.items():
        for name in names:
            by_dist.setdefault(_norm(name), []).append(top)
    out = []
    for name, extras in sorted(dropped.items()):
        label = f"{name}[{','.join(sorted(extras))}]"
        if name not in shipped:
            continue  # not shipped on this target: nothing to import
        tops = sorted(t for t in by_dist.get(name, []) if not t.startswith("_") and t.isidentifier())
        if not tops:
            out.append(f"{label}: not installed, so its import without the extra is unproven")
            continue
        done = subprocess.run([sys.executable, "-c", _DROPPED_EXTRA_PROBE, json.dumps(blocked), json.dumps(tops)],
                              capture_output=True, text=True, timeout=300, cwd=ROOT, check=False)
        if done.returncode != 0:
            raise RuntimeError(f"dropped-extra probe failed for {label}: {done.stderr[-2000:]}")
        failed = json.loads(done.stdout.strip().splitlines()[-1])
        out += [f"{label}: {top} does not import without the omitted distributions ({why})"
                for top, why in sorted(failed.items())]
    return out


def omitted_import_sites(manifest, walk_result: Walk) -> dict[str, list[dict]]:
    """Every import site of an omitted distribution in the kept modules (each must be guarded)."""
    return {row["distribution"]: [dict(site, top=top) for top in row["imports"]
                                  for site in walk_result.import_sites.get(top, [])]
            for row in manifest.omitted_distributions}


def classify(direct: dict[str, list[str]], base, extras, selected, omitted,
             not_for_target=(), guarded_only=()) -> dict[str, dict]:
    """Direct distribution -> {status, extras, via}; status is ship / ship-undeclared / optional / omitted.

    ``base`` and ``extras`` are dependency CLOSURES, so a distribution that arrives only as a
    requirement of an extra (botocore under ``bedrock``'s boto3) is classified with that extra.
    ``not_for_target``: declared, but every declaration's marker is false for the target
    (``ptyprocess; sys_platform != 'win32'`` on Windows) — optional, not undeclared.
    ``guarded_only``: undeclared, and every import site in the kept modules is guarded
    (``hermes_cli._launchers`` tries ``distlib`` then pip's copy) — optional.
    """
    rows = {}
    for dist, via in direct.items():
        homes = sorted(e for e, dists in extras.items() if dist in dists)
        if dist in omitted:
            status = "omitted"
        elif dist in base or set(homes) & set(selected):
            status = "ship"
        elif homes or dist in not_for_target or dist in guarded_only:
            status = "optional"
        else:
            status = "ship-undeclared"
        declared_as = ("base" if dist in base else
                       "extra " + ",".join(sorted(set(homes) & set(selected))) if set(homes) & set(selected) else
                       "extra " + ",".join(homes) if homes else
                       "declared for other targets" if dist in not_for_target else
                       "undeclared, every import guarded" if dist in guarded_only else "undeclared")
        rows[dist] = {"status": status, "extras": homes, "declared": declared_as, "via": via}
    return rows


def shipped_distributions(graph, classes: dict[str, dict], dynamic, declared_base) -> set[str]:
    """The shipped rows plus the base distributions no static import reaches (stdlib ``zoneinfo``
    loads ``tzdata``), with every requirement — requested extras included — followed."""
    return graph.closure({*(d for d, row in classes.items() if row["status"].startswith("ship")),
                          *(set(dynamic) & set(declared_base))})


class WalkFacts:
    """A closure's first-party half: the profile's one walk, which depends on neither the extras
    selected nor the site directories distribution metadata is read from. Built once per process;
    every :class:`GraphFacts` and every selection of extras reads it."""

    def __init__(self, manifest, *, parents: bool = False, index: dict[str, Path] | None = None):
        self.manifest = manifest
        self.result, self.index = profile_walk(manifest, index, parents=parents)
        self.first_party = {m.split(".")[0] for m in self.index}
        self.roots = (*manifest.packaging_roots, *plugin_roots(manifest))
        self.pruned = manifest.switched_off_modules
        self.pinned_tops = eager_tops(self.result.pinned, self.index, self.first_party)
        self.tops = dict(self.result.tops)
        for top in self.pinned_tops:
            self.tops.setdefault(top, ["(pinned module)"])
        self.placeholders = {_norm(d) for d in manifest.placeholder_distributions}
        self.omitted = {_norm(r["distribution"]) for r in manifest.omitted_distributions}
        self.dynamic = {_norm(d) for d in manifest.dynamic_distributions}
        sites = omitted_import_sites(manifest, self.result)
        self.unguarded_sites = {d: [s for s in ss if not s["guarded"]] for d, ss in sites.items()}
        self.answered = stand_in_answered(manifest, self.unguarded_sites)


class GraphFacts:
    """A closure's distribution half for one marker environment, from the metadata visible on
    ``sys.path`` when it is built (the packager's child points that at the pool or the bundle)."""

    def __init__(self, walk: WalkFacts, env: dict):
        self.walk, self.env = walk, env
        self.graph = Graph(_lock(), without_dropped_extras(requested_extras(env=env), walk.manifest),
                           walk.placeholders, env=env)
        self.declared_base, self.declared_extras = declared(env=env)
        self.base = self.graph.closure(self.declared_base - walk.omitted)
        self.extras = {extra: self.graph.closure(dists) for extra, dists in self.declared_extras.items()}
        self.direct: dict[str, list[str]] = {}
        self.unresolved = {}
        for top, via in walk.tops.items():
            dists = self.graph.dists_for_sites(top, walk.result.import_sites.get(top, ()))
            if not dists:
                self.unresolved[top] = via
            for dist in sorted(dists):
                self.direct.setdefault(dist, via)
        self.not_for_target = declared_anywhere() - self.declared_base - set().union(*self.declared_extras.values())
        unguarded = set().union(*(self.graph.dists_for_sites(top, [site for site in sites if not site["guarded"]])
                                  for top, sites in walk.result.import_sites.items()
                                  if any(not site["guarded"] for site in sites)))
        unguarded |= {self.graph.dist_for_top(top) for top in walk.pinned_tops}
        self.guarded_only = set(self.direct) - unguarded

    def select(self, extra_extras=()) -> tuple[tuple[str, ...], dict[str, dict], set[str]]:
        """-> (the extras shipped, the direct distributions' classes, every distribution that ships)."""
        selected = (*self.walk.manifest.packaging_extras, *extra_extras)
        classes = classify(self.direct, self.base, self.extras, selected, self.walk.omitted,
                           self.not_for_target, self.guarded_only)
        return selected, classes, shipped_distributions(self.graph, classes, self.walk.dynamic, self.declared_base)

    def refusal_facts(self, selected, shipped: set[str]) -> dict:
        """The result keys :func:`refusals` reads, for one selection."""
        walk = self.walk
        return {
            "unknown_extras": sorted(set(selected) - set(self.declared_extras)),
            "omitted_but_required": sorted(walk.omitted & shipped),
            # A dynamic distribution declared for other targets only (tzdata off Windows) is skipped.
            "dynamic_not_base": sorted(walk.dynamic - self.declared_base - self.not_for_target),
            # A placeholder stands in for a REQUIREMENT only: kept code importing it, or base code
            # (which may assume a base dependency), would get the placeholder.
            "placeholder_imported": sorted(walk.placeholders & set(self.direct)),
            "placeholder_is_base": sorted(walk.placeholders & self.declared_base),
            "omitted_unguarded_import_sites": {d: [s for s in ss if s.get("dotted") not in walk.answered.get(d, ())]
                                               for d, ss in walk.unguarded_sites.items()},
            "dropped_extra_failures": dropped_extra_failures(walk.manifest, self.graph, shipped),
        }

    def plan(self, extra_extras=()) -> dict:
        """``{needed: [distribution…], refusals: [line…]}``: what the packager ships for one selection."""
        selected, _classes, shipped = self.select(extra_extras)
        return {"needed": sorted(shipped), "refusals": refusals(self.refusal_facts(selected, shipped))}


def plan_jobs(manifest, jobs, env: dict, *, root: Path = ROOT, base_path: list[str] | None = None,
              index: dict[str, Path] | None = None, progress=None) -> list[dict[str, dict]]:
    """The packager's planning (``scripts/bundle_profile_package.distribution_plans``), in process.

    ``jobs``: ``[{"sites": [dir…], "selections": {key: [extra…]}}]``. ONE walk of ``manifest``
    (:class:`WalkFacts`); then per job the distribution metadata of its ``sites`` alone — they lead
    ``sys.path`` (before ``root`` and ``base_path``) while its :class:`GraphFacts` is read — and
    :meth:`GraphFacts.plan` for each selection. ``progress(step)`` is told each step.
    """
    tell = progress or (lambda _step: None)
    walk = WalkFacts(manifest, parents=True, index=index)
    base = list(sys.path) if base_path is None else list(base_path)
    saved, out = list(sys.path), []
    try:
        for number, job in enumerate(jobs):
            sys.path[:] = [*job["sites"], str(root), *base]
            tell(f"graph {number}")
            facts = GraphFacts(walk, env)
            plans = {}
            for key, extras in job["selections"].items():
                tell(f"select {number} {key or 'core'}")
                plans[key] = facts.plan(tuple(extras))
            out.append(plans)
    finally:
        sys.path[:] = saved
    return out


def closure(profile: str, *, boot: bool = True, extra_extras=(), target: str | None = None,
            parents: bool = False) -> dict:
    """``extra_extras``: extras shipped on top of ``packaging.extras`` (an engine pack's).

    ``target``: a :data:`TARGETS` key; markers are evaluated for it (default: the desktop
    installer's :data:`TARGET_ENV`). ``parents``: the walk also enters every kept module's
    enclosing packages (their ``__init__`` runs on import) — see :class:`Walk`.

    The full report. The packager reads :meth:`GraphFacts.plan` instead: the same walk and the
    same selection, without the excludable walk, the boot probe and the size facts.
    """
    from agent_runtime.bundle_profiles.manifest import load_profile

    env = TARGETS[target] if target is not None else TARGET_ENV
    manifest = load_profile(profile, validate=False)
    walk = WalkFacts(manifest, parents=parents)
    facts = GraphFacts(walk, env)
    graph, result, index = facts.graph, walk.result, walk.index
    selected, classes, shipped = facts.select(extra_extras)
    dynamic = walk.dynamic

    # Excludable: what the switched-off modules alone would add.
    everything = Walk(tuple(walk.roots) + tuple(walk.pruned), (), index, walk.first_party)
    all_direct = set().union(*(graph.dists_for_sites(t, everything.import_sites.get(t, ())) for t in everything.tops))
    all_classes = classify({d: [] for d in all_direct}, facts.base, facts.extras, selected, walk.omitted)
    reachable = graph.closure(d for d, row in all_classes.items() if row["status"].startswith("ship"))

    booted: set[str] = set()
    if boot:
        booted = graph.closure({d for d in (graph.dist_for_top(t) for t in boot_tops(manifest.packaging_roots, walk.first_party)) if d})

    rows = [{**graph.facts(n), "loaded_at_boot": n in booted,
             "direct": classes.get(n, {}).get("status", "dynamic" if n in dynamic else "requirement"),
             "extras": classes.get(n, {}).get("extras", []),
             "declared": classes.get(n, {}).get("declared", "base, reached dynamically" if n in dynamic
                                                else "requirement")} for n in sorted(shipped)]
    optional = [{**graph.facts(d), "extras": row["extras"], "via": row["via"]}
                for d, row in sorted(classes.items()) if row["status"] == "optional"]
    omitted_rows = [{**graph.facts(_norm(r["distribution"])), "degrades": r.get("degrades", "")}
                    for r in manifest.omitted_distributions]
    excl = [graph.facts(n) for n in sorted(reachable - shipped)]
    refused = facts.refusal_facts(selected, shipped)
    return {
        "profile": manifest.profile, "interpreter": sys.version.split()[0], "venv": sys.prefix,
        "target": env, "extras_shipped": list(selected),
        "unknown_extras": refused["unknown_extras"],
        "first_party_modules_kept": len(result.kept),
        "pinned_switched_off_modules": sorted(result.pinned),
        "unguarded_switched_off_imports": sorted(result.unguarded_into_pruned,
                                                 key=lambda r: (r["target"], r["module"], r["line"])),
        "needed": rows, "optional_not_shipped": optional, "omitted": omitted_rows,
        "omitted_but_required": refused["omitted_but_required"],
        "dynamic_not_base": refused["dynamic_not_base"],
        "placeholder_imported": refused["placeholder_imported"],
        "placeholder_is_base": refused["placeholder_is_base"],
        "omitted_unguarded_import_sites": refused["omitted_unguarded_import_sites"],
        "stand_in_answered": walk.answered,
        "dropped_extra_failures": refused["dropped_extra_failures"],
        "excludable": excl,
        "needed_measured_bytes": sum(r.get("size_bytes", 0) for r in rows),
        "needed_estimated_bytes": sum(r.get("wheel_bytes_estimate") or 0 for r in rows if not r["installed"]),
        # Compressed, comparable to an installer ceiling: every shipped distribution's uv.lock wheel.
        "needed_wheel_bytes": sum(_wheel_size(graph.lock.get(r["name"], {})) or 0 for r in rows),
        "needed_without_wheel": sorted(r["name"] for r in rows if not _wheel_size(graph.lock.get(r["name"], {}))),
        "excludable_total_bytes": sum(r.get("size_bytes", 0) for r in excl),
        "unresolved_import_names": facts.unresolved,
        "reached_via": {d: row["via"] for d, row in sorted(classes.items())},
        "loaded_at_boot_not_in_static": sorted(booted - shipped),
    }


def refusals(result: dict) -> list[str]:
    """Reasons the profile's packaging is not sound; empty when it is."""
    out = [f"omitted {d} is imported unguarded at {[(s['module'], s['line']) for s in sites]}"
           for d, sites in result["omitted_unguarded_import_sites"].items() if sites]
    out += [f"omitted {d} is required by a shipped distribution" for d in result["omitted_but_required"]]
    out += [f"packaging.extras names no pyproject extra: {e}" for e in result["unknown_extras"]]
    out += [f"packaging.dynamic_distributions names no base dependency: {d}"
            for d in result.get("dynamic_not_base", [])]
    out += [f"placeholder distribution {d} is imported by kept first-party code"
            for d in result.get("placeholder_imported", [])]
    out += [f"placeholder distribution {d} is a base dependency" for d in result.get("placeholder_is_base", [])]
    out += [f"dropped extra {reason}" for reason in result.get("dropped_extra_failures", [])]
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-desktop")
    parser.add_argument("--json", type=Path, help="write the full result here")
    parser.add_argument("--markdown", type=Path, help="write the doc's tables here")
    parser.add_argument("--no-boot", action="store_true", help="skip the instrumented boot probe")
    args = parser.parse_args(argv)
    # ``parents``: the report walks the way the packager and the profile gate do, so
    # the modules a kept module's package ``__init__`` imports are counted.
    result = closure(args.profile, boot=not args.no_boot, parents=True)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        args.markdown.write_text(render_markdown(result), encoding="utf-8")
    boot = [r for r in result["needed"] if r["loaded_at_boot"]]
    print(f"shipped {len(result['needed'])} dists, {_mib(result['needed_measured_bytes'])} MiB measured + "
          f"~{_mib(result['needed_estimated_bytes'])} MiB wheel estimate; all shipped as wheels "
          f"~{_mib(result['needed_wheel_bytes'])} MiB; boot {len(boot)} dists "
          f"{_mib(sum(r.get('size_bytes', 0) for r in boot))} MiB; "
          f"optional-not-shipped {len(result['optional_not_shipped'])}; excludable {len(result['excludable'])}, "
          f"{_mib(result['excludable_total_bytes'])} MiB; pinned {result['pinned_switched_off_modules']}; "
          f"unguarded switched-off imports {len(result['unguarded_switched_off_imports'])}")
    problems = refusals(result)
    for problem in problems:
        print(f"REFUSED: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
