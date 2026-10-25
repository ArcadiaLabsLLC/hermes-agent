"""Phase 4 of the packager, verify (plan D4): the bundle matches its manifest.

Split out of ``scripts/bundle_profile_package.py`` (W0-G1 size ceiling, row RT-PACKAGER-CEILING-800).
:func:`verify_bundle` recomputes the plan from the source tree and the bundle's OWN metadata and
reports anything extra or missing; :func:`verify_pack` does the same for an engine pack.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent.skill_utils import parse_frontmatter
from agent_runtime.bundle_profiles.forced_tree import FORCED_TREE_DIR
from scripts.bundle_licenses import licence_problems
from scripts.bundle_profile_closure import module_index
from scripts.bundles.bundle_files import (
    BAKED_MARKER, BUNDLE_MANIFEST, PACK_MANIFEST, PACKAGER_FILES, Dist, _excluded, _in_resource, _is_noise,
    _is_test, _platforms, _resource_file, read_site, skill_ships, tracked_files)
from scripts.bundles.plan import CORE, Plan, make_plan, pack_distributions, pack_from_plans, pack_selections
from scripts.bundles.serve_probe import named_timezone_problems, serve_import_problems


def resource_problems(app_files: set[str], tracked: list[str], resources: tuple[str, ...],
                      excluded: dict[str, str], skill_platforms: tuple[str, ...] = (),
                      skill_names: tuple[str, ...] = (), app_dir: Path | None = None) -> list[str]:
    """Every ``packaging.resources`` entry ships, file for file, what the packager selects for it
    (``skills/`` narrowed by the profile's ``skill_platforms`` and ``skill_names``, as
    :func:`first_party_files` does); with ``app_dir``, every shipped ``SKILL.md`` under a platform
    filter names one of those platforms, so the run-time OS switch shows it."""
    problems = []
    cache: dict = {}
    for resource in resources:
        named = {rel for rel in tracked if _in_resource(rel, (resource,)) and _resource_file(rel, excluded)}
        wanted = {rel for rel in named if not rel.startswith("skills/")
                  or skill_ships(rel, skill_platforms, _cache=cache, skill_names=skill_names)}
        if not named:  # a resource naming nothing is a typo; a platform filter selecting no skill is not
            problems.append(f"resource selects no tracked file: {resource}")
        for rel in sorted(wanted - app_files):
            problems.append(f"missing resource file ({resource}): app/{rel}")
    shipped_skills = sorted(rel for rel in app_files if rel.startswith("skills/") and rel.endswith("/SKILL.md"))
    for rel in shipped_skills if app_dir is not None and skill_platforms else ():
        listed = {p.lower() for p in _platforms(parse_frontmatter((app_dir / rel).read_text(encoding="utf-8-sig"))[0])}
        if listed and not listed & {p.lower() for p in skill_platforms}:
            problems.append(f"shipped skill hidden on {list(skill_platforms)}: app/{rel} names {sorted(listed)}")
    return problems


def verify_jobs(core_dir: Path, packs: list[tuple[str, Path]], manifest) -> list:
    """:func:`distribution_plans` jobs that re-plan a built core and its packs from their OWN
    metadata: the core over its site-packages, each pack over its own plus the core's."""
    core_site = core_dir / "site-packages"
    return [([core_site], {CORE: ()}),
            *(([pack_dir / "site-packages", core_site], pack_selections(manifest, [pack])) for pack, pack_dir in packs)]


def verify_pack(pack_dir: Path, core_dir: Path, manifest, plans: dict | None = None) -> list[str]:
    """The pack holds exactly what the closure ships with its extras and the core bundle lacks.
    ``plans``: this pack's job from a :func:`verify_jobs` run, when the caller has one."""
    record = json.loads((pack_dir / PACK_MANIFEST).read_text(encoding="utf-8-sig"))
    site, core_site = pack_dir / "site-packages", core_dir / "site-packages"
    if plans is None:
        names, refused = pack_distributions(manifest, record["pack"], [site, core_site], record["target"],
                                            record["python_version"])
    else:
        names, refused = pack_from_plans(plans, record["pack"])
    plan = Plan(profile=manifest.profile, target=record["target"], python_version=record["python_version"],
                first_party=set(), pinned=set(), distributions=names, refusals=refused)
    site_files = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    return compare(plan, set(), read_site(site), site_files, manifest.excluded_data,
                   baked=(pack_dir / BAKED_MARKER).is_file()) + licence_problems(pack_dir, names)


def compare(plan: Plan, app_modules: set[str], site_dists: dict[str, Dist], site_files: set[str],
            excluded: dict[str, str], baked: bool = False, app_files: set[str] = frozenset(),
            tree_modules: set[str] = frozenset()) -> list[str]:
    """Every way the bundle differs from its plan, one line each (empty = matches). ``app_modules``
    are the modules under ``app/``, ``tree_modules`` those under the sibling tree."""
    problems = [f"closure refuses the profile's packaging: {line}" for line in plan.refusals]
    for module in sorted(app_modules & plan.sibling):
        problems.append(f"forced module under the scanned app tree (the plan puts it in {FORCED_TREE_DIR}/): {module}")
    for module in sorted(tree_modules - plan.sibling):
        problems.append(f"module in {FORCED_TREE_DIR}/ the plan does not put there: {module}")
    app_modules = app_modules | tree_modules
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


def app_module_names(app: Path, plugins=(), resources: tuple[str, ...] = ()) -> set[str]:
    """The bundle's modules, named by the same indexer the walk uses. A resource's ``.py``
    (a skill script) is a shipped file, not a module, so it is not compared to the closure."""
    return {name for name, path in module_index(app, plugins=plugins).items()
            if not _in_resource(path.relative_to(app).as_posix(), resources)}


def verify_bundle(out: Path, manifest, index: dict[str, Path] | None = None,
                  python: Path | str | None = sys.executable,
                  distributions: tuple[set[str], list[str]] | None = None) -> list[str]:
    """Recompute the plan from the source tree and the bundle's OWN site-packages; compare.
    Then import the serve entrypoints with ``python`` (the bundle's interpreter), from the bundle alone;
    ``python=None`` skips that probe (a cross-target build on a host with no target interpreter).
    ``distributions``: the core's answer from a :func:`verify_jobs` run, when the caller has one."""
    record = json.loads((out / BUNDLE_MANIFEST).read_text(encoding="utf-8-sig"))
    site, app = out / "site-packages", out / "app"
    plan = make_plan(manifest, site, record["target"], record["python_version"], index=index,
                     distributions=distributions)
    site_files = {p.relative_to(site).as_posix() for p in site.rglob("*") if p.is_file()}
    app_files = {p.relative_to(app).as_posix() for p in app.rglob("*") if p.is_file()}
    app_modules = app_module_names(app, manifest.packaging_plugins, manifest.packaging_resources)
    tree = out / FORCED_TREE_DIR
    tree_modules = set(module_index(tree, plugins=manifest.packaging_plugins)) if tree.is_dir() else set()
    tree_files = {p.relative_to(tree).as_posix() for p in tree.rglob("*") if p.is_file()} if tree.is_dir() else set()
    problems = compare(plan, app_modules, read_site(site), site_files, manifest.excluded_data,
                       baked=(out / BAKED_MARKER).is_file(), app_files=app_files | tree_files,
                       tree_modules=tree_modules)
    problems += licence_problems(out, plan.distributions)
    problems += resource_problems(app_files, tracked_files(), manifest.packaging_resources,
                                  manifest.excluded_data, manifest.packaging_skill_platforms,
                                  manifest.packaging_skill_names, app)
    packs = {name: list(extras) for name, extras in manifest.packaging_packs.items()}
    if record.get("packs", {}) != packs:
        problems.append(f"bundle-manifest.json packs {record.get('packs', {})} != the profile's {packs}")
    if record["target"].startswith("win32"):  # other targets read the system zone database
        problems += named_timezone_problems(site)
    index = index if index is not None else module_index(plugins=manifest.packaging_plugins)
    if python is not None:
        problems += serve_import_problems(out, plan.first_party, index, record["python_version"], python)
    return problems
