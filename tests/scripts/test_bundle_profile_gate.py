"""The profile gate (plan Stage 2 step 4): what it refuses in a kept module's source and in a
shipped distribution, and what it lets through. The phone profile's CURRENT refusal list is a
work list recorded by the gate's own run (``docs/downstream/bundled-phone-gate-2026-09-28.md``),
never frozen here.
"""

from __future__ import annotations

import textwrap

from scripts.bundle_profile_gate import distribution_findings, is_pure, module_findings


def _findings(tmp_path, source: str) -> list[tuple[str, str]]:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return [(f["kind"], f["subject"]) for f in module_findings("pkg.mod", path)]


def test_a_spawn_call_is_refused_however_it_is_spelled(tmp_path):
    source = """
        import subprocess
        import subprocess as sp
        from subprocess import check_output as co
        import os

        def a():
            subprocess.run(["git"])
            sp.Popen(["x"])
            co(["y"])
            os.system("z")
    """
    assert sorted(_findings(tmp_path, source)) == [
        ("subprocess_call", "os.system"), ("subprocess_call", "subprocess.Popen"),
        ("subprocess_call", "subprocess.check_output"), ("subprocess_call", "subprocess.run")]


def test_importing_subprocess_without_calling_a_spawner_is_allowed(tmp_path):
    source = """
        import subprocess

        def a(exc):
            return isinstance(exc, subprocess.CalledProcessError), subprocess.PIPE
    """
    assert _findings(tmp_path, source) == []


def test_a_pty_import_is_refused_unless_an_import_error_guard_absorbs_it(tmp_path):
    guarded = """
        try:
            import pty
        except ImportError:
            pty = None
    """
    unguarded = """
        import termios
    """
    assert _findings(tmp_path, guarded) == []
    assert _findings(tmp_path, unguarded) == [("process", "termios")]


def _wheel(tag: str) -> dict:
    return {"url": f"https://files/x-1.0-{tag}.whl"}


def test_a_compiled_distribution_is_refused_unless_the_profile_admits_it():
    lock = {
        "requests": {"wheels": [_wheel("py3-none-any")]},
        "pydantic-core": {"wheels": [_wheel("cp314-cp314-win_amd64"), _wheel("cp314-cp314-manylinux_2_17_x86_64")]},
        "pillow": {"wheels": [_wheel("cp314-cp314-win_amd64")]},
        "openai": {"wheels": [_wheel("py3-none-any")]},
        "psutil": {"wheels": [_wheel("cp37-abi3-win_amd64")]},
        "mystery": {},
    }
    shipped = set(lock) | {"unlocked"}

    rows = {(f["kind"], f["subject"]) for f in distribution_findings(shipped, lock, {"pillow": "why"})}

    assert rows == {("native", "pydantic-core"), ("provider_sdk", "openai"), ("process", "psutil"),
                    ("native", "psutil"), ("unproven", "mystery"), ("unproven", "unlocked")}
    # Positive control: pillow is compiled, so without the admission it is refused too.
    assert ("native", "pillow") in {(f["kind"], f["subject"]) for f in distribution_findings(shipped, lock, {})}


def test_purity_is_read_off_the_locked_wheels():
    assert is_pure({"wheels": [_wheel("cp314-cp314-win_amd64"), _wheel("py3-none-any")]}) is True
    assert is_pure({"wheels": [_wheel("cp314-cp314-win_amd64")]}) is False
    assert is_pure({"sdist": {"url": "x.tar.gz"}}) is None


def test_the_walk_enters_a_kept_modules_enclosing_packages_when_asked(tmp_path):
    """Importing ``pkg.sub`` runs ``pkg/__init__`` first, so its imports are reached too."""
    from scripts.bundle_profile_closure import Walk, module_index

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("import heavy\n", encoding="utf-8")
    (pkg / "sub.py").write_text("import light\n", encoding="utf-8")
    index = module_index(tmp_path)

    assert set(Walk(("pkg.sub",), (), index, {"pkg"}, parents=True).tops) == {"heavy", "light"}
    # Control: the desktop closure's default walk does not (its recorded figures predate the option).
    assert set(Walk(("pkg.sub",), (), index, {"pkg"}).tops) == {"light"}


def test_a_skill_ships_to_a_phone_only_when_its_frontmatter_names_a_phone(tmp_path):
    from scripts.bundle_profile_package import skill_ships

    for name, platforms in (("marked", "[linux, android]"), ("unmarked", None)):
        skill = tmp_path / "skills" / "cat" / name
        skill.mkdir(parents=True)
        front = f"platforms: {platforms}\n" if platforms else ""
        (skill / "SKILL.md").write_text(f"---\nname: {name}\n{front}---\nbody\n", encoding="utf-8")

    phone = ("android", "ios")
    assert skill_ships("skills/cat/marked/SKILL.md", phone, root=tmp_path, _cache={})
    assert not skill_ships("skills/cat/unmarked/SKILL.md", phone, root=tmp_path, _cache={})
    # Control: a profile with no skill filter ships both.
    assert skill_ships("skills/cat/unmarked/SKILL.md", (), root=tmp_path, _cache={})


def test_markers_are_evaluated_for_the_profiles_target(tmp_path):
    from scripts.bundle_profile_closure import TARGETS, declared

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(textwrap.dedent('''
        [project]
        name = "hermes-agent"
        dependencies = ["pywin32>=1; sys_platform == 'win32'", "ptyprocess>=1; sys_platform != 'win32'", "httpx>=1"]
    '''), encoding="utf-8")

    assert declared(pyproject, env=TARGETS["android_arm64"])[0] == {"ptyprocess", "httpx"}
    assert declared(pyproject, env=TARGETS["ios_arm64"])[0] == {"ptyprocess", "httpx"}
    assert declared(pyproject)[0] == {"pywin32", "httpx"}  # control: the desktop default


def test_the_phone_profile_names_only_known_targets():
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_closure import TARGETS

    targets = load_profile("bundled-phone").packaging_targets
    assert targets and set(targets) <= set(TARGETS)
