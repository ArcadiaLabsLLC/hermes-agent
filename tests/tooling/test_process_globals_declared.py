"""Census: process-global state in fork modules is DECLARED (``agent_runtime.process_state``).

Plan ``docs/agent-runtime-harness/planned/process-global-state-reset-2026-10-15.md``
S4. A fork module that keeps state for the whole process registers its reset
beside the global; one fixture resets everything declared. This census finds the
state nobody declared.

What counts as process-global state (source walk, over-approximating -- the safe
direction for a "this must be declared" census):

* a module global rebound through a ``global`` statement in a function; or
* a module-level mutable container (dict/list/set literal or comprehension, or a
  ``dict``/``list``/``set``/``defaultdict``/``OrderedDict``/``deque``/``Counter``/
  ``WeakKeyDictionary``/``WeakValueDictionary`` call) that the module MUTATES
  (item assignment or deletion, or a mutating method call). A constant table
  nobody writes is not state.

Whether a global is declared is asked of the RUNTIME: the module is imported and
``process_state.declared_globals()`` read, so a registration that is spelled but
never bound does not count.

REPORT mode (owner ruling 2026-10-15, decision 4): the population outside the
seeded allowlist is printed, not failed, until the allowlist holds only reasoned
entries; then ``ENFORCE`` flips to True. The allowlist is
``tests/fixtures/process_globals_allowlist.json`` (``path|NAME`` -> reason).
"""

from __future__ import annotations

import ast
import importlib
import json

from scripts import god_file_probe as probe

#: Flip once every allowlist row carries a reason instead of the seed marker.
ENFORCE = False

ALLOWLIST_PATH = probe.ROOT / "tests" / "fixtures" / "process_globals_allowlist.json"
SEED_REASON = "seeded 2026-10-16 from the census; reason owed"

_CONTAINER_CALLS = {
    "dict", "list", "set", "defaultdict", "OrderedDict", "deque", "Counter",
    "WeakKeyDictionary", "WeakValueDictionary",
}
_MUTATORS = {
    "append", "add", "update", "setdefault", "pop", "popitem", "clear", "extend",
    "insert", "discard", "remove", "move_to_end", "appendleft", "popleft",
}
_EXEMPT_PATHS = {"agent_runtime/process_state.py"}


def _is_container(value: ast.AST) -> bool:
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    if isinstance(value, ast.Call):
        func = value.func
        name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        return name in _CONTAINER_CALLS
    return False


def _module_containers(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and _is_container(stmt.value):
            names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None and _is_container(stmt.value):
            if isinstance(stmt.target, ast.Name):
                names.add(stmt.target.id)
    return names


def _subscripted_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Subscript):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def process_globals(source: str) -> set[str]:
    """Names of the process-global state ``source`` keeps (see module docstring)."""

    tree = ast.parse(source)
    containers = _module_containers(tree)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            found.update(node.names)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for target in targets:
                if isinstance(target, ast.Subscript):
                    name = _subscripted_name(target)
                    if name in containers:
                        found.add(name)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _MUTATORS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in containers
        ):
            found.add(node.func.value.id)
    return found


def _dotted(path: str) -> str:
    module = path[:-3].replace("/", ".")
    return module[: -len(".__init__")] if module.endswith(".__init__") else module


def _declared(path: str, source: str) -> frozenset[str]:
    if "register_process_state" not in source:
        return frozenset()
    from agent_runtime import process_state

    try:
        importlib.import_module(_dotted(path))
    except Exception:  # an unimportable module declares nothing; the census reports it
        return frozenset()
    return process_state.declared_globals()


def census() -> set[str]:
    """``path|NAME`` for every undeclared process global in a fork production module."""

    rows: set[str] = set()
    for path in probe.fork_production_files(probe.ROOT, probe.MANIFEST):
        if path in _EXEMPT_PATHS or not path.endswith(".py"):
            continue
        source = (probe.ROOT / path).read_text(encoding="utf-8")
        names = process_globals(source)
        if not names:
            continue
        declared = _declared(path, source)
        rows.update(f"{path}|{name}" for name in names if f"{_dotted(path)}:{name}" not in declared)
    return rows


def _allowlist() -> dict[str, str]:
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


def test_census_report():
    population = census()
    allowed = _allowlist()
    new = sorted(population - set(allowed))
    stale = sorted(set(allowed) - population)
    unreasoned = sum(1 for reason in allowed.values() if reason == SEED_REASON)
    report = (
        f"process-global census: {len(population)} undeclared, {len(new)} outside the allowlist, "
        f"{len(stale)} stale allowlist rows, {unreasoned} rows still '{SEED_REASON}'\n"
        + "".join(f"  NEW   {row}\n" for row in new)
        + "".join(f"  STALE {row}\n" for row in stale)
    )
    print(report)
    if ENFORCE:
        assert not new and not stale and not unreasoned, report


def test_the_walk_sees_a_global_rebind_and_a_mutated_container_but_not_a_constant_table():
    source = (
        "import collections\n"
        "_ENABLED = False\n"
        "_CACHE = {}\n"
        "_SEEN = set()\n"
        "_QUEUE = collections.deque()\n"
        "_TABLE = {'a': 1}\n"
        "_NAMES = ['x']\n"
        "def on():\n    global _ENABLED\n    _ENABLED = True\n"
        "def put(k):\n    _CACHE[k] = 1\n    _SEEN.add(k)\n    _QUEUE.append(k)\n"
        "def read(k):\n    return _TABLE[k], _NAMES[0]\n"
    )
    assert process_globals(source) == {"_ENABLED", "_CACHE", "_SEEN", "_QUEUE"}


def test_a_declared_global_is_not_in_the_census():
    """Runtime arm: builds.detect rebinds _ENABLED and declares it, so it is absent;
    a module with the same shape and no declaration would be present."""

    path = "agent_runtime/builds/detect.py"
    source = (probe.ROOT / path).read_text(encoding="utf-8")
    assert "_ENABLED" in process_globals(source)
    assert "agent_runtime.builds.detect:_ENABLED" in _declared(path, source)
    assert f"{path}|_ENABLED" not in census()
