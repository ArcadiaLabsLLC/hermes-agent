"""The bundle packaging step: the bundle matches its manifest's closure (plan D1/D4).

The heavy phases (uv pool, closure over the pool, file copy) are exercised by
the measured build in ``docs/downstream/bundled-desktop-closure-2026-09-28.md``;
these pin the pure decisions — how a bundle is compared with its plan, which
first-party modules the plan ships, and which locked requirements a target keeps.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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

    version = f"{sys.version_info.major}.{sys.version_info.minor}.0"
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


def test_a_cross_target_run_can_skip_the_serve_probe_and_says_so(monkeypatch, capsys, tmp_path: Path):
    # 2026-10-02 (pin 0b6560d1a4): `--target linux-x64` on Windows wrote complete outputs, then
    # red on "serve import probe needs a CPython 3.14 interpreter (--python)" with no way past it.
    import scripts.bundle_profile_package as pkg

    seen: list = []
    monkeypatch.setattr(pkg, "module_index", lambda **_kw: {})
    monkeypatch.setattr(pkg, "verify_bundle", lambda out, manifest, index, python: seen.append(python) or [])
    assert pkg.main(["--verify", str(tmp_path), "--no-serve-probe"]) == 0
    assert seen == [None]
    assert "serve import probe: SKIPPED (--no-serve-probe)" in capsys.readouterr().out
    assert pkg.main(["--verify", str(tmp_path)]) == 0 and seen[-1] is not None  # positive control
    with pytest.raises(SystemExit):
        pkg.main(["--verify", str(tmp_path), "--no-serve-probe", "--python", "py"])


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


def test_the_phone_targets_have_marker_environments():
    """RT-BUNDLED-PHONE-PROFILE S1: ``--profile bundled-phone --target android_arm64`` was a KeyError in
    ``marker_env``; the profile's ``packaging.targets`` was read by the gate, never by the packager.

    Killing mutation: drop the ``android_arm64`` row from ``TARGETS`` -> KeyError, red."""
    from agent_runtime.bundle_profiles.manifest import PACKAGING_TARGETS
    from scripts.bundle_profile_package import TARGETS

    android = marker_env("android_arm64", "3.14")
    assert android["sys_platform"] == "android" and android["platform_system"] == "Android"
    assert android["platform_machine"] == "aarch64" and android["python_full_version"] == "3.14.0"
    ios = marker_env("ios_arm64", "3.14.7")
    assert ios["sys_platform"] == "ios" and ios["platform_machine"] == "arm64"
    assert TARGETS["android_arm64"][0] == "aarch64-linux-android" and TARGETS["ios_arm64"][0] == "arm64-apple-ios"
    assert set(PACKAGING_TARGETS) <= set(TARGETS)
    exported = "ptyprocess==0.7.0 ; sys_platform == 'android' \\\n    --hash=sha256:bb\n"
    assert "ptyprocess==0.7.0" in evaluate_markers(exported, android)
    assert "ptyprocess" not in evaluate_markers(exported, ios)


def test_a_requirement_with_no_hash_lines_keeps_no_continuation():
    """S3's first phone run (android_arm64): uv.lock pins ``psutil @ git+…`` for ``sys_platform ==
    'android'`` on one line with no hashes; the kept head got a trailing backslash that swallowed the
    next requirement (uv: "Expected end of input or `;`, found `p`").
    Killing mutation: always append the continuation -> red."""
    exported = ("psutil @ git+https://github.com/giampaolo/psutil.git@380bd2b ; sys_platform == 'android'\n"
                "ptyprocess==0.7.0 ; sys_platform != 'win32' \\\n    --hash=sha256:bb\n")
    kept = evaluate_markers(exported, marker_env("android_arm64", "3.14")).splitlines()
    assert kept[0] == "psutil @ git+https://github.com/giampaolo/psutil.git@380bd2b"
    assert kept[1] == "ptyprocess==0.7.0 \\" and kept[2] == "    --hash=sha256:bb"


_THREE_BLOCKS = ("idna==3.19 \\\n    --hash=sha256:cc\n"
                 "Markdown-It-Py==4.0.0 ; python_full_version >= '3.10' \\\n    --hash=sha256:dd \\\n"
                 "    --hash=sha256:ee\n"
                 "psutil @ git+https://github.com/giampaolo/psutil.git@380bd2b ; sys_platform == 'android'\n")


def test_requirement_blocks_are_typed_by_their_normalised_distribution_name():
    from scripts.bundles.requirement_blocks import requirement_blocks

    blocks = requirement_blocks(_THREE_BLOCKS)
    assert [b.name for b in blocks] == ["idna", "markdown-it-py", "psutil"]
    assert blocks[1].marker == "python_full_version >= '3.10'"
    assert blocks[1].hashes == ("    --hash=sha256:dd \\", "    --hash=sha256:ee")
    assert blocks[2].head == "psutil @ git+https://github.com/giampaolo/psutil.git@380bd2b" and not blocks[2].hashes


def test_a_selection_keeps_only_named_blocks_and_refuses_a_selected_hashless_pin():
    """Plan bundled-phone-pool-2026-10-22 S2: a closure pool installs only the blocks the closure
    names, markers and hashes intact (``evaluate_markers`` still applies after); a selected block
    with no hash lines is refused by name instead of failing inside uv's ``--require-hashes``; an
    unselected hashless block is never judged.

    Killing mutation: drop the hash check in ``select_blocks`` -> the refusal assertion reds."""
    from scripts.bundles.requirement_blocks import requirement_blocks, select_blocks

    blocks = requirement_blocks(_THREE_BLOCKS)
    text, refused = select_blocks(blocks, {"idna", "markdown_it_py"})
    assert text == ("idna==3.19 \\\n    --hash=sha256:cc\n"
                    "Markdown-It-Py==4.0.0 ; python_full_version >= '3.10' \\\n    --hash=sha256:dd \\\n"
                    "    --hash=sha256:ee\n") and refused == []
    assert evaluate_markers(text, marker_env("ios_arm64", "3.14")).startswith("idna==3.19 \\\n")
    _text, refused = select_blocks(blocks, {"idna", "psutil"})
    assert refused == ["pool_pin_unhashed: psutil @ git+https://github.com/giampaolo/psutil.git@380bd2b"]


def test_a_phone_target_refuses_bake_with_and_names_its_python(monkeypatch, capsys, tmp_path: Path):
    """S2: the phone interpreter is the host app's; the desktop lock's version and ``--bake-with`` are
    desktop-only. Killing mutation: drop the ``bake_refused_phone_target`` refusal -> no SystemExit, red."""
    import scripts.bundle_profile_package as pkg

    monkeypatch.setattr(pkg, "module_index", lambda **_kw: {})
    out = str(tmp_path / "core")
    with pytest.raises(SystemExit):
        pkg.main(["--profile", "bundled-phone", "--target", "ios_arm64", "--python-version", "3.14",
                  "--bake-with", "python", "--out", out])
    assert "bake_refused_phone_target: ios_arm64" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        pkg.main(["--profile", "bundled-phone", "--target", "android_arm64", "--out", out])
    assert "--python-version is required for the phone target android_arm64" in capsys.readouterr().err
    seen: list = []
    monkeypatch.setattr(pkg, "_build", lambda args, *_a: seen.append(args.python_version) or 0)
    assert pkg.main(["--profile", "bundled-phone", "--target", "android_arm64", "--python-version", "3.14",
                     "--out", out, "--no-serve-probe"]) == 0
    assert pkg.main(["--target", "win32-x64", "--out", out, "--no-serve-probe"]) == 0  # desktop: the lock
    assert seen == ["3.14", pkg.locked_python_version()]


def test_a_profile_naming_a_target_the_packager_lacks_is_refused():
    from agent_runtime.bundle_profiles.manifest import (
        ProfileManifestError, load_profile, parse_manifest, validate_manifest)

    phone = load_profile("bundled-phone")
    assert set(phone.packaging_targets) == {"android_arm64", "ios_arm64"}  # positive control: it validates
    data = {"schema_version": 1, "profile": "watch", "packaging": {"targets": ["watchos_arm64"]}}
    with pytest.raises(ProfileManifestError, match="watchos_arm64"):
        validate_manifest(parse_manifest(data, validate=False))


def test_the_engine_pack_path_file_adds_only_installed_packs(tmp_path: Path, monkeypatch):
    import os
    import sys

    from scripts.bundle_profile_package import ENGINE_PACKS_ENV, ENGINE_PACKS_PTH_LINE

    pack, missing = tmp_path / "speech" / "site-packages", tmp_path / "absent" / "site-packages"
    pack.mkdir(parents=True)
    monkeypatch.setenv(ENGINE_PACKS_ENV, os.pathsep.join([str(pack), str(missing)]))
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert ENGINE_PACKS_PTH_LINE.startswith("import ")  # site only executes .pth lines that do
    exec(ENGINE_PACKS_PTH_LINE)  # exactly what site.addpackage runs
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


PLUGIN_TREE = ["plugins/__init__.py", "plugins/README.md",
               "plugins/eternia-harness/__init__.py", "plugins/eternia-harness/plugin.yaml"]


def test_a_plugin_s_manifest_ships_only_with_its_code():
    """The plugin loader errors on a ``plugin.yaml`` whose ``__init__.py`` did not ship ("No
    __init__.py"): a plugin directory is its manifest's package even when the index cannot name
    it (hyphenated, unlisted), so the enclosing ``plugins`` package does not carry it as data."""
    from scripts.bundle_profile_closure import ROOT
    from scripts.bundle_profile_package import first_party_files

    index = {"plugins": ROOT / "plugins/__init__.py"}  # an unlisted hyphenated plugin: not indexed
    assert first_party_files(_plan({"plugins"}, set()), index, PLUGIN_TREE, ()) == [
        "plugins/README.md", "plugins/__init__.py"]
    # Positive control: the plugin's code ships (listed, so indexed), so its manifest does.
    index["plugins.eternia_harness"] = ROOT / "plugins/eternia-harness/__init__.py"
    assert first_party_files(_plan({"plugins", "plugins.eternia_harness"}, set()), index, PLUGIN_TREE, ()) == sorted(PLUGIN_TREE)


@pytest.mark.timeout(300)  # the phone walk (~40 s)
def test_the_phone_wheel_ships_what_its_registries_and_plugin_loader_import():
    """The staged phone tree (the e2e's ``_stage_phone_wheel``: the walk's kept modules plus the
    packager's file list) holds every module a kept registry imports BY NAME — read from the
    registries' own tables at run time — ``tools.web_tools``'s ``plugins.web.firecrawl.provider``,
    and no ``plugin.yaml`` without its ``__init__.py``."""
    from agent.secret_sources import registry as secret_registry
    from agent_runtime.bundle_profiles.manifest import load_profile
    from hermes_cli import plugins as plugin_context
    from scripts.bundle_profile_closure import ROOT, profile_walk
    from scripts.bundle_profile_package import _with_parents, first_party_files, tracked_files

    manifest = load_profile("bundled-phone")
    walk, index = profile_walk(manifest, parents=True)
    kept = _with_parents(set(walk.kept), index)
    off = manifest.switched_off_modules

    def is_off(name):
        return any(name == m or name.startswith(m + ".") for m in off)

    named = {row[2] for row in plugin_context._SCOPED_PROVIDER_REGISTRARS}
    named |= {row[3].partition(":")[0] for row in plugin_context._SCOPED_PROVIDER_REGISTRARS}
    named |= {row[0] for row in secret_registry._BUILTIN_SOURCES}
    assert {"hermes_cli.plugins", "agent.secret_sources.registry", "tools.web_tools"} <= kept
    assert {n for n in named if not is_off(n)} - kept == set()
    assert "plugins.web.firecrawl.provider" in kept
    plan = Plan(profile=manifest.profile, target="android_arm64", python_version="3.14", first_party=kept,
                pinned=set(), distributions=set())
    files = set(first_party_files(plan, index, tracked_files(), manifest.packaging_resources,
                                  manifest.excluded_data, manifest.packaging_skill_platforms))
    orphans = sorted(f for f in files if f.endswith("/plugin.yaml")
                     and f.rpartition("/")[0] + "/__init__.py" not in files)
    assert orphans == []
    assert "plugins/web/firecrawl/plugin.yaml" in files  # positive control: a shipped plugin's manifest
    assert (ROOT / "plugins/web/firecrawl/provider.py").is_file()


# -- the forced tree (lane G6, owner ruling 2026-09-30 option (1)) ---------------------------------


FORCED = {"tools.a", "tools.pkg", "tools.pkg.x", "tools.kept.inner", "plugins.ns.p", "plugins.ns.p.mod", "other.m"}
KEPT = {"tools", "tools.kept", "plugins", "keep"}


def test_the_forced_tree_takes_only_scanned_package_modules_with_no_kept_package_between():
    """``tools.kept.inner`` stays in ``app/``: its package's ``__path__`` is app-only, and no scan imports
    a non-entry file of a kept package. ``other.m`` is under no scanned package."""
    from agent_runtime.bundle_profiles.forced_tree import sibling_modules

    assert sibling_modules(FORCED, KEPT) == {"tools.a", "tools.pkg", "tools.pkg.x", "plugins.ns.p", "plugins.ns.p.mod"}


def test_only_a_profile_that_asks_for_the_forced_tree_gets_one():
    """The desktop profile does not set ``packaging.forced_sibling_tree``: its plan has no sibling tree,
    so its bundle is laid out exactly as before. Positive control: the same inputs with the flag set."""
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_package import forced_tree_plan

    assert load_profile("bundled-desktop", validate=False).packaging_forced_sibling_tree is False
    assert load_profile("bundled-phone", validate=False).packaging_forced_sibling_tree is True
    assert forced_tree_plan(SimpleNamespace(packaging_forced_sibling_tree=False), KEPT | FORCED, FORCED) == set()
    assert forced_tree_plan(SimpleNamespace(packaging_forced_sibling_tree=True), KEPT | FORCED, FORCED) == {
        "tools.a", "tools.pkg", "tools.pkg.x", "plugins.ns.p", "plugins.ns.p.mod"}


def test_a_forced_package_s_data_and_manifest_go_to_the_forced_tree_with_its_code():
    """A forced plugin's ``plugin.yaml`` left in ``app/plugins/`` is a manifest the loader scans with no
    ``__init__.py`` beside it; it moves with its package. A kept module's file stays."""
    from scripts.bundle_profile_closure import ROOT
    from scripts.bundle_profile_package import split_forced_tree

    index = {"plugins.ns.p": ROOT / "plugins/ns/p/__init__.py", "plugins.ns.p.mod": ROOT / "plugins/ns/p/mod.py",
             "tools.a": ROOT / "tools/a.py"}
    rels = ["plugins/__init__.py", "plugins/ns/README.md", "plugins/ns/p/__init__.py", "plugins/ns/p/mod.py",
            "plugins/ns/p/plugin.yaml", "tools/a.py", "tools/b.py"]
    app, tree = split_forced_tree(rels, set(index), index)
    assert tree == ["plugins/ns/p/__init__.py", "plugins/ns/p/mod.py", "plugins/ns/p/plugin.yaml", "tools/a.py"]
    assert app == ["plugins/__init__.py", "plugins/ns/README.md", "tools/b.py"]
    assert split_forced_tree(rels, set(), index) == (rels, [])  # no tree: every file stays in app/


def test_verify_names_a_forced_module_under_the_scanned_tree_and_a_stray_in_the_forced_tree():
    plan = _plan({"a", "tools", "tools.a"}, {"x"})
    plan.sibling = {"tools.a"}
    assert compare(plan, {"a", "tools"}, SITE, {"x/__init__.py"}, {}, tree_modules={"tools.a"}) == []  # control
    assert compare(plan, {"a", "tools", "tools.a"}, SITE, {"x/__init__.py"}, {}) == [
        "forced module under the scanned app tree (the plan puts it in phone_forced/): tools.a"]
    assert compare(plan, {"a", "tools"}, SITE, {"x/__init__.py"}, {}, tree_modules={"tools.a", "tools.b"}) == [
        "module in phone_forced/ the plan does not put there: tools.b",
        "extra first-party module (outside the closure): tools.b"]


def test_the_mounted_forced_tree_resolves_imports_the_scanned_directory_does_not_hold(tmp_path: Path):
    """The embedded entry's mount, in a child interpreter over a miniature bundle: before it the forced
    module is not importable, after it it imports from ``phone_forced/``; the scanned ``tools/`` directory
    never holds it; a second mount appends nothing; a bundle without the tree mounts nothing."""
    import subprocess
    import sys

    from scripts.bundle_profile_closure import ROOT

    _write(tmp_path, "app/tools/__init__.py", "")
    _write(tmp_path, "app/plugins/__init__.py", "")
    _write(tmp_path, "phone_forced/tools/forced.py", "WHERE = 'tree'\n")
    _write(tmp_path, "phone_forced/plugins/off/__init__.py", "")
    child = (
        "import importlib.util, json, sys\n"
        "sys.path[:0] = [sys.argv[1], sys.argv[2]]\n"
        "from agent_runtime.bundle_profiles.forced_tree import mount_forced_tree\n"
        "before = importlib.util.find_spec('tools.forced') is not None\n"
        "first, second = mount_forced_tree(), mount_forced_tree()\n"
        "import tools.forced, plugins.off\n"
        "print(json.dumps({'before': before, 'first': first, 'second': second,\n"
        "                  'origin': tools.forced.__file__, 'plugin': plugins.off.__file__}))\n")
    def run(app):
        return subprocess.run([sys.executable, "-I", "-c", child, str(app), str(ROOT)],
                              capture_output=True, text=True, timeout=120, check=False)

    done = run(tmp_path / "app")
    assert done.returncode == 0, done.stderr[-2000:]
    import json

    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["before"] is False
    assert out["first"] == [str(tmp_path / "phone_forced" / "tools"), str(tmp_path / "phone_forced" / "plugins")]
    assert out["second"] == []
    assert Path(out["origin"]) == tmp_path / "phone_forced" / "tools" / "forced.py"
    assert Path(out["plugin"]) == tmp_path / "phone_forced" / "plugins" / "off" / "__init__.py"
    assert sorted(p.name for p in (tmp_path / "app" / "tools").glob("*.py")) == ["__init__.py"]
    # Negative control: no tree beside app/, nothing is mounted and the forced module does not import.
    import shutil

    shutil.rmtree(tmp_path / "phone_forced")
    done = run(tmp_path / "app")
    assert done.returncode != 0 and "No module named 'tools.forced'" in done.stderr, done.stderr[-2000:]


def test_the_serve_import_probe_mounts_the_forced_tree(tmp_path: Path):
    """A lazy import into a forced module resolves in the probe exactly when the bundle carries the
    sibling tree — the probe mounts it as the embedded entry does."""
    import shutil
    import sys

    from scripts.bundle_profile_closure import module_index

    version = f"{sys.version_info.major}.{sys.version_info.minor}.0"
    _serve_tree(tmp_path, with_sibling=True)
    _write(tmp_path, "app/hermes_cli/harness_parts/serve/loop.py",
           "def rpc():\n    import rpc.registry\n    import tools.forced\n")
    _write(tmp_path, "app/tools/__init__.py", "")
    _write(tmp_path, "phone_forced/tools/forced.py", "")
    _write(tmp_path, "source/tools/forced.py", "")  # the checkout's copy the plan reads, outside the bundle
    index = {**module_index(tmp_path / "app"), "tools.forced": tmp_path / "source/tools/forced.py"}
    shipped = set(index)
    assert serve_import_table(shipped, index)["lazy"]["hermes_cli.harness_parts.serve.loop"] == [
        "rpc.registry", "tools.forced"]
    assert serve_import_problems(tmp_path, shipped, index, version) == []
    shutil.rmtree(tmp_path / "phone_forced")
    problems = serve_import_problems(tmp_path, shipped, index, version)
    assert len(problems) == 1 and "tools.forced" in problems[0], problems


def test_every_build_phase_prints_its_time_the_moment_it_ends(capsys):
    """The build log (the launcher's QA bundle log) shows where the time went: one
    ``phase <name>: <s>s`` line per phase, flushed as it ends, also kept in ``PHASE_TIMES``.
    Killing mutation: drop the ``print`` in ``phase`` -> red."""
    import scripts.bundle_profile_package as pkg

    before = len(pkg.PHASE_TIMES)
    with pkg.phase("plan"):
        pass
    assert capsys.readouterr().out.startswith("phase plan: ") and pkg.PHASE_TIMES[before][0] == "plan"


def _build_stubs(monkeypatch, tmp_path: Path, packs: dict):
    """``_build`` with every heavy phase stubbed: what remains is how it plans and verifies."""
    import scripts.bundle_profile_package as pkg

    calls: list = []
    written: dict = {}

    def plans(profile, jobs, target, python_version, **_kw):
        calls.append([sorted(selections) for _sites, selections in jobs])
        return [{key: ({"core-dist", *((f"{key}-dist",) if key else ())}, []) for key in selections}
                for _sites, selections in jobs]

    monkeypatch.setattr(pkg, "distribution_plans", plans)
    monkeypatch.setattr(pkg, "make_plan", lambda manifest, site, target, pv, index=None, distributions=None:
                        _plan(set(), distributions[0]))
    monkeypatch.setattr(pkg, "write_bundle", lambda *a, **k: {"first_party_files": 0, "distributions": {},
                                                               "third_party_files": 0})
    monkeypatch.setattr(pkg, "read_site", lambda site: {n: None for n in ("core-dist", *(f"{p}-dist" for p in packs))})

    def write_pack(manifest, pack, names, dists, stage, out, target, pv):
        written[pack] = names
        return {"distributions": dict.fromkeys(names, "1"), "files": 0}

    monkeypatch.setattr(pkg, "write_pack", write_pack)
    monkeypatch.setattr(pkg, "verify_bundle", lambda *a, **k: [])
    monkeypatch.setattr(pkg, "verify_pack", lambda *a, **k: [])
    from agent_runtime.bundle_profiles.manifest import PoolScope

    args = SimpleNamespace(reuse_stage=True, target="win32-x64", python_version="3.14.7", out=tmp_path / "core",
                           bake_with=None, uv="uv", offline=False, seed_sites=[tmp_path / "seed"])
    manifest = SimpleNamespace(profile="p", packaging_extras=(), packaging_packs=packs, packaging_plugins=(),
                               packaging_pool=PoolScope.EXPORT)
    (tmp_path / "core.pool").mkdir()
    return pkg, args, manifest, calls, written


def test_a_build_plans_the_core_and_every_pack_in_one_child_and_verifies_them_in_one_more(monkeypatch, capsys,
                                                                                          tmp_path: Path):
    """Lane h-bundle-speed (2026-10-16): a build with N engine packs starts TWO planning children —
    one for the core and every pack over the pool, one re-planning the written core and packs from
    their own metadata — where it used to start 2 + 4N (22 for five packs, 88 min for the QA bundle).
    Every phase prints a ``phase <name>: <s>s`` line, and the build closes with ``phase total``.

    Killing mutation: plan each pack in ``_build`` with ``pack_distributions(manifest, pack, [stage],
    …)`` again (the per-pack core recompute) -> two more children, red."""
    pkg, args, manifest, calls, written = _build_stubs(monkeypatch, tmp_path, {"a": ("x",), "b": ("y",)})
    assert pkg._build(args, manifest, {}, tmp_path / "core.pool", None) == 0
    assert calls == [[["", "a", "b"]], [[""], ["", "a"], ["", "b"]]]
    assert written == {"a": {"a-dist"}, "b": {"b-dist"}}  # a pack is what its selection adds to the core's
    out = capsys.readouterr().out
    assert [line.split(":")[0] for line in out.splitlines() if line.startswith("phase ")] == [
        "phase plan", "phase copy core", "phase copy pack a", "phase copy pack b", "phase verify plan",
        "phase verify core", "phase verify pack a", "phase verify pack b"]


def test_a_stalled_planning_child_is_stopped_and_the_build_says_retryable(monkeypatch, capsys, tmp_path: Path):
    """The closure step must not turn load into a hard failure (runtime-queue row, 2026-10-15): the
    child is stopped only when its progress report stands still, and the build exits
    ``EXIT_RETRYABLE`` with a ``RETRYABLE:`` line. Positive control: a child that keeps reporting
    NEW progress for longer than the stall window finishes and is read, and so does one whose
    first report comes later than the stall window (start-up on a loaded box is not a stall).

    Killing mutations: reset the stall clock on any progress line, not only a changed one -> the
    frozen child is stopped by the cap instead and the "no progress" assertion reds; start the
    stall clock at spawn -> the late-starting child is stopped ``(last: None)``."""
    import sys

    import scripts.bundle_profile_package as pkg

    frozen = ("import sys, time\n"
              "while True:\n    print('progress walk parses=7', file=sys.stderr, flush=True); time.sleep(0.1)\n")
    moving = ("import sys, time\n"
              "time.sleep(2)\n"
              "for n in range(30):\n    print(f'progress walk parses={n}', file=sys.stderr, flush=True); time.sleep(0.1)\n"
              "print('answer')\n")
    with pytest.raises(pkg.PlanStalled, match="no progress for 1s"):
        pkg._run_planner([sys.executable, "-c", frozen], stall=1, cap=20)
    assert pkg._run_planner([sys.executable, "-c", moving], stall=1, cap=20).strip() == "answer"

    _pkg, _args, manifest, _calls, _written = _build_stubs(monkeypatch, tmp_path, {})

    def stalled(*_a, **_k):
        raise pkg.PlanStalled("closure planning child no progress for 300s (last: progress walk parses=7)")

    monkeypatch.setattr(pkg, "distribution_plans", stalled)
    monkeypatch.setattr(pkg, "module_index", lambda **_kw: {})
    monkeypatch.setattr("agent_runtime.bundle_profiles.manifest.load_profile", lambda _name: manifest)
    assert pkg.main(["--target", "win32-x64", "--out", str(tmp_path / "core"), "--reuse-stage",
                     "--no-serve-probe"]) == pkg.EXIT_RETRYABLE
    out = capsys.readouterr().out
    assert "RETRYABLE: closure planning child no progress" in out and "phase total:" in out


_EXPORT = ("a-dist==1 \\\n    --hash=sha256:aa\n"
           "b-dist==1 \\\n    --hash=sha256:bb\n"
           "c-dist==1 \\\n    --hash=sha256:cc\n")


def _pool_stubs(monkeypatch, tmp_path: Path, scope, seed_answer: dict, pool_answer=None):
    """``_build`` from phase pool on: the export and the install stubbed, the seed child answering
    ``seed_answer`` and the pool child ``pool_answer`` (default: the ``_build_stubs`` answer)."""
    from agent_runtime.bundle_profiles.manifest import PoolScope

    pkg, args, manifest, calls, _written = _build_stubs(monkeypatch, tmp_path, {"pk": ("x",)})
    stubbed = pkg.distribution_plans
    installed: list = []

    def plans(profile, jobs, target, python_version, **kw):
        if jobs[0][0] == args.seed_sites:
            calls.append(["seed", *[sorted(selections) for _sites, selections in jobs]])
            return [{key: (set(seed_answer[key]), []) for key in jobs[0][1]}]
        if pool_answer is not None:
            calls.append([sorted(selections) for _sites, selections in jobs])
            return [{key: (set(pool_answer[key]), []) for key in selections} for _sites, selections in jobs]
        return stubbed(profile, jobs, target, python_version, **kw)

    monkeypatch.setattr(pkg, "distribution_plans", plans)
    monkeypatch.setattr(pkg, "export_requirements", lambda extras, uv="uv": _EXPORT)
    monkeypatch.setattr(pkg, "install_pool", lambda text, stage, *a: installed.append(text))
    args.reuse_stage = False
    manifest.packaging_pool = getattr(PoolScope, scope)
    return pkg, args, manifest, calls, installed


def test_a_closure_pool_installs_only_the_seed_plan_s_union(monkeypatch, capsys, tmp_path: Path):
    """Plan bundled-phone-pool-2026-10-22 S3: under ``PoolScope.CLOSURE`` one seed planning child runs
    before phase pool, and the pool installs the union of every selection's ``needed`` (core + each
    engine pack), nothing else from the export. Under ``EXPORT`` the pool is the whole export and no
    seed child starts.

    Killing mutation: ignore ``manifest.packaging_pool`` and always select -> the EXPORT case reds
    (the seed child ran)."""
    pkg, args, manifest, calls, installed = _pool_stubs(
        monkeypatch, tmp_path, "CLOSURE", {"": {"a-dist"}, "pk": {"a-dist", "b-dist"}})
    assert pkg._build(args, manifest, {}, tmp_path / "core.pool", None) == 0
    assert calls[0] == ["seed", ["", "pk"]]
    assert "a-dist==1" in installed[0] and "b-dist==1" in installed[0] and "c-dist" not in installed[0]
    out = capsys.readouterr().out
    assert [line.split(":")[0] for line in out.splitlines() if line.startswith("phase ")][:3] == [
        "phase seed plan", "phase pool", "phase plan"]
    assert "pool scope: closure — 2 of 3 export blocks (seed: " in out

    (tmp_path / "export").mkdir()
    pkg, args, manifest, calls, installed = _pool_stubs(monkeypatch, tmp_path / "export", "EXPORT",
                                                        {"": {"a-dist"}, "pk": {"a-dist"}})
    assert pkg._build(args, manifest, {}, tmp_path / "export" / "core.pool", None) == 0
    assert installed == [_EXPORT] and calls == [[["", "pk"]], [[""], ["", "pk"]]]
    assert "pool scope" not in capsys.readouterr().out


def test_the_pool_plan_proves_the_seed_a_dist_the_seed_missed_ends_the_build(monkeypatch, capsys, tmp_path: Path):
    """Plan bundled-phone-pool-2026-10-22 S4: the seed plan only chooses what the pool installs;
    phase plan re-plans over the installed pool and stays the authority. A seed answering
    ``{a-dist}`` while the pool plan needs ``{a-dist, d-dist}`` ends the build red, and the receipt
    names both counts.

    Killing mutation: skip the ``plan.missing`` check when ``packaging_pool is CLOSURE`` -> exit 0, red."""
    import scripts.bundle_profile_package as pkg

    _pkg, args, manifest, _calls, _installed = _pool_stubs(
        monkeypatch, tmp_path, "CLOSURE", {"": {"a-dist"}, "pk": {"a-dist"}},
        pool_answer={"": {"a-dist", "d-dist"}, "pk": {"a-dist", "d-dist"}})
    monkeypatch.setattr(pkg, "make_plan", lambda manifest, site, target, pv, index=None, distributions=None:
                        _plan(set(), distributions[0], missing=distributions[0] - {"a-dist"}))
    assert pkg._build(args, manifest, {}, tmp_path / "core.pool", None) == 1
    out = capsys.readouterr().out
    assert "pool: seed plan 1 dists, pool plan 2 dists" in out
    assert "the closure needs d-dist; the pool does not hold it" in out
