"""Read literal registration tables without importing or executing tool code."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple, Optional

_UNKNOWN = object()


def registration_rows(tree: ast.Module):
    """Yield direct calls and calls in finite, literal module-level tables.

    Unknown values stay unknown: handler expressions are never evaluated. A loop
    whose table cannot be read yields its calls with unresolved arguments, so the
    manifest generator refuses a truncated inventory rather than losing tools.
    """
    definitions = {}
    reassigned = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                if target.id in definitions:
                    reassigned.add(target.id)
                definitions[target.id] = value

    def value(node, bindings, visiting=frozenset()):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in bindings:
                return bindings[node.id]
            if node.id in reassigned or node.id in visiting:
                return _UNKNOWN
            target = definitions.get(node.id)
            return value(target, bindings, visiting | {node.id}) if target else _UNKNOWN
        if isinstance(node, (ast.Tuple, ast.List)):
            return [value(item, bindings, visiting) for item in node.elts]
        if isinstance(node, ast.Dict):
            result = {}
            for key, item in zip(node.keys, node.values):
                key_value = value(key, bindings, visiting)
                if isinstance(key_value, str):
                    result[key_value] = value(item, bindings, visiting)
            return result
        if isinstance(node, ast.Subscript):
            owner = value(node.value, bindings, visiting)
            key = value(node.slice, bindings, visiting)
            if isinstance(owner, dict) and isinstance(key, str):
                return owner.get(key, _UNKNOWN)
            if isinstance(owner, list) and isinstance(key, int) and -len(owner) <= key < len(owner):
                return owner[key]
        return _UNKNOWN

    def bind(target, item, bindings):
        if isinstance(target, ast.Name):
            bindings[target.id] = item
        elif isinstance(target, (ast.Tuple, ast.List)):
            items = item if isinstance(item, list) else []
            star = next((i for i, node in enumerate(target.elts) if isinstance(node, ast.Starred)), None)
            for i, node in enumerate(target.elts):
                if isinstance(node, ast.Starred):
                    tail = len(target.elts) - i - 1
                    bind(node.value, items[i:len(items) - tail if tail else None], bindings)
                else:
                    index = i if star is None or i < star else i - len(target.elts)
                    selected = items[index] if -len(items) <= index < len(items) else _UNKNOWN
                    bind(node, selected, bindings)

    def walk(statements, bindings):
        for stmt in statements:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if (isinstance(call.func, ast.Attribute) and call.func.attr == "register"
                        and isinstance(call.func.value, ast.Name) and call.func.value.id == "registry"):
                    kw = {item.arg: item.value for item in call.keywords if item.arg}
                    name = kw.get("name") or (call.args[0] if call.args else None)
                    toolset = kw.get("toolset") or (call.args[1] if len(call.args) > 1 else None)
                    yield stmt, value(name, bindings), value(toolset, bindings)
            elif isinstance(stmt, ast.For):
                rows = value(stmt.iter, bindings)
                # Bound the reader even for an accidentally huge literal table.
                if not isinstance(rows, list) or len(rows) > 10000:
                    rows = [_UNKNOWN]
                for row in rows:
                    local = dict(bindings)
                    bind(stmt.target, row, local)
                    yield from walk(stmt.body, local)
                yield from walk(stmt.orelse, bindings)

    yield from walk(tree.body, {})


class ToolScan(NamedTuple):
    tools: dict[str, str]
    modules: dict[str, list[str]]
    unresolved: list[str]


def scan_registered_tools(tools_dir: Optional[Path] = None) -> ToolScan:
    """Which tools each builtin module registers, and into which toolset —
    read STATICALLY, importing nothing.

    The question "what are this install's toolset names" does not need the 38
    registrar modules; it needs the two identifying arguments of their top-level
    ``registry.register()`` calls, including finite literal registration
    tables. Importing them to find out costs 3.16 s measured on this checkout
    (2026-09-04, warm verdict cache) and is paid on every cold
    ``perform_agent_create`` and every single-test run, because the memo it would
    otherwise ride lives under ``get_hermes_home()`` — which the test runner
    points at a fresh temp directory per file, so it is cold by construction.

    Uses the builtin discovery text prefilter and a module-level AST reader
    that also expands literal registration tables. The scope stays module-level (a ``registry.register`` inside a
    function body is a helper, not a registrar, and stays invisible here exactly
    as it does there). What is added is reading the call's arguments.

    **This answers NAMES, never HANDLERS.** A handler is a live callable and
    there is no static substitute for importing the module that defines it.
    Anything that must CALL a tool still goes through
    :func:`discover_builtin_tools`.

    It also answers only BUILTINS. Plugin tools register into the same singleton
    through ``hermes_cli.plugins``, and MCP tools through ``discover_mcp_tools``;
    neither is in this tree and neither is in this scan. A caller that needs the
    complete live set must union this with the registry it has actually
    populated — see the note on the generated manifest.
    """

    tools_path = Path(tools_dir) if tools_dir is not None else Path(__file__).resolve().parent
    tools: dict[str, str] = {}
    modules: dict[str, list[str]] = {}
    unresolved: list[str] = []

    paths = list(tools_path.glob("*.py"))
    paths.extend(path for path in tools_path.glob("*/tool.py") if (path.parent / "__init__.py").is_file())
    for path in sorted(paths):
        if path.name in {"__init__.py", "registry.py", "mcp_tool.py"}:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            unresolved.append(f"{path.stem}: unreadable ({type(exc).__name__})")
            continue
        if "registry" not in source or "register" not in source:
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            unresolved.append(f"{path.stem}: does not parse")
            continue

        for stmt, name, toolset in registration_rows(tree):
            if not isinstance(name, str) or not isinstance(toolset, str):
                unresolved.append(
                    f"{path.stem}: register() at line {stmt.lineno} has a "
                    f"{'name' if not isinstance(name, str) else 'toolset'} this reader cannot resolve"
                )
                continue
            tools[name] = toolset
            module = ".".join(path.relative_to(tools_path).with_suffix("").parts)
            modules.setdefault(module, []).append(name)

    return ToolScan(tools=tools, modules=modules, unresolved=unresolved)
