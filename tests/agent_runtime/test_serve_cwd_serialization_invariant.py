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

This test locks three things:

1. Nothing in ``profile_runner`` calls ``os.chdir`` (run-serialization S4,
   2026-10-16: ``_agent_workdir`` grounds a run through its terminal scope, so
   the process cwd is never per-turn state again).
2. ``AgentRunExecution.scopes`` holds ``_WORKDIR_LOCK`` for the whole run, until
   S5 of ``docs/agent-runtime-harness/planned/run-serialization-retirement-2026-10-15.md``
   shrinks it.
3. ``_WORKDIR_LOCK`` is REENTRANT.

Widening turn concurrency therefore starts by failing this test — which is the
point. The doc section that must be satisfied first:
``docs/agent-runtime-harness/archive/2026-08-22-pre-consolidation/env-determinism-audit.md`` § "The serve-cwd
concurrency invariant". The fix shape recorded there is per-run resolved
absolute paths handed to the tools instead of a process-global ``chdir``; this
test is the tripwire that makes anyone widening concurrency read it.

AST-based, mirroring the ``test_store_event_invariant`` precedent: a source
scan cannot be satisfied by a mock and does not need the harness in the loop.
"""

from __future__ import annotations

import ast
import threading

import agent_runtime.profile_runner as profile_runner
from tests._downstream.split_package_source import package_tree

#: The lock that serializes process-global cwd mutation.
LOCK_NAME = "_WORKDIR_LOCK"
#: The run chokepoint that must hold it for the full turn.
#: (Lane R3 turned ``ProfileAgentRunner._execute_agent_run`` into phases; the
#: whole-run scope stack, ``_WORKDIR_LOCK`` first, is ``AgentRunExecution.scopes``.)
RUN_CHOKEPOINT = "AgentRunExecution.scopes"


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


def _holds_lock(with_node: ast.With | ast.AsyncWith) -> bool:
    """Does this ``with`` acquire ``_WORKDIR_LOCK`` among its items?"""

    for item in with_node.items:
        for sub in ast.walk(item.context_expr):
            if isinstance(sub, ast.Name) and sub.id == LOCK_NAME:
                return True
            if isinstance(sub, ast.Attribute) and sub.attr == LOCK_NAME:
                return True
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


def test_the_run_chokepoint_holds_the_workdir_lock_for_the_whole_run() -> None:
    """Guarding the chdir instant is not enough — the RUN must be serialized.

    ``_agent_workdir`` holds the lock across its own chdir pair, but that alone
    would still allow a second turn to acquire it and chdir away while the
    first turn's agent is mid-execution. The whole-run acquisition in
    ``_execute_agent_run`` is what actually makes the process-global cwd a
    per-turn value.
    """

    tree = _module_tree()
    parents = _parents(tree)

    targets = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and f"{_enclosing_qualname(node, parents)}.{node.name}".endswith(RUN_CHOKEPOINT)
    ]
    assert len(targets) == 1, (
        f"Expected exactly one {RUN_CHOKEPOINT}; found {len(targets)}. The run "
        "chokepoint moved — re-point this invariant at the new one."
    )

    run = targets[0]
    holds = any(
        isinstance(node, (ast.With, ast.AsyncWith)) and _holds_lock(node)
        for node in ast.walk(run)
    )
    assert holds, (
        f"{RUN_CHOKEPOINT} no longer acquires {LOCK_NAME}. Turn serialization "
        "is the ONLY reason a process-global os.chdir is safe here; dropping "
        "it silently enables concurrent turns to fight over the serve "
        "process's working directory."
    )


def test_the_workdir_lock_is_reentrant() -> None:
    """``_execute_agent_run`` and ``_agent_workdir`` both take it, nested.

    A plain ``threading.Lock`` satisfies both AST checks above and deadlocks
    the runner on the first grounded turn, so the reentrancy is part of the
    invariant, not an implementation detail.
    """

    lock = getattr(profile_runner, LOCK_NAME)
    assert isinstance(lock, type(threading.RLock())), (
        f"{LOCK_NAME} must be a reentrant lock (threading.RLock): "
        "_execute_agent_run acquires it for the run and _agent_workdir "
        f"re-acquires it around the chdir pair. Found {type(lock)!r}."
    )
    # Prove reentrancy rather than trusting the type name.
    assert lock.acquire(blocking=False)
    try:
        assert lock.acquire(blocking=False), "lock did not re-enter"
        lock.release()
    finally:
        lock.release()
