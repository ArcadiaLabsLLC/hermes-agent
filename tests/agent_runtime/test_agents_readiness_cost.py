"""h-readiness: the ``agents_readiness`` walk pays its per-profile work once, with the same answer.

Measured on a scratch copy of the operator's store (11 runtime personas,
2026-10-05): the section cost ~780 ms a warm build. Three terms were paid per
persona per build that need not be:

* ``get_all_skills_dirs`` re-parsed each persona's ``config.yaml`` — upstream's
  config cache holds ONE entry and every persona binds a different profile;
  ``skill_resolution.skill_search_roots`` memoizes it per profile on every input
  the upstream body reads;
* ``resolve_skills`` scanned every registry entry for every name (~200 x ~1,150
  Path compares a persona) and paid a ``realpath`` per candidate; the registry
  now indexes its entries by path and carries their realpaths;
* ``runtime_environment_status`` listed site-packages once per persona; inside
  the walk it answers once per package list.

Named sabotage, one per guarantee:
* key ``skill_search_roots`` on the home alone (drop ``config_sig``) -> the
  config-edit row reds;
* drop the ``create_dir.is_dir() == existed`` re-check -> the create-dir row reds;
* make ``skill_search_roots`` return ``get_all_skills_dirs()`` unmemoized -> the
  once-per-profile count reds;
* drop the ``manifests_by_path`` lookup in ``resolve_skills`` -> the
  equivalence row reds (direct-path matches vanish);
* drop ``runtime_environment_status_scope()`` from the section -> the
  once-per-package-list count reds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent import skill_utils
from agent_runtime import skill_resolution as sr
from hermes_cli import runtime_environment as renv
from hermes_constants import reset_hermes_home_override, set_hermes_home_override


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _skill(root: Path, rel: str, *, declared: str | None = None) -> Path:
    name = Path(rel).name
    return _write(root / rel / "SKILL.md", f"---\nname: {declared or name}\n---\nbody\n")


class _home:
    """Bind a Hermes home context-locally, as ``persona_profile_scope`` does."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self):
        self.token = set_hermes_home_override(self.path)
        return self.path

    def __exit__(self, *exc) -> None:
        reset_hermes_home_override(self.token)


@pytest.fixture(autouse=True)
def _fresh_memos():
    sr._search_roots_cache_clear()
    sr._skill_root_registry_cache_clear()
    skill_utils._external_dirs_cache_clear()
    yield
    sr._search_roots_cache_clear()
    sr._skill_root_registry_cache_clear()
    skill_utils._external_dirs_cache_clear()


# --------------------------------------------------------------------------- #
# resolve_skills: same answer as the scan it replaced
# --------------------------------------------------------------------------- #


def _reference_resolve_skills(names, roots):
    """The pre-h-readiness body, verbatim in behaviour: full scans, realpath per candidate."""

    found = {name: [] for name in names}
    seen = {name: set() for name in names}

    def record(name, root, skill_dir, skill_md):
        key = sr._resolved_path(skill_md)
        if key in seen[name]:
            return
        seen[name].add(key)
        found[name].append(sr.SkillResolutionCandidate(
            root=root, skill_dir=skill_dir, skill_md=skill_md,
            source_kind=sr.skill_source_kind(root),
        ))

    for root in roots:
        registry = sr._skill_root_registry(root)
        for name in names:
            direct_manifest = root / name / "SKILL.md"
            for skill_dir, manifest in registry.manifests:
                if manifest == direct_manifest:
                    record(name, root, skill_dir, manifest)
            direct_legacy = (root / name).with_suffix(".md")
            for skill_dir, legacy in registry.legacy:
                if legacy == direct_legacy:
                    record(name, root, skill_dir, legacy)
            for skill_dir, manifest in registry.manifests_by_alias.get(name, ()):
                record(name, root, skill_dir, manifest)
            for skill_dir, legacy in registry.legacy_by_alias.get(name, ()):
                record(name, root, skill_dir, legacy)
    return {
        name: sr.SkillResolution(name, sr._skill_resolution_status(name, c), tuple(c))
        for name, c in found.items()
    }


def test_resolve_skills_matches_the_scan_it_replaced(tmp_path):
    home = tmp_path / "profiles" / "p"
    local = home / "skills"
    other = tmp_path / "external"
    _skill(local, "alpha")
    _skill(local, "cat/beta")
    _skill(local, "cat/renamed", declared="gamma")
    _skill(local, "dup")
    _skill(other, "dup")                       # collision across roots
    _skill(other, "x/alpha2", declared="alpha")  # alias collides with a direct name
    _write(local / "loose.md", "legacy flat skill")
    _write(other / "flat.md", "legacy")
    names = ["alpha", "cat/beta", "beta", "gamma", "renamed", "dup", "loose",
             "flat", "missing", "cat/renamed", "x/alpha2"]
    with _home(home):
        roots = [local, other]
        expected = _reference_resolve_skills(names, roots)
        sr._skill_root_registry_cache_clear()
        actual = sr.resolve_skills(names, roots=roots, _root_registries={})
    assert actual == expected
    statuses = {name: res.status for name, res in actual.items()}
    assert statuses["dup"] == "collision" and statuses["alpha"] == "collision"
    assert statuses["loose"] == "resolved" and statuses["missing"] == "missing"


# --------------------------------------------------------------------------- #
# skill_search_roots: once per profile, every input in the key
# --------------------------------------------------------------------------- #


def _profiles(tmp_path, count):
    homes = []
    for i in range(count):
        home = tmp_path / "profiles" / f"p{i}"
        (home / "skills").mkdir(parents=True)
        ext = tmp_path / f"ext{i}"
        ext.mkdir()
        _write(home / "config.yaml", f"skills:\n  external_dirs:\n    - {ext.as_posix()}\n")
        homes.append(home)
    return homes


def test_each_profile_config_is_parsed_once_across_builds(tmp_path, monkeypatch):
    homes = _profiles(tmp_path, 3)
    parses = []
    real_yaml_load = skill_utils.yaml_load
    monkeypatch.setattr(skill_utils, "yaml_load", lambda text: parses.append(1) or real_yaml_load(text))

    answers = {}
    for _build in range(4):
        for home in homes:  # personas bind a different profile each, in turn
            with _home(home):
                answers.setdefault(home, []).append(sr.skill_search_roots())

    assert len(parses) == len(homes), (
        f"{len(parses)} config parses for {len(homes)} profiles over 4 builds; "
        "the walk is re-reading config per persona per build"
    )
    for home in homes:
        with _home(home):
            truth = skill_utils.get_all_skills_dirs()
        assert all(answer == truth for answer in answers[home]), home


def test_a_config_edit_moves_the_answer(tmp_path):
    (home,) = _profiles(tmp_path, 1)
    added = tmp_path / "added"
    added.mkdir()
    with _home(home):
        before = sr.skill_search_roots()
        cfg = home / "config.yaml"
        cfg.write_text(cfg.read_text(encoding="utf-8") + f"    - {added.as_posix()}\n", encoding="utf-8")
        import os
        os.utime(cfg, ns=(9_000_000_000, 9_000_000_000))
        after = sr.skill_search_roots()
        assert added not in before
        assert added.resolve() in [p.resolve() for p in after]
        assert after == skill_utils.get_all_skills_dirs()


def test_a_create_dir_that_appears_is_seen(tmp_path):
    home = tmp_path / "profiles" / "p"
    (home / "skills").mkdir(parents=True)
    create = tmp_path / "made-later"
    _write(home / "config.yaml", f"skills:\n  create_dir: {create.as_posix()}\n")
    with _home(home):
        assert create.resolve() not in sr.skill_search_roots()
        create.mkdir()
        assert create.resolve() in sr.skill_search_roots()
        assert sr.skill_search_roots() == skill_utils.get_all_skills_dirs()


def test_an_env_change_moves_the_answer(tmp_path, monkeypatch):
    home = tmp_path / "profiles" / "p"
    (home / "skills").mkdir(parents=True)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _write(home / "config.yaml", "skills:\n  external_dirs:\n    - ${HR_TEST_EXT}\n")
    monkeypatch.setenv("HR_TEST_EXT", str(tmp_path / "a"))
    with _home(home):
        first = sr.skill_search_roots()
        monkeypatch.setenv("HR_TEST_EXT", str(tmp_path / "b"))
        skill_utils._external_dirs_cache_clear()  # upstream's own memo ignores env
        second = sr.skill_search_roots()
    assert (tmp_path / "a").resolve() in first
    assert (tmp_path / "b").resolve() in second


# --------------------------------------------------------------------------- #
# runtime_environment_status: once per package list inside the walk
# --------------------------------------------------------------------------- #


def test_the_status_scope_answers_once_per_package_list(monkeypatch):
    calls = []
    real = renv._runtime_environment_status
    monkeypatch.setattr(renv, "_runtime_environment_status", lambda p: calls.append(tuple(p)) or real(p))

    renv.runtime_environment_status(["openai"])
    renv.runtime_environment_status(["openai"])
    assert len(calls) == 2, "outside a scope every ask is fresh"

    calls.clear()
    with renv.runtime_environment_status_scope():
        first = renv.runtime_environment_status(["openai"])
        assert renv.runtime_environment_status(["openai"]) is first
        renv.runtime_environment_status(["anthropic"])
    assert calls == [("openai",), ("anthropic",)]


def test_the_snapshot_walk_asks_once_per_package_list_not_per_persona(
    isolate_agent_runtime_root, monkeypatch
):
    from agent_runtime import profile_readiness as pr
    from agent_runtime.models import AgentPersona
    from agent_runtime.snapshot import build_snapshot
    from agent_runtime.store import AgentStore

    for i in range(3):
        AgentStore().save(AgentPersona(
            id=f"readiness_cost_{i}", display_name=f"Cost {i}", role="qa",
            model=None, provider=None, api_mode=None, toolsets=[], system_prompt_path="",
        ))
    monkeypatch.setattr(renv, "required_packages_for", lambda **_: ["openai"])
    walks, statuses = [], []
    real_walk = pr.profile_readiness_for_persona
    real_status = renv._runtime_environment_status
    monkeypatch.setattr(pr, "profile_readiness_for_persona", lambda p, **k: walks.append(p.id) or real_walk(p, **k))
    monkeypatch.setattr(renv, "_runtime_environment_status", lambda p: statuses.append(tuple(p)) or real_status(p))

    build_snapshot()

    assert len([w for w in walks if w.startswith("readiness_cost_")]) == 3
    assert statuses == [("openai",)], (
        f"site-packages listed {len(statuses)} times for {len(walks)} personas on one package list"
    )
