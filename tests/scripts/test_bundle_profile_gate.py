"""The profile gate (plan Stage 2 step 4): what it refuses in a kept module's source and in a
shipped distribution, and what it lets through. The phone profile's CURRENT refusal list is a
work list recorded by the gate's own run (``docs/downstream/bundled-phone-gate-2026-09-28.md``),
never frozen here.
"""

from __future__ import annotations

import textwrap

import pytest

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


def test_a_pin_the_loop_placeholders_answer_is_a_seam_proven_at_run_time(tmp_path):
    """``run_agent`` imports ``cleanup_vm`` / ``get_active_env`` from the terminal lifecycle at module
    level; the phone does not ship it and ``agent_runtime.loop_tool_lifecycles`` registers a
    placeholder carrying those names. The gate asks the placeholder in a child interpreter: every name
    answered -> not pinned. A name it lacks, or a bare ``import m``, keeps the pin."""
    from types import SimpleNamespace

    from scripts.bundle_profile_gate import placeholder_seams

    sources = {
        "loop_a": "from tools.terminal_tool_lifecycle import cleanup_vm, get_active_env\n"
                  "from tools.browser_tool_lifecycle import cleanup_browser\n",
        "loop_b": "from tools.skills_hub import GitHubAuth\n",
    }
    index = {}
    for name, source in sources.items():
        index[name] = tmp_path / f"{name}.py"
        index[name].write_text(source, encoding="utf-8")
    pinned = {"tools.terminal_tool_lifecycle", "tools.browser_tool_lifecycle", "tools.skills_hub"}
    manifest = SimpleNamespace(switched_off_modules=tuple(sorted(pinned)))
    walk = SimpleNamespace(pinned=pinned, kept=set(sources))
    assert placeholder_seams(manifest, walk, index) == {
        "tools.browser_tool_lifecycle": ["cleanup_browser"],
        "tools.terminal_tool_lifecycle": ["cleanup_vm", "get_active_env"],
    }

    # A table name that is a VALUE, not a callable, resolves too: ``tools.tts_tool_lifecycle`` binds
    # the local TTS engines' model-cache mapping at module level (an empty, read-only mapping stands in).
    index["loop_b"].write_text("from tools.tts_tool_local import _LOCAL_TTS_MODEL_CACHES, _generate_piper_tts\n",
                               encoding="utf-8")
    manifest = SimpleNamespace(switched_off_modules=("tools.tts_tool_local",))
    walk = SimpleNamespace(pinned={"tools.tts_tool_local"}, kept={"loop_b"})
    assert placeholder_seams(manifest, walk, index) == {
        "tools.tts_tool_local": ["_LOCAL_TTS_MODEL_CACHES", "_generate_piper_tts"]}
    manifest = SimpleNamespace(switched_off_modules=tuple(sorted(pinned)))
    walk = SimpleNamespace(pinned=pinned, kept=set(sources))

    # Negative controls: a name the placeholder table lacks, and a bare module import, stay pinned.
    index["loop_a"].write_text("from tools.terminal_tool_lifecycle import cleanup_vm, cleanup_all_environments\n"
                               "import tools.browser_tool_lifecycle\n", encoding="utf-8")
    assert placeholder_seams(manifest, walk, index) == {}


def test_a_relative_import_is_resolved_against_the_kept_modules_package(tmp_path):
    """``from .lifecycle import x`` inside ``tools/__init__.py`` or ``tools/a.py`` names
    ``tools.lifecycle``; a guarded import and a bare ``import m`` are the two other answers."""
    from scripts.bundle_profile_gate import eager_imported_names

    pkg = tmp_path / "tools"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .lifecycle import from_init\n", encoding="utf-8")
    (pkg / "a.py").write_text(
        "from .lifecycle import from_a\n"
        "from . import lifecycle_sibling\n"
        "try:\n    from .lifecycle import guarded\nexcept ImportError:\n    guarded = None\n",
        encoding="utf-8",
    )
    (pkg / "b.py").write_text("import other.pinned\n", encoding="utf-8")
    index = {"tools": pkg / "__init__.py", "tools.a": pkg / "a.py", "tools.b": pkg / "b.py"}
    pinned = {"tools.lifecycle", "tools", "other.pinned"}
    names = eager_imported_names(pinned, ["tools", "tools.a", "tools.b"], index)
    assert names["tools.lifecycle"] == {"from_init", "from_a"}
    assert names["tools"] == {"lifecycle_sibling"}
    assert names["other.pinned"] is None


_SPAWNY = """
import subprocess

def rebound():
    subprocess.run(["git"])

def plain():
    subprocess.run(["git"])

class Owner:
    @staticmethod
    def meth():
        subprocess.run(["x"])

def outer():
    def inner():
        subprocess.run(["y"])
    return inner
"""

_SPAWNY_TABLE = """
from agent_runtime.spawn_stand_ins import StandIn

TABLE = (StandIn("spawny", "rebound"), StandIn("spawny", "Owner.meth"), StandIn("spawny", "outer", returns=None))
STALE = (*TABLE, StandIn("spawny", "renamed_upstream"))
"""


def test_a_spawn_in_a_function_the_phone_entry_rebinds_is_answered_at_run_time(tmp_path, monkeypatch):
    """``spawn_seams`` asks a child interpreter (the phone's absences, placeholders and config in
    place) whether each ``subprocess_call`` site's enclosing function IS the stand-in the phone entry
    bound for it. Answered: a rebound function, a static method, the outer def of a nested spawner.
    Not answered: a plain function. A row naming a missing function fails the probe (never a skip);
    a profile that ships a provider SDK (desktop) has nothing answered."""
    from agent_runtime.bundle_profiles.manifest import load_profile
    from scripts.bundle_profile_gate import spawn_seams

    path = tmp_path / "spawny.py"
    path.write_text(_SPAWNY, encoding="utf-8")
    (tmp_path / "spawny_table.py").write_text(_SPAWNY_TABLE, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    findings = module_findings("spawny", path)
    lines = {f["line"] for f in findings}
    assert len(findings) == 4
    phone = load_profile("bundled-phone")
    kept, answered = spawn_seams(phone, findings, {"spawny": path}, table="spawny_table:TABLE")
    assert [(f["module"], f["line"]) for f in kept] == [("spawny", 8)]  # plain()
    assert answered == {"spawny": ["5: rebound", "13: Owner.meth", "17: outer"]}
    assert lines == {5, 8, 13, 17}

    with pytest.raises(RuntimeError, match="renamed_upstream"):
        spawn_seams(phone, findings, {"spawny": path}, table="spawny_table:STALE")

    kept, answered = spawn_seams(load_profile("bundled-desktop"), findings, {"spawny": path},
                                 table="spawny_table:TABLE")
    assert (len(kept), answered) == (4, {})


def test_the_gate_runs_only_under_the_bundles_pinned_cpython_or_a_named_interpreter(tmp_path, capsys):
    """The count depends on the interpreter (s2-g1: 104 under the lane's, 106 under system 3.12), so the
    gate refuses to run anywhere but the pinned CPython's major.minor unless ``--interpreter`` names the
    one running it — and it prints the interpreter either way."""
    import json
    import sys

    from scripts.bundle_profile_gate import INTERPRETER_LOCK, interpreter_refusal, main, pinned_interpreter

    pin, want = pinned_interpreter()
    assert pin == json.loads(INTERPRETER_LOCK.read_text(encoding="utf-8"))["version"]
    assert interpreter_refusal(None, executable="py", implementation="cpython", version=want) is None
    older = interpreter_refusal(None, executable="py", implementation="cpython", version=(want[0], want[1] - 2))
    assert older and "pinned CPython" in older and pin in older
    assert interpreter_refusal(None, executable="py", implementation="pypy", version=want)
    # An explicit --interpreter is honoured only when it names the interpreter actually running.
    assert interpreter_refusal(sys.executable, implementation="cpython", version=(want[0], want[1] - 2)) is None
    assert interpreter_refusal(str(tmp_path / "other-python.exe"))

    assert main(["--interpreter", str(tmp_path / "other-python.exe")]) == 2
    out, err = capsys.readouterr()
    assert out.startswith(f"interpreter: {sys.executable} (") and "GATE NOT RUN" in err


def test_the_phones_kept_pty_and_psutil_import_sites_are_guarded():
    """Phone-gate lane G2: the tty prompt's ``termios``/``tty`` and the kept psutil sites are
    ImportError-guarded, so ``secret_prompt`` stays kept and ``psutil`` can be omitted.
    Positive control: the same gate refuses an unguarded pty import (the test above)."""
    from pathlib import Path

    from scripts.bundle_profile_closure import _imports

    root = Path(__file__).resolve().parents[2]
    kinds = {kind for kind, _ in [(f["kind"], f["subject"]) for f in
                                  module_findings("hermes_cli.secret_prompt", root / "hermes_cli/secret_prompt.py")]}
    assert "process" not in kinds
    for rel in ("hermes_cli/process_identity.py", "hermes_constants_scratch.py", "agent_runtime/discussions/native.py",
                "agent_runtime/conversations/native_peer.py"):
        module = rel[:-3].replace("/", ".")
        unguarded = [line for dotted, _eager, guarded, line in _imports(root / rel, module, False)
                     if dotted == "psutil" and not guarded]
        assert unguarded == [], (rel, unguarded)


def test_a_pin_the_packager_ships_in_the_forced_tree_is_answered_from_its_plan(tmp_path):
    """Lane G6: a module kept code imports at module level that the packager's plan ships in the sibling
    tree (``phone_forced/``, mounted by the embedded entry) is present, so it is not pinned — read from the
    plan, for a profile that asks for the tree. Negative controls: the same pin without the tree, a pin
    outside a scanned package, and one a placeholder already answered, are not answered here."""
    from types import SimpleNamespace

    from scripts.bundle_profile_gate import forced_tree_seams, render_markdown

    sources = {"keep": "from tools.skills_hub import GitHubAuth\nimport other.pinned\n"}
    index = {"keep": tmp_path / "keep.py", "tools.skills_hub": tmp_path / "skills_hub.py",
             "other.pinned": tmp_path / "pinned.py", "tools": tmp_path / "tools_init.py"}
    index["keep"].write_text(sources["keep"], encoding="utf-8")
    for name in ("tools.skills_hub", "other.pinned", "tools"):
        index[name].write_text("", encoding="utf-8")
    walk = SimpleNamespace(pinned={"tools.skills_hub", "other.pinned"}, kept={"keep", "tools"}, unguarded_into_pruned=[])
    tree = SimpleNamespace(packaging_forced_sibling_tree=True)
    assert forced_tree_seams(tree, walk, index) == ["tools.skills_hub"]
    assert forced_tree_seams(SimpleNamespace(packaging_forced_sibling_tree=False), walk, index) == []
    assert forced_tree_seams(tree, walk, index, answered={"tools.skills_hub": ["GitHubAuth"]}) == []
    result = {"profile": "p", "targets": ["t"], "kept_modules": 2, "passed": False, "refusals": [],
              "module_findings": [], "targets_detail": {"t": {}}, "forced_tree_seams": ["tools.skills_hub"]}
    assert "sibling tree (`phone_forced/`" in render_markdown(result) and "`tools.skills_hub`" in render_markdown(result)


def test_the_phones_kept_cryptography_import_sites_are_guarded():
    """Phone-gate lane G5 (owner D3): with the vault switched off, the two kept modules that still
    reach ``cryptography`` import it ImportError-guarded, so the phone can omit it (and ``cffi``).
    Positive control: the same walk finds the sites — they are there, and guarded."""
    from pathlib import Path

    from scripts.bundle_profile_closure import _imports

    root = Path(__file__).resolve().parents[2]
    for rel in ("agent_runtime/gateway_tls.py", "agent/secret_sources/bitwarden.py"):
        module = rel[:-3].replace("/", ".")
        sites = [(line, guarded) for dotted, _eager, guarded, line in _imports(root / rel, module, False)
                 if dotted.split(".")[0] == "cryptography"]
        assert sites, rel
        assert [line for line, guarded in sites if not guarded] == [], (rel, sites)


def test_a_dropped_extra_is_not_followed_and_ships_only_when_its_distribution_imports_without_it():
    """``omitted_distributions[].dropped_extras``: the phone ships PyJWT without its requested ``crypto``
    extra, so the closure stops following ``pyjwt[crypto] -> cryptography`` — but only because a child
    interpreter with ``cryptography`` unfindable still imports ``jwt``. Positive control: the same probe
    with the distribution's own top module blocked refuses, so the probe really imports."""
    from types import SimpleNamespace

    from scripts.bundle_profile_closure import Graph, _lock, dropped_extra_failures, without_dropped_extras

    row = {"distribution": "cryptography", "imports": ("cryptography",), "degrades": "x",
           "dropped_extras": ("pyjwt[crypto]",)}
    manifest = SimpleNamespace(omitted_distributions=(row,))
    assert without_dropped_extras({"pyjwt": {"crypto"}, "httpx": {"socks"}}, manifest) == \
        {"pyjwt": set(), "httpx": {"socks"}}
    graph = Graph(_lock(), {})
    assert dropped_extra_failures(manifest, graph, {"pyjwt"}) == []
    assert dropped_extra_failures(manifest, graph, set()) == []  # not shipped on the target: nothing to prove

    blocked_self = SimpleNamespace(omitted_distributions=({**row, "imports": ("cryptography", "jwt")},))
    refused = dropped_extra_failures(blocked_self, graph, {"pyjwt"})
    assert len(refused) == 1 and refused[0].startswith("pyjwt[crypto]: jwt does not import"), refused
