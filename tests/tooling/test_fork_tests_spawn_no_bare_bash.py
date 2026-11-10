"""No fork-owned test spawns a bare ``bash`` — it asks ``tests/_downstream/real_bash.py`` (FH-TEST-BASH-RESOLVER-DUPLICATES).

On Windows a bare ``bash`` argv reaches System32's WSL launcher before PATH, which exits 1
with a UTF-16 notice or re-parses the argv through a distro's shell; the test then reds for
the host, not the code. The fork's one resolver answers which bash runs the repo's scripts.

A "must never be written" rule, so a source walk is the right shape: it flags a spawn call
(``subprocess.run``/``Popen``/``check_output``/``check_call``/``call``, ``os.exec*``,
``asyncio.create_subprocess_exec``) whose program is the literal ``bash`` / ``bash.exe``. An
argv literal that is only DATA (a classifier's input) is not a spawn and is not flagged.
Population: every tracked ``tests/**.py`` not in the upstream manifest
(``scripts/god_file_probe.upstream_paths``); upstream's tests take no edit
(``tests/scripts/conftest.py::bare_bash_is_the_real_bash`` respells theirs).

Killing mutation (2026-11-08): respell ``tests/scripts/test_rerere_train_downstream.py``'s
spawn as ``["bash", str(SCRIPT), "HEAD..main"]`` -> ``test_no_fork_owned_test_spawns_a_bare_bash`` red.
"""

from __future__ import annotations

import ast
import functools
import subprocess

import pytest

from scripts import god_file_probe as probe

pytestmark = pytest.mark.gate

#: Spawn calls whose first argument is an argv sequence.
_ARGV_SPAWNS = frozenset({"run", "Popen", "check_output", "check_call", "call"})
#: Spawn calls whose first argument is the program itself.
_PROGRAM_SPAWNS = frozenset({
    "create_subprocess_exec", "execv", "execve", "execvp", "execvpe", "execl", "execlp",
    "spawnv", "spawnvp", "spawnl", "spawnlp",
})
_BARE = frozenset({"bash", "bash.exe"})

#: Files whose bare ``bash`` is the point, with the reason.
_ALLOWED = {
    "tests/_env_gap_fence.py": "bare_bash_is_not_posix probes whether a bare bash IS the WSL launcher",
}


def _is_bare(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and node.value in _BARE


def _first_arg(call: ast.Call, keyword: str) -> ast.AST | None:
    if call.args:
        return call.args[0]
    return next((kw.value for kw in call.keywords if kw.arg == keyword), None)


def bare_bash_spawns(source: str, path: str = "<string>") -> list[int]:
    """Line numbers where ``source`` spawns the literal program ``bash``."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in _ARGV_SPAWNS:
            argv = _first_arg(node, "args")
            if isinstance(argv, (ast.List, ast.Tuple)) and argv.elts and _is_bare(argv.elts[0]):
                found.append(node.lineno)
        elif name in _PROGRAM_SPAWNS and node.args:
            program = node.args[1] if name.startswith("spawn") and len(node.args) > 1 else node.args[0]
            if _is_bare(program):
                found.append(node.lineno)
    return found


def _fork_test_files() -> list[str]:
    root = probe.ROOT
    tracked = subprocess.run(["git", "ls-files", "-z", "--", "tests/*.py"], cwd=root,
                             capture_output=True, check=True).stdout.decode("utf-8").split("\0")
    upstream = probe.upstream_paths()
    return sorted(p for p in tracked if p and p not in upstream and (root / p).is_file())


@functools.cache
def _offenders() -> dict[str, list[int]]:
    root = probe.ROOT
    found = {}
    for path in _fork_test_files():
        text = (root / path).read_text(encoding="utf-8")
        if "bash" not in text:  # a parse costs; a file that never spells bash cannot spawn it
            continue
        lines = bare_bash_spawns(text, path)
        if lines:
            found[path] = lines
    return found


def test_no_fork_owned_test_spawns_a_bare_bash():
    population = _fork_test_files()
    assert len(population) > 1000, f"the fork test population came back implausibly small: {len(population)}"
    offenders = [f"{path}:{line}" for path, lines in _offenders().items() if path not in _ALLOWED
                 for line in lines]
    assert offenders == [], (
        "spawn `resolve_real_bash()` / `real_bash_or_skip()` from tests/_downstream/real_bash.py "
        "(or the `real_bash` fixture) instead of a bare bash:\n" + "\n".join(offenders)
    )


def test_every_allowance_still_names_a_bare_bash_spawn():
    found = _offenders()
    stale = [path for path in _ALLOWED if path not in found]
    assert stale == [], f"an allowance whose file no longer spawns a bare bash: {stale}"


def test_the_walk_sees_every_spelling_it_forbids():
    """Positive control: each spawn spelling is flagged; data argvs and resolved bashes are not."""
    for spelling in (
        'subprocess.run(["bash", "-c", "x"])',
        "subprocess.run(('bash', script))",
        'subprocess.Popen(["bash.exe", script])',
        'subprocess.check_output(args=["bash", "-c", "x"])',
        'run(["bash", script], check=True)',
        'await asyncio.create_subprocess_exec("bash", "-c", "x")',
        'os.execvp("bash", ["bash", "-c", "x"])',
        'os.spawnvp(os.P_WAIT, "bash", ["bash"])',
    ):
        assert bare_bash_spawns(spelling), spelling
    for allowed in (
        "subprocess.run([real_bash, '-c', 'x'])",
        "subprocess.run([resolve_real_bash(), script])",
        'classify(["bash", "-c", "hermes gateway run"])',
        'argv = ["bash", "-lic", "x"]',
        'subprocess.run(["/usr/bin/bash", "-c", "x"])',
        'subprocess.run("bash -c x", shell=True)',
    ):
        assert not bare_bash_spawns(allowed), allowed
