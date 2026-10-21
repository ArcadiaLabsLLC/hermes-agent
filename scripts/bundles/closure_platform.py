"""Platform branches the bundle closure walk prunes for its target.

An import under ``if os.name == "nt":`` (or after ``if os.name == "posix": ...; return``) is no
load a Linux or macOS bundle must satisfy: the walk reads :func:`dead_for_target` with the target's
marker environment and skips what it buries (PKG-CLOSURE-PLATFORM-GUARDED-IMPORTS).
"""

from __future__ import annotations

import ast


#: Platform probes a branch test may read -> the marker-environment key that answers it for the target.
_PLATFORM_PROBES = {("os", "name"): "os_name", ("sys", "platform"): "sys_platform"}


def _platform_value(node: ast.expr, env: dict) -> str | None:
    """``os.name`` / ``sys.platform`` / ``platform.system()`` -> the target's value, else None."""
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        key = _PLATFORM_PROBES.get((node.value.id, node.attr))
        return env.get(key) if key else None
    if (isinstance(node, ast.Call) and not node.args and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and (node.func.value.id, node.func.attr) == ("platform", "system")):
        return env.get("platform_system")
    return None


def _platform_truth(test: ast.expr, env: dict) -> bool | None:
    """Whether a branch test on the platform holds for the target; None when it is not one.

    ``os.name == "nt"``, ``sys.platform != "win32"``, ``platform.system() == "Windows"``,
    ``sys.platform.startswith("win")`` and their ``not``."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _platform_truth(test.operand, env)
        return None if inner is None else not inner
    if (isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.NotEq))
            and isinstance(test.comparators[0], ast.Constant) and isinstance(test.comparators[0].value, str)):
        value = _platform_value(test.left, env)
        if value is None:
            return None
        return (value == test.comparators[0].value) == isinstance(test.ops[0], ast.Eq)
    if (isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute) and test.func.attr == "startswith"
            and len(test.args) == 1 and isinstance(test.args[0], ast.Constant) and isinstance(test.args[0].value, str)):
        value = _platform_value(test.func.value, env)
        return None if value is None else value.startswith(test.args[0].value)
    return None


def _terminates(body: list[ast.stmt]) -> bool:
    return bool(body) and isinstance(body[-1], (ast.Return, ast.Raise))


def dead_for_target(tree: ast.AST, env: dict) -> set[int]:
    """ids of every node a platform branch makes unreachable on the target: the false arm of an
    ``if`` on the platform, and the statements after an arm that holds and always returns/raises
    (``if os.name == "posix": ...; return`` then the Windows path). A lazy ``import portalocker`` on
    the Windows path is no load a Linux bundle must satisfy (PKG-CLOSURE-PLATFORM-GUARDED-IMPORTS)."""
    dead: set[int] = set()

    def bury(stmts) -> None:
        for stmt in stmts:
            dead.update(id(n) for n in ast.walk(stmt))

    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field, None)
            if not isinstance(stmts, list):
                continue
            for index, stmt in enumerate(stmts):
                if not isinstance(stmt, ast.If) or (truth := _platform_truth(stmt.test, env)) is None:
                    continue
                live, gone = (stmt.body, stmt.orelse) if truth else (stmt.orelse, stmt.body)
                bury(gone)
                if _terminates(live):
                    bury(stmts[index + 1:])
    return dead
