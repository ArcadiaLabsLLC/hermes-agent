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

NATIVE_SUFFIXES = (".pyd", ".so", ".dll", ".dylib")
_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "web", "website", "apps", "ui-tui"}

#: The bundle target: markers are evaluated for the interpreter the installer ships.
TARGET_ENV = {
    "sys_platform": "win32", "platform_system": "Windows", "platform_machine": "AMD64",
    "os_name": "nt", "python_version": "3.14", "python_full_version": "3.14.0",
    "implementation_name": "cpython", "platform_python_implementation": "CPython",
    "platform_release": "10", "extra": "",
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
        if _SKIP_DIRS.intersection(rel.parts[:-1]):
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


def profile_walk(manifest, index: dict[str, Path] | None = None) -> tuple["Walk", dict[str, Path]]:
    """The profile's one walk: its roots plus its bundled plugins, never into switched-off modules."""
    index = index if index is not None else module_index(plugins=getattr(manifest, "packaging_plugins", ()))
    first_party = {m.split(".")[0] for m in index}
    roots = (*manifest.packaging_roots, *plugin_roots(manifest))
    return Walk(roots, manifest.switched_off_modules, index, first_party), index


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
        if isinstance(node, ast.Try) and any(_catches_import_error(h.type) for h in node.handlers):
            for stmt in node.body:
                guarded.update(id(n) for n in ast.walk(stmt))
        elif isinstance(node, (ast.With, ast.AsyncWith)) and any(_suppresses_import_error(i) for i in node.items):
            for stmt in node.body:
                guarded.update(id(n) for n in ast.walk(stmt))
    return guarded


def _literal_import_module(node: ast.AST) -> str | None:
    """``importlib.import_module("x")`` / ``import_module("x")`` with a literal name -> ``"x"``."""
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
    arg = node.args[0]
    if name == "import_module" and isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
            and not arg.value.startswith("."):
        return arg.value
    return None


def _imports(path: Path, module: str, is_pkg: bool):
    """Yield ``(dotted, eager, guarded, lineno)`` for every import in the file; eager = at module level."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return
    top_level = {id(n) for n in tree.body}
    for stmt in tree.body:
        if isinstance(stmt, (ast.If, ast.Try)):
            top_level.update(id(n) for n in ast.walk(stmt))
    guarded = _guarded_ids(tree)
    package = module if is_pkg else module.rpartition(".")[0]
    for node in ast.walk(tree):
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

    def __init__(self, roots, pruned, index, first_party_tops):
        self.kept: set[str] = set()
        self.tops: dict[str, list[str]] = {}
        self.pinned: set[str] = set()
        self.unguarded_into_pruned: list[dict] = []
        self.import_sites: dict[str, list[dict]] = {}
        # A root prefix (``agent_runtime``) must not seed a switched-off module under it.
        queue = deque(m for m in index if _under(m, roots) and not _under(m, pruned))
        parent: dict[str, str] = {m: "" for m in queue}
        while queue:
            module = queue.popleft()
            if module in self.kept:
                continue
            self.kept.add(module)
            path = index[module]
            for dotted, eager, guarded, line in _imports(path, module, path.name == "__init__.py"):
                owner = _owner(dotted, index)
                if owner is None:
                    top = dotted.split(".")[0]
                    if top and top not in first_party_tops and top not in sys.stdlib_module_names:
                        self.tops.setdefault(top, _import_chain(module, parent))
                        self.import_sites.setdefault(top, []).append(
                            {"module": module, "line": line, "guarded": guarded, "eager": eager})
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


def declared(path: Path = ROOT / "pyproject.toml") -> tuple[set[str], dict[str, set[str]]]:
    """-> (base distribution names, extra -> distribution names), markers evaluated for the target."""
    project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    self_name = _norm(project["name"])

    def names(raws):
        out, refs = set(), set()
        for raw in raws:
            req = _req(raw)
            if req.marker is not None and not req.marker.evaluate(TARGET_ENV):
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


def declared_anywhere(path: Path = ROOT / "pyproject.toml") -> set[str]:
    """Every distribution ``[project]`` declares (base + extras), markers NOT evaluated."""
    project = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
    raws = [*project.get("dependencies", []), *(r for reqs in project.get("optional-dependencies", {}).values()
                                                 for r in reqs)]
    return {_norm(_req(raw).name) for raw in raws} - {_norm(project["name"])}


def _lock(path: Path = ROOT / "uv.lock") -> dict[str, dict]:
    return {_norm(p["name"]): p for p in tomllib.loads(path.read_text(encoding="utf-8")).get("package", [])}


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

    def __init__(self, lock: dict[str, dict]):
        self.lock = lock
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

    def requires(self, name: str) -> list[str]:
        dist = self.installed.get(name)
        if dist is not None:
            out = []
            for raw in dist.requires or []:
                req = _req(raw)
                if req.marker is None or req.marker.evaluate(TARGET_ENV):
                    out.append(_norm(req.name))
            return out
        from packaging.markers import Marker

        out = []
        for dep in self.lock.get(name, {}).get("dependencies", []):
            marker = dep.get("marker")
            if marker is None or Marker(marker).evaluate(TARGET_ENV):
                out.append(_norm(dep["name"]))
        return out

    def closure(self, roots) -> set[str]:
        found, queue = set(), deque(roots)
        while queue:
            name = queue.popleft()
            if name in found:
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


_BOOT_PROBE = "; ".join([
    "import importlib, json, sys",
    "[importlib.import_module(m) for m in sys.argv[1:]]",
    "print(json.dumps(sorted({n.split('.')[0] for n in sys.modules})))",
])


def boot_tops(roots, first_party_tops) -> set[str]:
    """Instrumented lower bound: third-party tops actually loaded by importing ``roots``."""
    import subprocess

    done = subprocess.run([sys.executable, "-c", _BOOT_PROBE, *roots], cwd=ROOT, capture_output=True,
                          text=True, timeout=300, check=True)
    loaded = json.loads(done.stdout.strip().splitlines()[-1])
    return {t for t in loaded if t not in first_party_tops and t not in sys.stdlib_module_names
            and not t.startswith("_")}


# -- the closure --------------------------------------------------------------------------------------


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


def closure(profile: str, *, boot: bool = True, extra_extras=()) -> dict:
    """``extra_extras``: extras shipped on top of ``packaging.extras`` (an engine pack's)."""
    from agent_runtime.bundle_profiles.manifest import load_profile

    manifest = load_profile(profile, validate=False)
    selected = (*manifest.packaging_extras, *extra_extras)
    result, index = profile_walk(manifest)
    first_party = {m.split(".")[0] for m in index}
    roots, pruned = (*manifest.packaging_roots, *plugin_roots(manifest)), manifest.switched_off_modules
    tops = dict(result.tops)
    for top in eager_tops(result.pinned, index, first_party):
        tops.setdefault(top, ["(pinned module)"])

    graph = Graph(_lock())
    declared_base, declared_extras = declared()
    omitted = {_norm(r["distribution"]) for r in manifest.omitted_distributions}
    base = graph.closure(declared_base - omitted)
    extras = {extra: graph.closure(dists) for extra, dists in declared_extras.items()}
    direct: dict[str, list[str]] = {}
    unresolved = {}
    for top, via in tops.items():
        dist = graph.dist_for_top(top)
        if dist is None:
            unresolved[top] = via
        else:
            direct.setdefault(dist, via)
    not_for_target = declared_anywhere() - declared_base - set().union(*declared_extras.values())
    unguarded = {graph.dist_for_top(top) for top, sites in result.import_sites.items()
                 if any(not site["guarded"] for site in sites)}
    unguarded |= {graph.dist_for_top(top) for top in eager_tops(result.pinned, index, first_party)}
    guarded_only = set(direct) - unguarded
    classes = classify(direct, base, extras, selected, omitted, not_for_target, guarded_only)
    shipped = graph.closure(d for d, row in classes.items() if row["status"].startswith("ship"))

    # Excludable: what the switched-off modules alone would add.
    everything = Walk(tuple(roots) + tuple(pruned), (), index, first_party)
    all_direct = {d for d in (graph.dist_for_top(t) for t in everything.tops) if d}
    all_classes = classify({d: [] for d in all_direct}, base, extras, selected, omitted)
    reachable = graph.closure(d for d, row in all_classes.items() if row["status"].startswith("ship"))

    booted: set[str] = set()
    if boot:
        booted = graph.closure({d for d in (graph.dist_for_top(t) for t in boot_tops(manifest.packaging_roots, first_party)) if d})

    rows = [{**graph.facts(n), "loaded_at_boot": n in booted,
             "direct": classes.get(n, {}).get("status", "requirement"),
             "extras": classes.get(n, {}).get("extras", []),
             "declared": classes.get(n, {}).get("declared", "requirement")} for n in sorted(shipped)]
    optional = [{**graph.facts(d), "extras": row["extras"], "via": row["via"]}
                for d, row in sorted(classes.items()) if row["status"] == "optional"]
    omitted_rows = [{**graph.facts(_norm(r["distribution"])), "degrades": r.get("degrades", "")}
                    for r in manifest.omitted_distributions]
    excl = [graph.facts(n) for n in sorted(reachable - shipped)]
    sites = omitted_import_sites(manifest, result)
    return {
        "profile": manifest.profile, "interpreter": sys.version.split()[0], "venv": sys.prefix,
        "target": TARGET_ENV, "extras_shipped": list(selected),
        "unknown_extras": sorted(set(selected) - set(declared_extras)),
        "first_party_modules_kept": len(result.kept),
        "pinned_switched_off_modules": sorted(result.pinned),
        "unguarded_switched_off_imports": sorted(result.unguarded_into_pruned,
                                                 key=lambda r: (r["target"], r["module"], r["line"])),
        "needed": rows, "optional_not_shipped": optional, "omitted": omitted_rows,
        "omitted_but_required": sorted(omitted & shipped),
        "omitted_unguarded_import_sites": {d: [s for s in ss if not s["guarded"]] for d, ss in sites.items()},
        "excludable": excl,
        "needed_measured_bytes": sum(r.get("size_bytes", 0) for r in rows),
        "needed_estimated_bytes": sum(r.get("wheel_bytes_estimate") or 0 for r in rows if not r["installed"]),
        # Compressed, comparable to an installer ceiling: every shipped distribution's uv.lock wheel.
        "needed_wheel_bytes": sum(_wheel_size(graph.lock.get(r["name"], {})) or 0 for r in rows),
        "needed_without_wheel": sorted(r["name"] for r in rows if not _wheel_size(graph.lock.get(r["name"], {}))),
        "excludable_total_bytes": sum(r.get("size_bytes", 0) for r in excl),
        "unresolved_import_names": unresolved,
        "reached_via": {d: row["via"] for d, row in sorted(classes.items())},
        "loaded_at_boot_not_in_static": sorted(booted - shipped),
    }


def refusals(result: dict) -> list[str]:
    """Reasons the profile's packaging is not sound; empty when it is."""
    out = [f"omitted {d} is imported unguarded at {[(s['module'], s['line']) for s in sites]}"
           for d, sites in result["omitted_unguarded_import_sites"].items() if sites]
    out += [f"omitted {d} is required by a shipped distribution" for d in result["omitted_but_required"]]
    out += [f"packaging.extras names no pyproject extra: {e}" for e in result["unknown_extras"]]
    return out


# -- rendering ------------------------------------------------------------------------------------------


def _mib(n) -> str:
    return f"{(n or 0) / 2**20:.2f}"


def _version(row) -> str:
    lock, inst = row.get("lock_version"), row.get("installed_version")
    if lock and inst and lock != inst:
        return f"{lock} (venv {inst})"
    return lock or (f"— (venv {inst})" if inst else "—")


def render_markdown(result: dict) -> str:
    rows = result["needed"]
    measured = [r for r in rows if r["installed"]]
    estimated = [r for r in rows if not r["installed"]]
    boot = [r for r in measured if r["loaded_at_boot"]]
    optional_bytes = sum((r.get("size_bytes") if r["installed"] else r.get("wheel_bytes_estimate")) or 0
                         for r in result["optional_not_shipped"])
    out = ["| | distributions | size |", "|---|---:|---:|",
           f"| Shipped, installed (measured) | {len(measured)} | **{_mib(result['needed_measured_bytes'])} MiB** |",
           f"| — of which loaded at boot | {len(boot)} | {_mib(sum(r['size_bytes'] for r in boot))} MiB |",
           f"| Shipped, not installed locally (uv.lock wheel bytes, **estimate**) | {len(estimated)} | "
           f"~{_mib(result['needed_estimated_bytes'])} MiB |",
           f"| **All shipped, as uv.lock wheels (compressed — the installer-ceiling view)** | {len(rows)} | "
           f"**~{_mib(result['needed_wheel_bytes'])} MiB** |",
           f"| Optional extras reached but not shipped | {len(result['optional_not_shipped'])} | "
           f"{_mib(optional_bytes)} MiB (direct only) |",
           f"| Omitted base distributions | {len(result['omitted'])} | "
           f"{_mib(sum(r.get('size_bytes', 0) for r in result['omitted']))} MiB |",
           f"| Excludable (reached only by switched-off features) | {len(result['excludable'])} | "
           f"{_mib(result['excludable_total_bytes'])} MiB |", ""]
    out += ["### Shipped, installed (measured)", "",
            "| distribution | version | declared | pure/native | MiB | loaded at boot |", "|---|---|---|---|---:|---|"]
    for r in measured:
        out.append(f"| {r['name']} | {_version(r)} | {r['declared']} | {'native' if r['native'] else 'pure'} | "
                   f"{_mib(r['size_bytes'])} | {'yes' if r['loaded_at_boot'] else 'no'} |")
    out += ["", "### Shipped, not installed locally (estimate: uv.lock wheel bytes)", "",
            "| distribution | version | MiB (wheel) |", "|---|---|---:|"]
    for r in sorted(estimated, key=lambda r: -(r.get("wheel_bytes_estimate") or 0)):
        out.append(f"| {r['name']} | {_version(r)} | {_mib(r.get('wheel_bytes_estimate'))} |")
    out += ["", "### Optional extras reached but not shipped", "",
            "| distribution | extras | MiB (installed, else wheel) | first reached via |", "|---|---|---:|---|"]
    for r in result["optional_not_shipped"]:
        size = r.get("size_bytes") if r["installed"] else r.get("wheel_bytes_estimate")
        homes = ", ".join(r["extras"][:4]) + (", …" if len(r["extras"]) > 4 else "")
        out.append(f"| {r['name']} | {homes} | {_mib(size)} | `{' → '.join(r['via'])}` |")
    out += ["", "### Omitted base distributions", "", "| distribution | MiB | what degrades |", "|---|---:|---|"]
    for r in result["omitted"]:
        out.append(f"| {r['name']} | {_mib(r.get('size_bytes'))} | {r['degrades']} |")
    out += ["", "### Excludable", "", "| distribution | version | MiB |", "|---|---|---:|"]
    for r in result["excludable"]:
        out.append(f"| {r['name']} | {_version(r)} | {_mib(r.get('size_bytes'))} |")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-desktop")
    parser.add_argument("--json", type=Path, help="write the full result here")
    parser.add_argument("--markdown", type=Path, help="write the doc's tables here")
    parser.add_argument("--no-boot", action="store_true", help="skip the instrumented boot probe")
    args = parser.parse_args(argv)
    result = closure(args.profile, boot=not args.no_boot)
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
