"""Wave-3 — the serve-cwd serialization invariant, made structural.

**The invariant.** Mission-chat workdir grounding
(``agent_runtime/mission_chat_workdir.py`` → ``AgentRunRequest.workdir`` →
``agent_runtime/profile_runner.py::_agent_workdir``) grounds a turn by calling
``os.chdir`` — which mutates **process-global** state. A ``hermes harness
serve`` process handles every request in one process, so one turn's grounding
is visible to any other turn running at the same time. That is safe today for
exactly one reason: **harness turns serialize**, because
``_execute_agent_run`` holds ``_WORKDIR_LOCK`` for the WHOLE run and
``_agent_workdir`` re-enters it around the ``chdir`` pair.

Nothing else enforces it. Remove the lock from either site and the code still
imports, still passes every functional test, and quietly becomes wrong the
first time two turns overlap — turn A's relative paths resolve into turn B's
repo, non-deterministically, with no error anywhere. That failure mode is
invisible to unit tests by construction, so it gets a structural guard
instead.

It locks one thing: nothing in ``profile_runner`` calls ``os.chdir``
(run-serialization S4, 2026-10-16: ``_agent_workdir`` grounds a run through its
terminal scope, so the process cwd is never per-turn state again). The whole-run
``_WORKDIR_LOCK`` this file used to pin was retired by S5 — runs serialize per
chat root now, proven at runtime in ``test_run_serialization_per_root.py``.

AST-based, mirroring the ``test_store_event_invariant`` precedent: a source
scan cannot be satisfied by a mock and does not need the harness in the loop.
"""

from __future__ import annotations

import ast

import agent_runtime.profile_runner as profile_runner
from tests._downstream.split_package_source import package_tree

def _module_tree() -> ast.Module:
    # The package lane R3 split profile_runner.py into, read as one text.
    return package_tree(profile_runner)


def _parents(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _is_chdir(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "chdir"
    if isinstance(func, ast.Name):
        return func.id == "chdir"
    return False


def _enclosing_qualname(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    names: list[str] = []
    current: ast.AST | None = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(current.name)
        current = parents.get(current)
    return ".".join(reversed(names)) or "<module>"


def test_profile_runner_never_moves_the_process_cwd() -> None:
    """Run-serialization S4: grounding is context-local, so ``os.chdir`` must never return.

    ``_agent_workdir`` binds the run's directory in a terminal scope
    (``tools.terminal_scope``); a process-wide ``chdir`` would ground every other run in
    the process too. A negative guarantee, so a source walk is the right instrument.
    """

    tree = _module_tree()
    parents = _parents(tree)
    chdir_calls = [
        f"profile_runner/:{node.lineno} (package text) in {_enclosing_qualname(node, parents)}"
        for node in ast.walk(tree)
        if _is_chdir(node)
    ]
    assert not chdir_calls, (
        "os.chdir mutates the SERVE PROCESS working directory, which every concurrent run "
        "shares. Ground the run through its terminal scope instead (_agent_workdir). Found: "
        + "; ".join(chdir_calls)
    )
