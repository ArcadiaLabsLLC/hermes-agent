"""Package a bundle profile: only its import closure, for one target OS and CPython.

Fork-owned (bundled desktop, plan D1). Given a profile manifest
(``agent_runtime/bundle_profiles/<profile>.yaml``), a target (``win32-x64``,
``darwin-arm64``, ... — the target names of ``pm/lock.json``) and a CPython
version, it writes::

    OUT/
      app/                 first-party modules the closure keeps, their package
                           data, the manifest's resources, and a PEP 621
                           dist-info (upstream's ``scripts/build/agent.write_metadata``)
      site-packages/       only the third-party distributions the closure needs
      bundle-manifest.json what was packaged, from which commit, for which target

Phases:

1. **Pool** — ``uv export --frozen`` of the core dependencies plus the
   manifest's ``packaging.extras``, installed with ``--no-deps
   --require-hashes --only-binary :all:`` into a staging ``--target`` for the
   target platform. The pins and hashes are ``uv.lock``'s, so the pool is
   reproducible; nothing is resolved here.
2. **Plan** — the static import walk of ``scripts/bundle_profile_closure.py``
   (roots, switched-off modules, pinned modules) plus the pinned modules' own
   module-level first-party imports; every third-party import is resolved to
   the distribution that owns that module path in the pool, and requirements
   are followed with the TARGET's markers.
3. **Copy** — tracked first-party files only (``git ls-files``); each needed
   distribution's RECORD files minus ``__pycache__``, test directories and the
   manifest's ``packaging.excluded_data``.
4. **Verify** — :func:`verify_bundle` recomputes the plan from the source tree
   and the bundle's OWN metadata and fails on anything extra or missing (plan
   D4: the bundle matches its manifest). The build exits non-zero on a problem.

No interpreter is packaged here: the target interpreter is pinned in
``agent_runtime/bundle_profiles/interpreters.lock.json`` (PM's own
python-build-standalone pin) and placed by the installer. ``--bake-with PYTHON`` compiles the bundle's bytecode with that
interpreter (``unchecked-hash``, as ``scripts/bundles/bytecode.py`` does).

Usage::

    python scripts/bundle_profile_package.py --profile bundled-desktop \\
        --target win32-x64 --python-version 3.14 --out <dir> [--stage <dir>]
    python scripts/bundle_profile_package.py --profile bundled-desktop --verify <dir>
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bundle_profile_closure import _imports, _norm, _owner, module_index, profile_walk  # noqa: E402

#: pm/lock.json target name -> (uv --python-platform, PEP 508 marker environment)
TARGETS: dict[str, tuple[str, dict[str, str]]] = {
    "win32-x64": ("x86_64-pc-windows-msvc",
                  {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt",
                   "platform_machine": "AMD64"}),
    "win32-arm64": ("aarch64-pc-windows-msvc",
                    {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt",
                     "platform_machine": "ARM64"}),
    "darwin-arm64": ("aarch64-apple-darwin",
                     {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix",
                      "platform_machine": "arm64"}),
    "darwin-x64": ("x86_64-apple-darwin",
                   {"sys_platform": "darwin", "platform_system": "Darwin", "os_name": "posix",
                    "platform_machine": "x86_64"}),
    "linux-x64": ("x86_64-unknown-linux-gnu",
                  {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix",
                   "platform_machine": "x86_64"}),
    "linux-arm64": ("aarch64-unknown-linux-gnu",
                    {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix",
                     "platform_machine": "aarch64"}),
}

#: Path components that never ship, first- or third-party.
TEST_DIRS = {"tests", "test", "testing_data"}
NOISE_DIRS = {"__pycache__"}
NOISE_SUFFIXES = (".pyc", ".pyo")
BUNDLE_MANIFEST = "bundle-manifest.json"
BAKED_MARKER = ".hermes-baked-pycache"
#: ``agent_runtime.build_stamp``'s baked stamp, read beside the package when no git is consulted.
BUILD_SHA_FILE = ".hermes_build_sha"
#: Core site-packages file that adds every installed engine pack to the import path at start.
#: ``site`` runs a .pth line that starts with ``import``; a missing directory is skipped, so
#: no pack means the engine's imports fail and its provider reports unavailable.
ENGINE_PACKS_ENV = "HERMES_ENGINE_PACKS"
ENGINE_PACKS_PTH = "hermes-engine-packs.pth"
ENGINE_PACKS_PTH_LINE = (
    "import os, site; [site.addsitedir(p) for p in os.environ.get(%r, '').split(os.pathsep) "
    "if p and os.path.isdir(p)]\n" % ENGINE_PACKS_ENV)
#: Files the packaging step itself writes into a site-packages (owned by no distribution).
PACKAGER_FILES = {ENGINE_PACKS_PTH}
PACK_MANIFEST = "engine-pack.json"


def marker_env(target: str, python_version: str) -> dict[str, str]:
    _, env = TARGETS[target]
    full = python_version if python_version.count(".") >= 2 else f"{python_version}.0"
    return {**env, "python_version": ".".join(full.split(".")[:2]), "python_full_version": full,
            "implementation_name": "cpython", "platform_python_implementation": "CPython",
            "platform_release": "", "platform_version": "", "extra": ""}


# -- phase 1: the pool -----------------------------------------------------------------------


def export_requirements(extras: tuple[str, ...], uv: str = "uv") -> str:
    """``uv.lock``'s pins + hashes for core + ``extras`` (no resolution happens here)."""
    cmd = [uv, "export", "--frozen", "--format", "requirements.txt", "--no-emit-project",
           "--no-dev", "--no-header", "--no-annotate"]
    for extra in extras:
        cmd += ["--extra", extra]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True, timeout=300)
    return done.stdout


def evaluate_markers(requirements: str, env: dict[str, str]) -> str:
    """Keep the requirement blocks whose marker holds for ``env``; strip the markers.

    Evaluated here, not by uv: uv's cross-target marker environment for
    ``x86_64-pc-windows-msvc`` does not report ``platform_machine == 'AMD64'``
    (measured 2026-09-28, uv 0.11.14), so ``nemo-relay``'s Windows arm silently
    dropped out of the pool. :func:`marker_env` is the one target authority.
    """
    from packaging.markers import Marker

    kept: list[str] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        head, _, marker = block[0].rstrip(" \\").partition(" ; ")
        if not marker or Marker(marker).evaluate(env):
            kept.append(head.strip() + " \\")
            kept.extend(block[1:])
        block.clear()

    for line in requirements.splitlines():
        if line.startswith((" ", "\t")):
            block.append(line)
        elif line.strip() and not line.startswith("#"):
            flush()
            block.append(line)
    flush()
    return "\n".join(kept) + "\n"


def install_pool(requirements: str, stage: Path, target: str, python_version: str,
                 uv: str = "uv", offline: bool = False) -> None:
    """Install the exported pins into ``stage`` for ``target`` — hashes required, wheels only."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    req = stage.parent / f"{stage.name}.requirements.txt"
    req.write_text(evaluate_markers(requirements, marker_env(target, python_version)), encoding="utf-8")
    cmd = [uv, "pip", "install", "--target", str(stage), "--python-platform", TARGETS[target][0],
           "--python-version", python_version, "--no-config", "--no-deps", "--require-hashes",
           "--only-binary", ":all:", "--link-mode", "copy", "--no-compile", "-r", str(req)]
    if offline:
        cmd.append("--offline")
    subprocess.run(cmd, cwd=ROOT, check=True, timeout=1800, stdin=subprocess.DEVNULL)


# -- distribution facts from a site directory ------------------------------------------------


@dataclass
class Dist:
    name: str
    version: str
    info: str  # dist-info directory name
    files: list[str]  # site-relative RECORD paths inside the site directory


def read_site(site: Path) -> dict[str, Dist]:
    """Every ``*.dist-info`` under ``site`` -> :class:`Dist` (normalized name key)."""
    import csv
    from email.parser import HeaderParser

    dists: dict[str, Dist] = {}
    for info in sorted(site.glob("*.dist-info")):
        meta = HeaderParser().parsestr((info / "METADATA").read_text(encoding="utf-8", errors="replace"))
        files: list[str] = []
        record = info / "RECORD"
        if record.is_file():
            with record.open(encoding="utf-8", newline="") as handle:
                files = [row[0].replace("\\", "/") for row in csv.reader(handle) if row]
        files = [f for f in files if not f.startswith("../") and not f.startswith("/")]
        dist = Dist(name=_norm(meta["Name"]), version=meta["Version"], info=info.name, files=files)
        dists[dist.name] = dist
    return dists


# -- phase 2: the plan -----------------------------------------------------------------------


@dataclass
class Plan:
    profile: str
    target: str
    python_version: str
    first_party: set[str]  # dotted first-party modules shipped
    pinned: set[str]  # switched-off modules shipped because kept code imports them unguarded
    distributions: set[str]  # normalized names: the closure's "needed" set
    missing: set[str] = field(default_factory=set)  # needed, but the site does not hold it
    refusals: list[str] = field(default_factory=list)  # the closure's own packaging refusals


def _eager_first_party_closure(start: set[str], index: dict[str, Path]) -> set[str]:
    """Modules loaded by importing ``start``: follow MODULE-LEVEL first-party imports only."""
    done: set[str] = set()
    queue = deque(m for m in start if m in index)
    while queue:
        module = queue.popleft()
        if module in done:
            continue
        done.add(module)
        # Importing a.b.c runs a/__init__ and a/b/__init__ first.
        parts = module.split(".")
        queue.extend(p for p in (".".join(parts[:i]) for i in range(1, len(parts)))
                     if p in index and p not in done)
        path = index[module]
        for dotted, eager, _guarded, _line in _imports(path, module, path.name == "__init__.py"):
            owner = _owner(dotted, index)
            if eager and owner and owner not in done:
                queue.append(owner)
    return done


def _with_parents(modules: set[str], index: dict[str, Path]) -> set[str]:
    out = set(modules)
    for module in modules:
        parts = module.split(".")
        out.update(p for p in (".".join(parts[:i]) for i in range(1, len(parts))) if p in index)
    return out


def first_party_plan(manifest, index: dict[str, Path] | None = None) -> tuple[set[str], set[str], dict]:
    """-> (modules to ship, switched-off modules shipped anyway, the index).

    The closure's own walk (:func:`profile_walk`) keeps what the roots and
    bundled plugins reach. A switched-off module is shipped too when kept code
    imports it UNGUARDED — at module level (``pinned``) or lazily
    (``unguarded_into_pruned``): omitting it turns that line into a runtime
    ImportError, so the feature stays off by its switch and its code ships.
    Each shipped module brings the modules it imports at module level.
    """
    result, index = profile_walk(manifest, index)
    forced = set(result.pinned) | {row["target"] for row in result.unguarded_into_pruned}
    loaded = _eager_first_party_closure(forced, index) - result.kept
    return _with_parents(result.kept | loaded, index), loaded, index


_DISTRIBUTION_DRIVER = r"""
import json, sys
root, sites, profile, env, extra = sys.argv[1:6]
sys.path[:0] = [*json.loads(sites), root]
import scripts.bundle_profile_closure as closure_script
closure_script.TARGET_ENV.clear()
closure_script.TARGET_ENV.update(json.loads(env))
result = closure_script.closure(profile, boot=False, extra_extras=tuple(json.loads(extra)))
print(json.dumps({"needed": [r["name"] for r in result["needed"]],
                  "refusals": closure_script.refusals(result)}))
"""


def distribution_plan(profile: str, sites: list[Path], target: str, python_version: str,
                      extra_extras=()) -> tuple[set[str], list[str]]:
    """-> (the distributions the closure ships, its refusals).

    The closure script is the one authority for what ships (its declaration-
    aware model: base dependencies, the manifest's extras — plus
    ``extra_extras`` for an engine pack — and omissions). It runs in a child
    interpreter whose ONLY site directories are ``sites`` (``-I -S``), so the
    metadata it reads is the pool's or the bundle's own, with its target
    environment set to ``target``, writing no bytecode into them (``-B``).
    """
    args = [json.dumps([str(site) for site in sites]), profile,
            json.dumps(marker_env(target, python_version)), json.dumps(list(extra_extras))]
    done = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", _DISTRIBUTION_DRIVER, str(ROOT), *args],
                          capture_output=True, text=True, timeout=600, check=True)
    out = json.loads(done.stdout.strip().splitlines()[-1])
    return set(out["needed"]), out["refusals"]


def make_plan(manifest, site: Path, target: str, python_version: str,
              index: dict[str, Path] | None = None) -> Plan:
    """The CORE bundle: the profile's closure with its own extras (no engine pack)."""
    first_party, loaded, _ = first_party_plan(manifest, index)
    needed, refused = distribution_plan(manifest.profile, [site], target, python_version)
    return Plan(profile=manifest.profile, target=target, python_version=python_version,
                first_party=first_party, pinned=loaded, distributions=needed,
                missing=needed - set(read_site(site)), refusals=refused)


def pack_distributions(manifest, pack: str, sites: list[Path], target: str,
                       python_version: str) -> tuple[set[str], list[str]]:
    """An engine pack: what the closure ships WITH the pack's extras and the core does not."""
    core, refused = distribution_plan(manifest.profile, sites, target, python_version)
    full, refused_full = distribution_plan(manifest.profile, sites, target, python_version,
                                           manifest.packaging_packs[pack])
    return full - core, [*refused, *refused_full]


# -- phase 3: copy ---------------------------------------------------------------------------


def tracked_files(root: Path = ROOT) -> list[str]:
    done = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True,
                          check=True, timeout=120)
    return [p for p in done.stdout.decode("utf-8").split("\0") if p]


def _is_noise(rel: str) -> bool:
    parts = rel.split("/")
    return bool(NOISE_DIRS.intersection(parts)) or rel.endswith(NOISE_SUFFIXES)


def _is_test(rel: str) -> bool:
    return bool(TEST_DIRS.intersection(rel.split("/")[:-1]))


def first_party_files(plan: Plan, index: dict[str, Path], tracked: list[str],
                      resources: tuple[str, ...], excluded: dict[str, str] | None = None) -> list[str]:
    """Repo-relative files: shipped modules, their packages' data files, and resources."""
    tracked_set = set(tracked)
    rels: set[str] = set()
    package_dirs: set[str] = set()
    for module in plan.first_party:
        rel = index[module].relative_to(ROOT).as_posix()
        if rel not in tracked_set:
            raise FileNotFoundError(f"shipped module is not tracked by git: {rel}")
        rels.add(rel)
        if rel.endswith("/__init__.py"):
            package_dirs.add(rel.rsplit("/", 1)[0])
    all_package_dirs = {p.relative_to(ROOT).as_posix().rsplit("/", 1)[0]
                        for p in index.values() if p.name == "__init__.py"}
    for rel in tracked:
        if rel.endswith(".py") or _is_noise(rel) or _is_test(rel) or _excluded(f"app/{rel}", excluded or {}):
            continue
        parts = rel.split("/")
        if parts[0] in resources:
            rels.add(rel)
            continue
        # Package data: the nearest enclosing Python package must be shipped.
        for i in range(len(parts) - 1, 0, -1):
            directory = "/".join(parts[:i])
            if directory in all_package_dirs:
                if directory in package_dirs:
                    rels.add(rel)
                break
    return sorted(rels)


def _excluded(rel: str, excluded: dict[str, str]) -> bool:
    """``rel`` is bundle-root-relative (``app/...``, ``site-packages/...``)."""
    return any(rel == pattern or rel.startswith(pattern.rstrip("/") + "/") or fnmatch.fnmatch(rel, pattern)
               for pattern in excluded)


def dist_files(dist: Dist, excluded: dict[str, str]) -> list[str]:
    return [f for f in dist.files
            if not _is_noise(f) and not _is_test(f) and not _excluded(f"site-packages/{f}", excluded)]


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _copy_distributions(names, dists: dict[str, Dist], stage: Path, site: Path, excluded) -> int:
    copied = 0
    for name in sorted(names):
        for rel in dist_files(dists[name], excluded):
            source = stage / rel
            if source.is_file():
                _copy_file(source, site / rel)
                copied += 1
    return copied


def write_pack(manifest, pack: str, names: set[str], dists: dict[str, Dist], stage: Path, out: Path,
               target: str, python_version: str) -> dict:
    """An engine pack directory: ``site-packages/`` holding only ``names``, and its record."""
    if out.exists():
        shutil.rmtree(out)
    copied = _copy_distributions(names, dists, stage, out / "site-packages", manifest.excluded_data)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=True).stdout.strip()
    record = {"schema": 1, "pack": pack, "profile": manifest.profile, "target": target,
              "python_version": python_version, "commit": commit,
              "extras": list(manifest.packaging_packs[pack]), "env": ENGINE_PACKS_ENV,
              "distributions": {n: dists[n].version for n in sorted(names)}, "files": copied}
    (out / PACK_MANIFEST).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def verify_pack(pack_dir: Path, core_dir: Path, manifest) -> list[str]:
    """The pack holds exactly what the closure ships with its extras and the core bundle lacks."""
    record = json.loads((pack_dir / PACK_MANIFEST).read_text(encoding="utf-8"))
    site, core_site = pack_dir / "site-packages", core_dir / "site-packages"
    names, refused = pack_distributions(manifest, record["pack"], [site, core_site], record["target"],
                                        record["python_version"])
    plan = Plan(profile=manifest.profile, target=record["target"], python_version=record["python_version"],
                first_party=set(), pinned=set(), distributions=names, refusals=refused)
    site_files = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    return compare(plan, set(), read_site(site), site_files, manifest.excluded_data,
                   baked=(pack_dir / BAKED_MARKER).is_file())


def write_bundle(plan: Plan, manifest, dists: dict[str, Dist], stage: Path, out: Path,
                 index: dict[str, Path]) -> dict:
    if out.exists():
        shutil.rmtree(out)
    app, site = out / "app", out / "site-packages"
    tracked = tracked_files()
    rels = first_party_files(plan, index, tracked, manifest.packaging_resources, manifest.excluded_data)
    for rel in rels:
        _copy_file(ROOT / rel, app / rel)
    from scripts.build.agent import write_metadata

    write_metadata(ROOT / "pyproject.toml", app)
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                                capture_output=True, text=True, check=True).stdout.strip())
    # The build stamp a checkout-less Hermes reads (agent_runtime.build_stamp, beside the package).
    (app / BUILD_SHA_FILE).write_text(commit + "\n", encoding="utf-8")
    third_party = _copy_distributions(plan.distributions, dists, stage, site, manifest.excluded_data)
    if manifest.packaging_packs:
        (site / ENGINE_PACKS_PTH).write_text(ENGINE_PACKS_PTH_LINE, encoding="utf-8")
    record = {
        "schema": 1, "profile": plan.profile, "target": plan.target, "python_version": plan.python_version,
        "commit": commit, "dirty": dirty,
        "first_party_modules": len(plan.first_party), "first_party_files": len(rels),
        "switched_off_modules_shipped": sorted(plan.pinned),
        "distributions": {n: dists[n].version for n in sorted(plan.distributions)},
        "third_party_files": third_party,
        "excluded_data": dict(manifest.excluded_data),
    }
    (out / BUNDLE_MANIFEST).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


# -- phase 4: verify (plan D4) ---------------------------------------------------------------


def compare(plan: Plan, app_modules: set[str], site_dists: dict[str, Dist], site_files: set[str],
            excluded: dict[str, str], baked: bool = False, app_files: set[str] = frozenset()) -> list[str]:
    """Every way the bundle differs from its plan, one line each (empty = matches)."""
    problems = [f"closure refuses the profile's packaging: {line}" for line in plan.refusals]
    for module in sorted(app_modules - plan.first_party):
        problems.append(f"extra first-party module (outside the closure): {module}")
    for module in sorted(plan.first_party - app_modules):
        problems.append(f"missing first-party module (the closure needs it): {module}")
    for name in sorted(set(site_dists) - plan.distributions):
        problems.append(f"extra distribution (outside the closure): {name}")
    for name in sorted((plan.distributions - set(site_dists)) | plan.missing):
        problems.append(f"missing distribution (the closure needs it): {name}")
    owned = {f for d in site_dists.values() for f in d.files}
    for rel in sorted(site_files):
        if rel.split("/")[0].endswith(".dist-info"):
            continue
        if _is_noise(rel):
            if not baked:
                problems.append(f"bytecode noise in site-packages: {rel}")
        elif _is_test(rel):
            problems.append(f"test file in site-packages: {rel}")
        elif _excluded(f"site-packages/{rel}", excluded):
            problems.append(f"excluded data shipped: site-packages/{rel}")
        elif rel not in owned and rel not in PACKAGER_FILES:
            problems.append(f"file owned by no bundled distribution: {rel}")
    for rel in sorted(app_files):
        if _is_noise(rel):
            if not baked:
                problems.append(f"bytecode noise in app: {rel}")
        elif _is_test(rel):
            problems.append(f"test file in app: {rel}")
        elif _excluded(f"app/{rel}", excluded):
            problems.append(f"excluded data shipped: app/{rel}")
    return problems


#: A named zone the bundle must resolve. Windows has no system timezone database, so stdlib
#: ``zoneinfo`` reads the ``tzdata`` distribution (``hermes_time``, cron's named timezones).
NAMED_TIMEZONE = "America/New_York"
_TIMEZONE_PROBE = (
    "import sys, zoneinfo; sys.path.insert(0, sys.argv[1]); zoneinfo.reset_tzpath(()); "
    "zoneinfo.ZoneInfo(sys.argv[2])")


def named_timezone_problems(site: Path, python: Path | str = sys.executable) -> list[str]:
    """``zoneinfo`` resolves :data:`NAMED_TIMEZONE` from ``site`` alone (``-I -S``, no TZPATH)."""
    done = subprocess.run([str(python), "-I", "-S", "-B", "-c", _TIMEZONE_PROBE, str(site), NAMED_TIMEZONE],
                          capture_output=True, text=True, timeout=120)
    if done.returncode == 0:
        return []
    last = (done.stderr.strip().splitlines() or ["(no output)"])[-1]
    return [f"named timezone {NAMED_TIMEZONE} does not resolve inside the bundle: {last}"]


def verify_bundle(out: Path, manifest, index: dict[str, Path] | None = None) -> list[str]:
    """Recompute the plan from the source tree and the bundle's OWN site-packages; compare."""
    record = json.loads((out / BUNDLE_MANIFEST).read_text(encoding="utf-8"))
    site, app = out / "site-packages", out / "app"
    plan = make_plan(manifest, site, record["target"], record["python_version"], index=index)
    site_files = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    app_files = {p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file()}
    # The bundle's modules, named by the same indexer the walk uses.
    app_modules = set(module_index(app, plugins=manifest.packaging_plugins))
    problems = compare(plan, app_modules, read_site(site), site_files, manifest.excluded_data,
                       baked=(out / BAKED_MARKER).is_file(), app_files=app_files)
    if record["target"].startswith("win32"):  # other targets read the system zone database
        problems += named_timezone_problems(site)
    return problems


def bake_dir(directory: Path, python: Path) -> None:
    """Compile with the TARGET interpreter (``unchecked-hash``), as upstream's payload does."""
    subprocess.run([str(python), "-I", "-m", "compileall", "-q", "--invalidation-mode", "unchecked-hash",
                    str(directory)], check=False, timeout=1800, stdin=subprocess.DEVNULL)


def bake(out: Path, python: Path) -> int:
    for sub in ("app", "site-packages"):
        bake_dir(out / sub, python)
    (out / BAKED_MARKER).write_text("unchecked-hash\n", encoding="utf-8")
    return sum(1 for _ in out.rglob("*.pyc"))


def locked_python_version() -> str:
    """``3.14.7`` from the bundle interpreter lock (``3.14.7+20260901``)."""
    lock = ROOT / "agent_runtime" / "bundle_profiles" / "interpreters.lock.json"
    return json.loads(lock.read_text(encoding="utf-8"))["version"].split("+")[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-desktop")
    parser.add_argument("--target", choices=sorted(TARGETS))
    parser.add_argument("--python-version", default=locked_python_version(),
                        help="target CPython (default: agent_runtime/bundle_profiles/interpreters.lock.json)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stage", type=Path, help="pool directory (default: OUT.pool)")
    parser.add_argument("--reuse-stage", action="store_true", help="skip phase 1 if the stage exists")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--uv", default=os.environ.get("UV", "uv"))
    parser.add_argument("--bake-with", type=Path, help="target interpreter to compile bytecode with")
    parser.add_argument("--verify", type=Path, help="only verify an existing bundle directory")
    parser.add_argument("--verify-pack", type=Path, help="only verify an engine pack (with --verify's core)")
    args = parser.parse_args(argv)

    from agent_runtime.bundle_profiles.manifest import load_profile

    manifest = load_profile(args.profile)
    index = module_index(plugins=manifest.packaging_plugins)
    if args.verify_pack:
        if not args.verify:
            parser.error("--verify-pack needs --verify <core bundle>")
        problems = verify_pack(args.verify_pack, args.verify, manifest)
        for line in problems:
            print(line)
        print(f"pack {'MATCHES' if not problems else 'DOES NOT MATCH'} manifest {args.profile}: "
              f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if args.verify:
        problems = verify_bundle(args.verify, manifest, index)
        for line in problems:
            print(line)
        print(f"bundle {'MATCHES' if not problems else 'DOES NOT MATCH'} manifest {args.profile}: "
              f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if not args.target or not args.out:
        parser.error("--target and --out are required to build")
    stage = args.stage or args.out.with_name(args.out.name + ".pool")
    if not (args.reuse_stage and stage.is_dir()):
        pack_extras = tuple(e for extras in manifest.packaging_packs.values() for e in extras)
        install_pool(export_requirements((*manifest.packaging_extras, *pack_extras), args.uv), stage,
                     args.target, args.python_version, args.uv, args.offline)
    plan = make_plan(manifest, stage, args.target, args.python_version, index=index)
    if plan.missing or plan.refusals:
        for name in sorted(plan.missing):
            print(f"the closure needs {name}; the pool does not hold it")
        for line in plan.refusals:
            print(f"closure refusal: {line}")
        print("the pool does not satisfy the closure: ship the extra that declares it "
              "(packaging.extras), or fix the refusal")
        return 1
    record = write_bundle(plan, manifest, read_site(stage), stage, args.out, index)
    if args.bake_with:
        record["baked_pyc"] = bake(args.out, args.bake_with)
    problems = verify_bundle(args.out, manifest, index)
    print(f"packaged {record['first_party_files']} first-party files, "
          f"{len(record['distributions'])} distributions ({record['third_party_files']} files) -> {args.out}")
    dists = read_site(stage)
    for pack in manifest.packaging_packs:
        names, refused = pack_distributions(manifest, pack, [stage], args.target, args.python_version)
        absent = sorted(names - set(dists))
        if absent or refused:
            problems += [f"engine pack {pack}: the pool does not hold {n}" for n in absent]
            problems += [f"engine pack {pack}: closure refusal: {r}" for r in refused]
            continue
        pack_out = args.out.with_name(f"{args.out.name}-{pack}-pack")
        pack_record = write_pack(manifest, pack, names, dists, stage, pack_out, args.target, args.python_version)
        if args.bake_with:
            bake_dir(pack_out / "site-packages", args.bake_with)
            (pack_out / BAKED_MARKER).write_text("unchecked-hash\n", encoding="utf-8")
        pack_problems = verify_pack(pack_out, args.out, manifest)
        problems += [f"engine pack {pack}: {line}" for line in pack_problems]
        print(f"engine pack {pack}: {len(pack_record['distributions'])} distributions "
              f"({pack_record['files']} files) -> {pack_out}")
    for line in problems:
        print(line)
    print(f"verify: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
