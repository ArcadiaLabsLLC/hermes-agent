"""Package a bundle profile: only its import closure, for one target OS and CPython.

Fork-owned (bundled desktop, plan D1). Given a profile manifest
(``agent_runtime/bundle_profiles/<profile>.yaml``), a target (``win32-x64``,
``darwin-arm64``, ... — the target names of ``pm/lock.json``) and a CPython
version, it writes::

    OUT/
      app/                 first-party modules the closure keeps, their package
                           data, the manifest's resources, and a PEP 621
                           dist-info (upstream's ``scripts/build/agent.write_metadata``)
      phone_forced/        only with ``packaging.forced_sibling_tree``: the forced set's
                           ``tools`` / ``plugins`` modules, out of reach of upstream's
                           directory scans (``agent_runtime/bundle_profiles/forced_tree.py``)
      site-packages/       only the third-party distributions the closure needs
      bundle-manifest.json what was packaged, from which commit, for which target
      licenses.json        every shipped component's licence, licence files, wheel
                           SHA-256 and review flag (``scripts/bundle_licenses.py``)
      sbom.cdx.json        the same components as a CycloneDX 1.5 SBOM

Each engine pack directory gets its own ``licenses.json`` and ``sbom.cdx.json``.

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
   are followed with the TARGET's markers. The core and EVERY engine pack are planned by one
   child interpreter over one walk (``scripts/bundles/plan.py``); a pack is what its selection
   ships and the core's does not.
3. **Copy** — tracked first-party files only (``git ls-files``); each needed
   distribution's RECORD files minus ``__pycache__``, test directories and the
   manifest's ``packaging.excluded_data``.
4. **Verify** — ``scripts/bundles/verify.py`` recomputes the plan from the source tree
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
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.bundle_licenses import copy_first_party_licence, write_licence_records
from scripts.bundle_profile_closure import module_index
from agent_runtime.bundle_profiles.forced_tree import FORCED_TREE_DIR
from agent_runtime.bundle_profiles.manifest import PACKAGING_TARGETS, PoolScope
from scripts.bundles.bundle_files import (
    BAKED_MARKER, BUILD_SHA_FILE, BUNDLE_MANIFEST, ENGINE_PACKS_ENV, ENGINE_PACKS_PTH, ENGINE_PACKS_PTH_LINE,
    PACK_MANIFEST, Dist, _data_file, _excluded, _in_resource, _is_noise, _is_test, _resource_file, read_site,
    mark_named_skill, skill_ships, tracked_files)
from scripts.bundles.plan import (
    CORE, EXIT_RETRYABLE, Plan, PlanStalled, distribution_plans, make_plan, pack_from_plans, pack_selections)
from scripts.bundles.pool_install import install_pool as install_pool_into, remove_tree
from scripts.bundles.requirement_blocks import closure_requirements, render, requirement_blocks, seed_union
from scripts.bundles.targets import TARGETS, marker_env
from scripts.bundles.verify import verify_bundle, verify_jobs, verify_pack


#: ``(phase, seconds)`` in run order: every build prints one ``phase <name>: <s>s`` line per phase and
#: a closing ``phase total`` line, so a build log (the launcher's QA bundle log) shows where time went.
PHASE_TIMES: list[tuple[str, float]] = []


@contextmanager
def phase(name: str):
    """Time one build phase and print it the moment it ends (flushed: the log is read live)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        seconds = time.perf_counter() - start
        PHASE_TIMES.append((name, seconds))
        print(f"phase {name}: {seconds:.1f}s", flush=True)


# -- phase 1: the pool -----------------------------------------------------------------------


def export_requirements(extras: tuple[str, ...], uv: str = "uv") -> str:
    """``uv.lock``'s pins + hashes for core + ``extras`` (no resolution happens here)."""
    cmd = [uv, "export", "--frozen", "--format", "requirements.txt", "--no-emit-project",
           "--no-dev", "--no-header", "--no-annotate"]
    for extra in extras:
        cmd += ["--extra", extra]
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True, timeout=300)
    return done.stdout


def evaluate_markers(requirements: str, env: dict[str, str]) -> str:
    """Keep the requirement blocks whose marker holds for ``env``; strip the markers.

    Evaluated here, not by uv: uv's cross-target marker environment for
    ``x86_64-pc-windows-msvc`` does not report ``platform_machine == 'AMD64'``
    (measured 2026-09-28, uv 0.11.14), so ``nemo-relay``'s Windows arm silently
    dropped out of the pool. :func:`marker_env` is the one target authority.
    """
    return render([block for block in requirement_blocks(requirements) if block.holds(env)], marker=False)


def install_pool(requirements: str, stage: Path, target: str, python_version: str,
                 uv: str = "uv", offline: bool = False) -> None:
    """Install the exported pins into ``stage`` for ``target`` — hashes required, wheels only.

    uv runs into a scratch folder outside the work tree and the pool is moved into
    ``stage`` whole, with a bounded retry on a Windows sharing violation
    (``scripts/bundles/pool_install.py`` says why).
    """
    remove_tree(stage)
    stage.parent.mkdir(parents=True, exist_ok=True)
    req = stage.parent / f"{stage.name}.requirements.txt"
    req.write_text(evaluate_markers(requirements, marker_env(target, python_version)), encoding="utf-8")

    def command(into: Path) -> list[str]:
        cmd = [uv, "pip", "install", "--target", str(into), "--python-platform", TARGETS[target][0],
               "--python-version", python_version, "--no-config", "--no-deps", "--require-hashes",
               "--only-binary", ":all:", "--link-mode", "copy", "--no-compile", "-r", str(req)]
        return [*cmd, "--offline"] if offline else cmd

    install_pool_into(command, stage, cwd=ROOT)


def pool_selection(manifest, seed_sites: list[Path], target: str, python_version: str) -> tuple[set[str], list[str]]:
    """``PoolScope.CLOSURE``: the union of every selection's ``needed`` (core and each engine pack), planned
    over a SEED site whose installed metadata maps import names to distributions, and the refusals.
    Phase ``plan`` re-plans over the installed pool, so a seed that mis-maps a name is a red there."""
    return seed_union(distribution_plans(manifest.profile, [(seed_sites, pack_selections(manifest))], target, python_version)[0])


# -- phase 3: copy ---------------------------------------------------------------------------

def split_forced_tree(rels: list[str], sibling: set[str], index: dict[str, Path],
                      root: Path = ROOT) -> tuple[list[str], list[str]]:
    """-> (files for ``app/``, files for the sibling tree): a sibling module's file, and every file
    of a sibling PACKAGE's directory (its ``plugin.yaml`` and data go with its ``__init__``)."""
    if not sibling:
        return list(rels), []
    files = {index[m].relative_to(root).as_posix() for m in sibling}
    package_dirs = tuple(f.rsplit("/", 1)[0] + "/" for f in files if f.endswith("/__init__.py"))
    app, tree = [], []
    for rel in rels:
        (tree if rel in files or rel.startswith(package_dirs) else app).append(rel)
    return app, tree


def first_party_files(plan: Plan, index: dict[str, Path], tracked: list[str],
                      resources: tuple[str, ...], excluded: dict[str, str] | None = None,
                      skill_platforms: tuple[str, ...] = (), skill_names: tuple[str, ...] = ()) -> list[str]:
    """Repo-relative files: shipped modules, their packages' data files, and resources."""
    tracked_set = set(tracked)
    skill_cache: dict = {}
    rels: set[str] = set()
    package_dirs: set[str] = set()
    for module in plan.first_party:
        rel = index[module].relative_to(ROOT).as_posix()
        if rel not in tracked_set:
            raise FileNotFoundError(f"shipped module is not tracked by git: {rel}")
        rels.add(rel)
        if rel.endswith("/__init__.py"):
            package_dirs.add(rel.rsplit("/", 1)[0])
    # Every tracked package, not only the index's: a plugin directory the index cannot name
    # (``plugins/eternia-harness``) is still the package its ``plugin.yaml`` belongs to, and the
    # plugin loader errors on a shipped ``plugin.yaml`` whose ``__init__.py`` did not ship.
    all_package_dirs = {rel.rsplit("/", 1)[0] for rel in tracked if rel.endswith("/__init__.py")}
    for rel in tracked:
        parts = rel.split("/")
        if _in_resource(rel, resources):
            if _resource_file(rel, excluded or {}) and (
                    parts[0] != "skills" or skill_ships(rel, skill_platforms, _cache=skill_cache, skill_names=skill_names)):
                rels.add(rel)
            continue
        if not _data_file(rel, excluded or {}):
            continue
        # Package data: the nearest enclosing Python package must be shipped.
        for i in range(len(parts) - 1, 0, -1):
            directory = "/".join(parts[:i])
            if directory in all_package_dirs:
                if directory in package_dirs:
                    rels.add(rel)
                break
    return sorted(rels)


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
    write_licence_records(out, pack, names, target, commit, core=False)
    return record


def write_bundle(plan: Plan, manifest, dists: dict[str, Dist], stage: Path, out: Path,
                 index: dict[str, Path]) -> dict:
    if out.exists():
        shutil.rmtree(out)
    app, site = out / "app", out / "site-packages"
    tracked = tracked_files()
    rels = first_party_files(plan, index, tracked, manifest.packaging_resources, manifest.excluded_data,
                             manifest.packaging_skill_platforms, manifest.packaging_skill_names)
    app_rels, tree_rels = split_forced_tree(rels, plan.sibling, index)
    for rel in app_rels:
        _copy_file(ROOT / rel, app / rel)
        mark_named_skill(app / rel, manifest.packaging_skill_platforms, manifest.packaging_skill_names)
    for rel in tree_rels:
        _copy_file(ROOT / rel, out / FORCED_TREE_DIR / rel)
    from scripts.build.agent import write_metadata

    write_metadata(ROOT / "pyproject.toml", app)
    copy_first_party_licence(app)
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
    if manifest.packaging_packs:  # the runtime reads which pack carries which extra here
        record["packs"] = {name: list(extras) for name, extras in manifest.packaging_packs.items()}
    if plan.sibling:  # only a profile with a sibling tree records one: the desktop record is unchanged
        record["forced_tree"] = {"dir": FORCED_TREE_DIR, "modules": sorted(plan.sibling), "files": len(tree_rels)}
    (out / BUNDLE_MANIFEST).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    write_licence_records(out, "core", plan.distributions, plan.target, commit, core=True)
    return record


def bake_dir(directory: Path, python: Path) -> None:
    """Compile with the TARGET interpreter (``unchecked-hash``), as upstream's payload does."""
    subprocess.run([str(python), "-I", "-m", "compileall", "-q", "--invalidation-mode", "unchecked-hash",
                    str(directory)], check=False, timeout=1800, stdin=subprocess.DEVNULL)


def bake(out: Path, python: Path) -> int:
    for sub in ("app", "site-packages", FORCED_TREE_DIR):
        if (out / sub).is_dir():
            bake_dir(out / sub, python)
    (out / BAKED_MARKER).write_text("unchecked-hash\n", encoding="utf-8")
    return sum(1 for _ in out.rglob("*.pyc"))


def locked_python_version() -> str:
    """``3.14.7`` from the bundle interpreter lock (``3.14.7+20260901``)."""
    lock = ROOT / "agent_runtime" / "bundle_profiles" / "interpreters.lock.json"
    return json.loads(lock.read_text(encoding="utf-8-sig"))["version"].split("+")[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", default="bundled-desktop")
    parser.add_argument("--target", choices=sorted(TARGETS))
    parser.add_argument("--python-version", default=None,
                        help="target CPython (default: agent_runtime/bundle_profiles/interpreters.lock.json; "
                             "a phone target has no pin and must name it)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--stage", type=Path, help="pool directory (default: OUT.pool)")
    parser.add_argument("--reuse-stage", action="store_true", help="skip phase 1 if the stage exists")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--uv", default=os.environ.get("UV", "uv"))
    parser.add_argument("--seed-site", type=Path, action="append", dest="seed_sites", help="pool: closure's "
                        "seed plan site (repeatable; default: this interpreter's purelib, synced from the lock)")
    parser.add_argument("--bake-with", type=Path, help="target interpreter to compile bytecode with")
    parser.add_argument("--verify", type=Path, help="only verify an existing bundle directory")
    parser.add_argument("--verify-pack", type=Path, help="only verify an engine pack (with --verify's core)")
    parser.add_argument("--python", type=Path, default=None,
                        help="the bundle's interpreter, for the serve import probe (default: --bake-with, "
                             "else this interpreter; it must be the bundle's CPython X.Y)")
    parser.add_argument("--no-serve-probe", action="store_true",
                        help="skip the serve import probe (a cross-target build: this host has no "
                             "interpreter for --target); the run says so")
    args = parser.parse_args(argv)
    if args.no_serve_probe and args.python:
        parser.error("--no-serve-probe and --python contradict each other")
    if args.target in PACKAGING_TARGETS:  # a phone: the host app embeds CPython, nothing here is pinned
        if args.bake_with:
            parser.error(f"bake_refused_phone_target: {args.target} bakes with the host app's interpreter")
        if not args.python_version:
            parser.error(f"--python-version is required for the phone target {args.target}")
    args.python_version = args.python_version or locked_python_version()
    args.seed_sites = args.seed_sites or [Path(sysconfig.get_paths()["purelib"])]

    from agent_runtime.bundle_profiles.manifest import load_profile

    manifest = load_profile(args.profile)
    index = module_index(plugins=manifest.packaging_plugins)
    probe_python = None if args.no_serve_probe else (args.python or args.bake_with or Path(sys.executable))
    if probe_python is None:
        print("serve import probe: SKIPPED (--no-serve-probe)")
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
        problems = verify_bundle(args.verify, manifest, index, probe_python)
        for line in problems:
            print(line)
        print(f"bundle {'MATCHES' if not problems else 'DOES NOT MATCH'} manifest {args.profile}: "
              f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if not args.target or not args.out:
        parser.error("--target and --out are required to build")
    stage = args.stage or args.out.with_name(args.out.name + ".pool")
    started = time.perf_counter()
    try:
        return _build(args, manifest, index, stage, probe_python)
    except PlanStalled as exc:
        print(f"RETRYABLE: {exc}", flush=True)
        return EXIT_RETRYABLE
    finally:
        print(f"phase total: {time.perf_counter() - started:.1f}s", flush=True)


def _build(args, manifest, index, stage: Path, probe_python) -> int:
    selected = None  # the seed plan's union: PoolScope.CLOSURE, and only when this run builds the pool
    if not (args.reuse_stage and stage.is_dir()):
        pack_extras = tuple(e for extras in manifest.packaging_packs.values() for e in extras)
        if manifest.packaging_pool is PoolScope.CLOSURE:
            with phase("seed plan"):
                selected, refused = pool_selection(manifest, args.seed_sites, args.target, args.python_version)
        with phase("pool"):
            requirements = export_requirements((*manifest.packaging_extras, *pack_extras), args.uv)
            if selected is not None:  # a refusal returns before any install (phase plan would raise the same)
                requirements, problems, receipt = closure_requirements(
                    requirements, selected, refused, marker_env(args.target, args.python_version), args.seed_sites)
                print("\n".join([receipt, *problems]), flush=True)
                if problems:
                    return 1
            install_pool(requirements, stage, args.target, args.python_version, args.uv, args.offline)
    with phase("plan"):  # the core and every engine pack: one child, one walk
        built = distribution_plans(manifest.profile, [([stage], pack_selections(manifest))], args.target,
                                   args.python_version)[0]
        plan = make_plan(manifest, stage, args.target, args.python_version, index=index, distributions=built[CORE])
    if selected is not None:  # the pool plan proves the seed: a dist the seed missed is `plan.missing` below
        print(f"pool: seed plan {len(selected)} dists, pool plan {len(seed_union(built)[0])} dists", flush=True)
    if plan.missing or plan.refusals:
        for name in sorted(plan.missing):
            print(f"the closure needs {name}; the pool does not hold it")
        for line in plan.refusals:
            print(f"closure refusal: {line}")
        print("the pool does not satisfy the closure: ship the extra that declares it "
              "(packaging.extras), or fix the refusal")
        return 1
    with phase("copy core"):
        record = write_bundle(plan, manifest, read_site(stage), stage, args.out, index)
    if args.bake_with:
        with phase("bake core"):
            record["baked_pyc"] = bake(args.out, args.bake_with)
    print(f"packaged {record['first_party_files']} first-party files, "
          f"{len(record['distributions'])} distributions ({record['third_party_files']} files) -> {args.out}")
    dists = read_site(stage)
    pack_problems: dict[str, list[str]] = {}
    written: list[tuple[str, Path]] = []
    for pack in manifest.packaging_packs:
        names, refused = pack_from_plans(built, pack)
        absent = sorted(names - set(dists))
        if absent or refused:
            pack_problems[pack] = [*(f"engine pack {pack}: the pool does not hold {n}" for n in absent),
                                   *(f"engine pack {pack}: closure refusal: {r}" for r in refused)]
            continue
        pack_out = args.out.with_name(f"{args.out.name}-{pack}-pack")
        with phase(f"copy pack {pack}"):
            pack_record = write_pack(manifest, pack, names, dists, stage, pack_out, args.target,
                                     args.python_version)
        if args.bake_with:
            with phase(f"bake pack {pack}"):
                bake_dir(pack_out / "site-packages", args.bake_with)
                (pack_out / BAKED_MARKER).write_text("unchecked-hash\n", encoding="utf-8")
        print(f"engine pack {pack}: {len(pack_record['distributions'])} distributions "
              f"({pack_record['files']} files) -> {pack_out}")
        written.append((pack, pack_out))
    with phase("verify plan"):  # the built core and packs, re-planned from their own metadata: one child
        checked = distribution_plans(manifest.profile, verify_jobs(args.out, written, manifest), args.target,
                                     args.python_version)
    with phase("verify core"):
        problems = verify_bundle(args.out, manifest, index, probe_python, distributions=checked[0][CORE])
    for (pack, pack_out), plans in zip(written, checked[1:]):
        with phase(f"verify pack {pack}"):
            pack_problems[pack] = [f"engine pack {pack}: {line}"
                                   for line in verify_pack(pack_out, args.out, manifest, plans)]
    for pack in manifest.packaging_packs:
        problems += pack_problems.get(pack, [])
    for line in problems:
        print(line)
    print(f"verify: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
