"""Import closure of a bundle profile: which third-party distributions its enabled features pull.

Static walk (``ast``), module-level AND function-level imports, from the
profile manifest's ``packaging.roots``. The walk never follows an import into
``packaging.switched_off_modules``; a distribution reached only through those
is EXCLUDABLE. Over-approximation is the safe direction for "needed": a lazy
import counts, a ``try: import x`` counts.

A switched-off module that a kept module imports at MODULE level is loaded
anyway — it is reported as "pinned" and its module-level imports count as
needed, because the bundle cannot omit it without a seam.

Third-party import names map to distributions through the running
interpreter's ``importlib.metadata`` (run this under the venv you are
measuring); transitive requirements follow installed metadata. Versions come
from ``uv.lock``; sizes are the on-disk bytes of each installed distribution's
RECORD files.

Usage::

    python scripts/bundle_profile_closure.py --profile bundled-desktop --json out.json
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


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def module_index(root: Path = ROOT) -> dict[str, Path]:
    """Dotted first-party module name -> file."""
    index: dict[str, Path] = {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if _SKIP_DIRS.intersection(rel.parts[:-1]):
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts and all(p.isidentifier() for p in parts):
            index[".".join(parts)] = path
    return index


def _imports(path: Path, module: str, is_pkg: bool):
    """Yield ``(dotted, eager)`` for every import in the file; eager = at module level."""
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
    package = module if is_pkg else module.rpartition(".")[0]
    for node in ast.walk(tree):
        eager = id(node) in top_level
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, eager
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                base = ".".join([*anchor, base] if base else anchor)
            yield base, eager
            for alias in node.names:
                yield f"{base}.{alias.name}", eager


def _owner(dotted: str, index: dict[str, Path]) -> str | None:
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        candidate = ".".join(parts[:i])
        if candidate in index:
            return candidate
    return None


def _under(module: str, prefixes) -> bool:
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def walk(roots, pruned, index, first_party_tops):
    """-> (kept modules, third-party import tops, pinned switched-off modules)."""
    queue = deque(m for m in index if _under(m, roots))
    parent: dict[str, str] = {m: "" for m in queue}
    kept, tops, pinned = set(), {}, set()
    while queue:
        module = queue.popleft()
        if module in kept:
            continue
        kept.add(module)
        path = index[module]
        for dotted, eager in _imports(path, module, path.name == "__init__.py"):
            owner = _owner(dotted, index)
            if owner is None:
                top = dotted.split(".")[0]
                if top and top not in first_party_tops and top not in sys.stdlib_module_names:
                    tops.setdefault(top, _chain(module, parent))
                continue
            if _under(owner, pruned):
                if eager and not _under(module, pruned):
                    pinned.add(owner)
                continue
            if owner not in parent:
                parent[owner] = module
                queue.append(owner)
    return kept, tops, pinned


def _chain(module: str, parent: dict[str, str]) -> list[str]:
    """Root -> ... -> ``module``: the first import path the walk found."""
    chain = [module]
    while parent.get(chain[-1]):
        chain.append(parent[chain[-1]])
    return chain[::-1]


def eager_tops(modules, index, first_party_tops) -> set[str]:
    tops = set()
    for module in modules:
        path = index[module]
        for dotted, eager in _imports(path, module, path.name == "__init__.py"):
            top = dotted.split(".")[0]
            if eager and _owner(dotted, index) is None and top not in first_party_tops \
                    and top not in sys.stdlib_module_names:
                tops.add(top)
    return tops


def _requires(dist: md.Distribution) -> list[str]:
    from packaging.requirements import Requirement

    names = []
    for raw in dist.requires or []:
        req = Requirement(raw)
        if req.marker is None or req.marker.evaluate({"extra": ""}):
            names.append(_norm(req.name))
    return names


def distributions_for(tops: set[str]) -> tuple[set[str], set[str]]:
    """Import tops -> (installed distribution names incl. transitive requirements, unresolved tops)."""
    mapping = md.packages_distributions()
    installed = {_norm(d.metadata["Name"]): d for d in md.distributions()}
    found, unresolved = set(), set()
    for top in tops:
        names = mapping.get(top)
        if names:
            found.update(_norm(n) for n in names)
        elif _norm(top) in installed:
            found.add(_norm(top))
        else:
            unresolved.add(top)
    queue = deque(found)
    while queue:
        dist = installed.get(queue.popleft())
        for req in (_requires(dist) if dist else []):
            if req not in found:
                found.add(req)
                queue.append(req)
    return found, unresolved


def dist_facts(name: str, lock: dict[str, str]) -> dict:
    try:
        dist = md.distribution(name)
    except md.PackageNotFoundError:
        return {"name": name, "lock_version": lock.get(name), "installed": False}
    size, native = 0, False
    for file in dist.files or []:
        located = Path(dist.locate_file(file))
        if located.is_file():
            size += located.stat().st_size
            native = native or located.suffix.lower() in NATIVE_SUFFIXES
    return {"name": name, "lock_version": lock.get(name), "installed_version": dist.version,
            "installed": True, "native": native, "size_bytes": size}


def lock_versions(path: Path = ROOT / "uv.lock") -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {_norm(p["name"]): p.get("version") for p in data.get("package", [])}


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


IMPORT_ALIASES = {"piper": "piper-tts", "PIL": "pillow", "faster_whisper": "faster-whisper"}


def _wheel_size(package: dict) -> int | None:
    """The Windows cp312 wheel's size from uv.lock (preferring cp312, then abi3, then any)."""
    wheels = package.get("wheels", [])
    for tag in ("cp312-win_amd64", "abi3-win_amd64", "none-win_amd64", "none-any"):
        for wheel in wheels:
            if wheel["url"].endswith(f"{tag}.whl") and wheel.get("size"):
                return wheel["size"]
    return None


def lock_estimates(tops, have: set[str], path: Path = ROOT / "uv.lock") -> list[dict]:
    """Not-installed tops -> uv.lock packages (+ their lock dependencies), sized by WHEEL bytes (estimate)."""
    from packaging.markers import Marker

    packages = {_norm(p["name"]): p for p in tomllib.loads(path.read_text(encoding="utf-8"))["package"]}
    queue = deque(n for n in (_norm(IMPORT_ALIASES.get(t, t)) for t in tops) if n in packages)
    found: set[str] = set()
    while queue:
        name = queue.popleft()
        if name in found or name in have:
            continue
        found.add(name)
        for dep in packages[name].get("dependencies", []):
            marker = dep.get("marker")
            if marker is None or Marker(marker).evaluate({"extra": "", "python_full_version": "3.12.14"}):
                queue.append(_norm(dep["name"]))
    return [{"name": n, "lock_version": packages[n].get("version"), "installed": False,
             "wheel_bytes_estimate": _wheel_size(packages[n])} for n in sorted(found)]


def closure(profile: str) -> dict:
    from agent_runtime.bundle_profiles.manifest import load_profile

    manifest = load_profile(profile, validate=False)
    index = module_index()
    first_party = {m.split(".")[0] for m in index}
    roots, pruned = manifest.packaging_roots, manifest.switched_off_modules
    kept, reached, pinned = walk(roots, pruned, index, first_party)
    tops = set(reached) | eager_tops(pinned, index, first_party)
    _, all_tops, _ = walk(tuple(roots) + tuple(pruned), (), index, first_party)
    needed, unresolved = distributions_for(tops)
    reachable, _ = distributions_for(set(all_tops))
    booted, _ = distributions_for(boot_tops(roots, first_party))
    lock = lock_versions()
    rows = [{**dist_facts(n, lock), "loaded_at_boot": n in booted} for n in sorted(needed)]
    excl = [dist_facts(n, lock) for n in sorted(reachable - needed)]
    return {
        "profile": manifest.profile, "interpreter": sys.version.split()[0], "venv": sys.prefix,
        "first_party_modules_kept": len(kept), "pinned_switched_off_modules": sorted(pinned),
        "needed": rows, "excludable": excl,
        "needed_total_bytes": sum(r.get("size_bytes", 0) for r in rows),
        "excludable_total_bytes": sum(r.get("size_bytes", 0) for r in excl),
        "unresolved_import_names": {top: reached.get(top, ["(pinned module)"]) for top in sorted(unresolved)},
        "reached_via": reached,
        "loaded_at_boot_not_in_static": sorted(booted - needed),
        "not_installed_estimates": lock_estimates(unresolved, needed),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-desktop")
    parser.add_argument("--json", type=Path, help="write the full result here")
    args = parser.parse_args(argv)
    result = closure(args.profile)
    text = json.dumps(result, indent=2)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(f"needed {len(result['needed'])} dists, {result['needed_total_bytes'] / 2**20:.1f} MiB; "
          f"excludable {len(result['excludable'])}, {result['excludable_total_bytes'] / 2**20:.1f} MiB; "
          f"pinned {result['pinned_switched_off_modules']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
