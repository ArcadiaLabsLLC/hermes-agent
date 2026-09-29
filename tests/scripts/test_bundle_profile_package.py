"""The bundle packaging step: the bundle matches its manifest's closure (plan D1/D4).

The heavy phases (uv pool, closure over the pool, file copy) are exercised by
the measured build in ``docs/downstream/bundled-desktop-closure-2026-09-28.md``;
these pin the pure decisions — how a bundle is compared with its plan, which
first-party modules the plan ships, and which locked requirements a target keeps.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.bundle_profile_package import (
    Dist,
    Plan,
    compare,
    evaluate_markers,
    first_party_plan,
    marker_env,
    named_timezone_problems,
    resource_problems,
    serve_import_problems,
    serve_import_table,
)


def _dist(name, files):
    return Dist(name=name, version="1", info=f"{name}-1.dist-info", files=list(files))


def _plan(first_party, distributions, missing=(), refusals=()):
    return Plan(profile="p", target="win32-x64", python_version="3.14.7", first_party=set(first_party),
                pinned=set(), distributions=set(distributions), missing=set(missing), refusals=list(refusals))


SITE = {"x": _dist("x", ["x/__init__.py"])}


def test_a_bundle_equal_to_its_plan_has_no_problems():
    """Positive control: the same inputs as the checks below, nothing extra or missing."""
    assert compare(_plan({"a", "a.b"}, {"x"}), {"a", "a.b"}, SITE, {"x/__init__.py"}, {}) == []


def test_an_extra_or_missing_first_party_module_fails():
    problems = compare(_plan({"a", "a.b"}, {"x"}), {"a", "a.c"}, SITE, {"x/__init__.py"}, {})
    assert problems == ["extra first-party module (outside the closure): a.c",
                        "missing first-party module (the closure needs it): a.b"]


def test_an_extra_or_missing_distribution_fails():
    site = {**SITE, "y": _dist("y", ["y.py"])}
    problems = compare(_plan({"a"}, {"x", "z"}, missing={"w"}), {"a"}, site, {"x/__init__.py", "y.py"}, {})
    assert problems == ["extra distribution (outside the closure): y",
                        "missing distribution (the closure needs it): w",
                        "missing distribution (the closure needs it): z"]


def test_a_closure_refusal_fails_the_bundle():
    problems = compare(_plan({"a"}, {"x"}, refusals=["omitted pillow-heif is imported unguarded"]),
                       {"a"}, SITE, {"x/__init__.py"}, {})
    assert problems == ["closure refuses the profile's packaging: omitted pillow-heif is imported unguarded"]


def test_stray_tests_noise_and_excluded_data_fail():
    files = ["x/__init__.py", "x/data/big.bin"]
    shipped = {*files, "x/tests/test_x.py", "x/__pycache__/m.cpython-314.pyc", "loose.py"}
    problems = compare(_plan({"a"}, {"x"}), {"a"}, {"x": _dist("x", files)}, shipped,
                       {"site-packages/x/data": "model", "app/tools/samples": "clips"},
                       app_files={"a.py", "tools/samples/jo.wav"})
    assert sorted(problems) == [
        "bytecode noise in site-packages: x/__pycache__/m.cpython-314.pyc",
        "excluded data shipped: app/tools/samples/jo.wav",
        "excluded data shipped: site-packages/x/data/big.bin",
        "file owned by no bundled distribution: loose.py",
        "test file in site-packages: x/tests/test_x.py",
    ]


def test_baked_bytecode_is_not_noise():
    shipped = {"x/__init__.py", "x/__pycache__/__init__.cpython-314.pyc"}
    assert compare(_plan({"a"}, {"x"}), {"a"}, SITE, shipped, {}, baked=True) == []


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_switched_off_code_kept_code_imports_unguarded_still_ships(tmp_path: Path):
    """A lazy unguarded import into a switched-off module must not become a runtime ImportError."""
    _write(tmp_path, "keep.py", "def f():\n    import off.lazy\n")
    _write(tmp_path, "off/__init__.py", "")
    _write(tmp_path, "off/lazy.py", "import off.helper\n")
    _write(tmp_path, "off/helper.py", "")
    _write(tmp_path, "off/unused.py", "")
    _write(tmp_path, "guarded.py", "try:\n    import off.unused\nexcept ImportError:\n    pass\n")
    from scripts.bundle_profile_closure import module_index

    manifest = SimpleNamespace(packaging_roots=("keep", "guarded"), switched_off_modules=("off",),
                               packaging_plugins=())
    shipped, forced, _ = first_party_plan(manifest, module_index(tmp_path))
    assert forced == {"off.lazy", "off.helper", "off"}
    assert shipped == {"keep", "guarded", "off", "off.lazy", "off.helper"}


def test_a_hyphenated_bundled_plugin_is_walked(tmp_path: Path):
    _write(tmp_path, "plugins/__init__.py", "")
    _write(tmp_path, "plugins/my-plugin/__init__.py", "from . import impl\n")
    _write(tmp_path, "plugins/my-plugin/impl.py", "")
    _write(tmp_path, "plugins/other-plugin/__init__.py", "")
    from scripts.bundle_profile_closure import module_index

    manifest = SimpleNamespace(packaging_roots=(), switched_off_modules=(), packaging_plugins=("my-plugin",))
    shipped, _, _ = first_party_plan(manifest, module_index(tmp_path, plugins=("my-plugin",)))
    assert shipped == {"plugins", "plugins.my_plugin", "plugins.my_plugin.impl"}


def test_a_package_init_s_relative_siblings_ship_with_the_module_that_enters_it(tmp_path: Path):
    """Importing ``pkg.a`` runs ``pkg/__init__`` first: its ``from . import b`` must ship ``pkg.b``."""
    _write(tmp_path, "root.py", "from pkg.a import x\n")
    _write(tmp_path, "pkg/__init__.py", "from . import a, b\n")
    _write(tmp_path, "pkg/a.py", "x = 1\n")
    _write(tmp_path, "pkg/b.py", "")
    from scripts.bundle_profile_closure import module_index

    manifest = SimpleNamespace(packaging_roots=("root",), switched_off_modules=(), packaging_plugins=())
    shipped, _, _ = first_party_plan(manifest, module_index(tmp_path))
    assert shipped == {"root", "pkg", "pkg.a", "pkg.b"}


def _serve_tree(root: Path, *, with_sibling: bool) -> None:
    """A miniature bundle: the parser door, a serve handler importing lazily into a package
    whose ``__init__`` imports a sibling with ``from . import``, and a ``-m`` worker."""
    _write(root, "app/hermes_cli/__init__.py", "")
    _write(root, "app/hermes_cli/harness_parts/__init__.py", "")
    _write(root, "app/hermes_cli/harness_parts/parser/__init__.py",
           "def build_parser(subs):\n"
           "    from hermes_cli.harness_parts.parser.machine import add_serve\n"
           "    add_serve(subs.add_parser('harness').add_subparsers())\n")
    _write(root, "app/hermes_cli/harness_parts/parser/machine.py",
           "def _cmd_serve(args):\n"
           "    from hermes_cli.harness_parts.serve.commands import run\n"
           "def add_serve(subs):\n"
           "    serve = subs.add_parser('serve')\n"
           "    serve.add_argument('--ndjson', action='store_true')\n"
           "    serve.set_defaults(func=_cmd_serve)\n")
    _write(root, "app/hermes_cli/harness_parts/serve/__init__.py", "")
    _write(root, "app/hermes_cli/harness_parts/serve/commands.py", "from . import loop\ndef run():\n    pass\n")
    _write(root, "app/hermes_cli/harness_parts/serve/loop.py", "def rpc():\n    import rpc.registry\n")
    _write(root, "app/rpc/__init__.py", "from . import chat\n")
    _write(root, "app/rpc/registry.py", "")
    if with_sibling:
        _write(root, "app/rpc/chat.py", "")
    _write(root, "app/worker.py", "ARGV = ['python', '-m', 'worker_entry']\n")
    _write(root, "app/worker_entry.py", "")
    (root / "site-packages").mkdir(parents=True, exist_ok=True)


def test_the_serve_import_probe_names_a_module_the_bundle_cannot_import(tmp_path: Path):
    """The built-bundle check: the bundle's interpreter, isolated, imports what serve loads."""
    import sys

    from scripts.bundle_profile_closure import module_index

    version = "%d.%d.0" % sys.version_info[:2]
    good, bad = tmp_path / "good", tmp_path / "bad"
    _serve_tree(good, with_sibling=True)
    _serve_tree(bad, with_sibling=False)
    index = module_index(good / "app")
    shipped = set(index)
    table = serve_import_table(shipped, index)
    assert table["spawned"] == ["worker_entry"]
    assert table["lazy"]["hermes_cli.harness_parts.serve.loop"] == ["rpc.registry"]
    assert serve_import_problems(good, shipped, index, version) == []  # positive control
    problems = serve_import_problems(bad, shipped, index, version)
    assert len(problems) == 1 and problems[0].startswith(
        "serve entrypoint does not import inside the bundle: rpc.registry: ImportError"), problems


def test_the_serve_import_probe_refuses_an_interpreter_of_another_version(tmp_path: Path):
    problems = serve_import_problems(tmp_path, set(), {}, "2.7.18")
    assert len(problems) == 1 and "needs a CPython 2.7 interpreter" in problems[0]


def test_markers_are_evaluated_for_the_target_not_by_uv():
    exported = (
        "nemo-relay==0.8.4 ; (platform_machine == 'AMD64' and sys_platform == 'win32') \\\n"
        "    --hash=sha256:aa\n"
        "ptyprocess==0.7.0 ; sys_platform != 'win32' \\\n"
        "    --hash=sha256:bb\n"
        "idna==3.19 \\\n"
        "    --hash=sha256:cc\n"
    )
    win = evaluate_markers(exported, marker_env("win32-x64", "3.14.7"))
    assert "nemo-relay==0.8.4 \\\n    --hash=sha256:aa" in win
    assert "ptyprocess" not in win and "idna==3.19" in win
    linux = evaluate_markers(exported, marker_env("linux-x64", "3.14.7"))
    assert "nemo-relay" not in linux and "ptyprocess==0.7.0" in linux


def test_the_engine_pack_path_file_adds_only_installed_packs(tmp_path: Path, monkeypatch):
    import os
    import sys

    from scripts.bundle_profile_package import ENGINE_PACKS_ENV, ENGINE_PACKS_PTH_LINE

    pack, missing = tmp_path / "speech" / "site-packages", tmp_path / "absent" / "site-packages"
    pack.mkdir(parents=True)
    monkeypatch.setenv(ENGINE_PACKS_ENV, os.pathsep.join([str(pack), str(missing)]))
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert ENGINE_PACKS_PTH_LINE.startswith("import ")  # site only executes .pth lines that do
    exec(ENGINE_PACKS_PTH_LINE)  # noqa: S102 — exactly what site.addpackage runs
    assert str(pack) in sys.path
    assert str(missing) not in sys.path


def test_the_engine_pack_path_file_is_not_a_stray_file():
    shipped = {"x/__init__.py", "hermes-engine-packs.pth"}
    assert compare(_plan({"a"}, {"x"}), {"a"}, SITE, shipped, {}) == []


def test_a_named_timezone_resolves_only_from_a_site_holding_tzdata(tmp_path: Path):
    """The built-bundle check: ``zoneinfo`` with no system TZPATH, only the bundle's site-packages."""
    import shutil

    import pytest

    tzdata = pytest.importorskip("tzdata")
    with_tz, without = tmp_path / "with", tmp_path / "without"
    shutil.copytree(Path(tzdata.__file__).parent, with_tz / "tzdata")
    without.mkdir()
    assert named_timezone_problems(with_tz) == []  # positive control
    problems = named_timezone_problems(without)
    assert len(problems) == 1 and "America/New_York" in problems[0]


SKILLS = "docs/agent-runtime-harness/harness-skills"
TRACKED = [f"{SKILLS}/harness-qa-verdict/SKILL.md", f"{SKILLS}/harness-qa-verdict/references/x.md",
           "docs/other.md", "skills/a/SKILL.md"]


def test_a_nested_resource_ships_file_for_file_or_verify_names_the_gap():
    """``--verify`` holds a repo-relative ``packaging.resources`` entry (the harness skills
    ``agent_runtime.skill_install`` reads from ``app/docs/...``) to every tracked file under it."""
    resources = (SKILLS, "skills")
    shipped = {f"{SKILLS}/harness-qa-verdict/SKILL.md", f"{SKILLS}/harness-qa-verdict/references/x.md",
               "skills/a/SKILL.md"}
    assert resource_problems(shipped, TRACKED, resources, {}) == []  # positive control
    problems = resource_problems(shipped - {f"{SKILLS}/harness-qa-verdict/SKILL.md"}, TRACKED, resources, {})
    assert problems == [f"missing resource file ({SKILLS}): app/{SKILLS}/harness-qa-verdict/SKILL.md"]
    assert resource_problems(shipped, TRACKED, (*resources, "docs/typo"), {}) == [
        "resource selects no tracked file: docs/typo"]


def test_the_packager_selects_a_nested_resource_and_nothing_beside_it():
    from scripts.bundle_profile_package import first_party_files

    plan = _plan(set(), set())
    assert first_party_files(plan, {}, TRACKED, (SKILLS,)) == sorted(TRACKED[:2])


SCRIPTED = ["skills/p/docx/SKILL.md", "skills/p/docx/scripts/render.py", "skills/p/docx/tests/test_render.py",
            "pkg/__init__.py", "pkg/loose.py"]


def test_a_skill_ships_its_scripts_but_not_its_tests():
    """A skill's ``scripts/*.py`` are resource files it runs; its tests and package ``.py``
    files outside a resource are not data."""
    from scripts.bundle_profile_package import first_party_files

    plan = _plan(set(), set())
    assert first_party_files(plan, {}, SCRIPTED, ("skills",)) == [
        "skills/p/docx/SKILL.md", "skills/p/docx/scripts/render.py"]
    assert first_party_files(plan, {}, SCRIPTED, ()) == []  # positive control: no resource, no .py


def test_verify_names_a_missing_skill_script():
    shipped = {"skills/p/docx/SKILL.md", "skills/p/docx/scripts/render.py"}
    assert resource_problems(shipped, SCRIPTED, ("skills",), {}) == []  # positive control
    assert resource_problems(shipped - {"skills/p/docx/scripts/render.py"}, SCRIPTED, ("skills",), {}) == [
        "missing resource file (skills): app/skills/p/docx/scripts/render.py"]


def test_a_shipped_skill_script_is_not_counted_as_a_module(tmp_path):
    from scripts.bundle_profile_package import app_module_names

    for rel in ("skills/p/docx/scripts/render.py", "pkg/__init__.py", "pkg/mod.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("", encoding="utf-8")
    assert app_module_names(tmp_path, (), ("skills",)) == {"pkg", "pkg.mod"}
    assert "skills.p.docx.scripts.render" in app_module_names(tmp_path, (), ())  # positive control
