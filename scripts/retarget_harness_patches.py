"""Re-point test patches on ``hermes_cli.harness.<name>`` at the module that now looks ``<name>`` up.

Lane H1 (``docs/agent-runtime-harness/planned/downstream-god-file-refactor.md``
§0.4, §2 Wave 1). Until H1 the command parts under ``hermes_cli/harness_parts/``
were ``exec``'d into harness.py's globals, so ONE dict answered every lookup and
a patch on ``harness.N`` reached every part. Now each part resolves names in its
own globals, and a patch on ``harness.N`` reaches only harness.py's own code.

The rewrite is semantics-preserving by construction: a patch on ``harness.N``
becomes a patch on EVERY unit (harness.py or a part) whose code reads ``N`` as
a global — read from the compiler's symbol table, not from a spelling — so the
set of code that sees the patched value is exactly the set that saw it before.
A read of ``harness.N`` (a call, a ``spec=``) is re-pointed at the unit that
DEFINES ``N`` when harness.py no longer binds it.

Usage::

    python scripts/retarget_harness_patches.py            # census only
    python scripts/retarget_harness_patches.py --write    # rewrite the tests

The census names each site ``rewritten`` / ``fanned`` (one patch became
several) / ``untouched`` / ``by-hand`` (a form the script does not rewrite).
"""

from __future__ import annotations

import argparse
import ast
import symtable
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = "hermes_cli/harness.py"
PARTS_DIR = ROOT / "hermes_cli" / "harness_parts"
HARNESS_DOTTED = "hermes_cli.harness"


def unit_paths() -> dict[str, Path]:
    """``{dotted module: path}`` for harness.py and every part module."""
    units = {HARNESS_DOTTED: ROOT / HARNESS}
    for path in sorted(PARTS_DIR.glob("*.py")):
        units[f"hermes_cli.harness_parts.{path.stem}"] = path
    return units


def _global_reads(table: symtable.SymbolTable, out: set[str]) -> None:
    for sym in table.get_symbols():
        if not sym.is_referenced():
            continue
        if table.get_type() == "module" or sym.is_global():
            out.add(sym.get_name())
    for child in table.get_children():
        _global_reads(child, out)


def unit_facts(path: Path) -> tuple[set[str], set[str], set[str]]:
    """(names bound at module level, names DEFINED by def/class/assign, names read as globals)."""
    source = path.read_text(encoding="utf-8")
    top = symtable.symtable(source, str(path), "exec")
    bound = {s.get_name() for s in top.get_symbols() if s.is_assigned() or s.is_imported()}
    defined = {s.get_name() for s in top.get_symbols() if s.is_assigned() and not s.is_imported()}
    reads: set[str] = set()
    _global_reads(top, reads)
    return bound, defined, reads


def load_units() -> dict[str, tuple[set[str], set[str], set[str]]]:
    return {dotted: unit_facts(path) for dotted, path in unit_paths().items()}


def harness_aliases(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == HARNESS_DOTTED and alias.asname:
                    names.add(alias.asname)
        elif isinstance(node, ast.ImportFrom) and node.module == "hermes_cli":
            for alias in node.names:
                if alias.name == "harness":
                    names.add(alias.asname or "harness")
    return names


def patch_targets(name: str, units) -> list[str]:
    """Every unit whose code reads ``name`` as a global and binds it."""
    return [dotted for dotted, (bound, _d, reads) in units.items() if name in reads and name in bound]


def read_target(name: str, units) -> str | None:
    """The unit a read of ``harness.name`` should go through, or None to leave it."""
    if name in units[HARNESS_DOTTED][0]:
        return None
    definers = [d for d, (_b, defined, _r) in units.items() if name in defined]
    if len(definers) == 1:
        return definers[0]
    binders = [d for d, (bound, _d, _r) in units.items() if name in bound]
    return binders[0] if len(binders) == 1 else "?"


PATCH_METHODS = {"setattr", "object", "delattr"}


def _string_target(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        prefix = HARNESS_DOTTED + "."
        if node.value.startswith(prefix) and "." not in node.value[len(prefix):]:
            return node.value[len(prefix):]
    return None


def sites_in(path: Path, units, tree: ast.Module | None = None) -> list[dict]:
    """Every patch and read of a harness name in one test file."""
    tree = tree or ast.parse(path.read_text(encoding="utf-8"))
    aliases = harness_aliases(tree)
    sites: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        method = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        first = node.args[0]
        if (
            method in PATCH_METHODS | {"getattr", "hasattr"}
            and isinstance(first, ast.Name)
            and first.id in aliases
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            kind = "patch" if method in PATCH_METHODS else "read"
            sites.append({"kind": kind, "form": "alias", "name": node.args[1].value, "node": node, "alias": first.id})
        elif method in {"setattr", "patch", "delattr"} and _string_target(first):
            sites.append({"kind": "patch", "form": "string", "name": _string_target(first), "node": node})
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            sites.append({"kind": "read", "form": "attr", "name": node.attr, "node": node, "alias": node.value.id})
    for site in sites:
        name = site["name"]
        if site["kind"] == "patch":
            targets = patch_targets(name, units)
            if not targets:
                definer = read_target(name, units)
                targets = [definer] if definer not in (None, "?") else [HARNESS_DOTTED]
            site["targets"] = targets
            site["verdict"] = (
                "untouched" if targets == [HARNESS_DOTTED] else "rewritten" if len(targets) == 1 else "fanned"
            )
        else:
            target = read_target(name, units)
            site["targets"] = [target] if target else [HARNESS_DOTTED]
            site["verdict"] = "untouched" if target is None else "by-hand" if target == "?" else "rewritten"
    return sites


def test_files() -> list[Path]:
    out = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "hermes_cli.harness" in text or "from hermes_cli import harness" in text:
            out.append(path)
    return out


def census(units=None) -> list[tuple[Path, dict]]:
    units = units or load_units()
    return [(path, site) for path in test_files() for site in sites_in(path, units)]


ALIASES = {"board": "board_commands", "level": "level_commands", "map": "map_commands", "office": "office_commands"}
SIMPLE_VALUES = (ast.Name, ast.Lambda, ast.Constant, ast.Attribute)
DISPATCH_ENTRIES = {"main", "build_parser", "populate_parser", "build_cli_parser"}


def module_alias(dotted: str) -> str:
    if dotted == HARNESS_DOTTED:
        return "harness"
    stem = dotted.rsplit(".", 1)[1]
    return ALIASES.get(stem, stem)


def _parents(tree: ast.AST) -> dict[int, ast.AST]:
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def _enclosing(node: ast.AST, parents, kinds) -> ast.AST | None:
    current = parents.get(id(node))
    while current is not None and not isinstance(current, kinds):
        current = parents.get(id(current))
    return current


def harness_touching_helpers(tree: ast.Module, aliases: set[str]) -> set[str]:
    """Module-level helpers that reach the harness, directly or through another such helper."""
    defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    touching = {
        name for name, node in defs.items()
        if any(isinstance(x, ast.Name) and x.id in aliases for x in ast.walk(node))
    }
    changed = True
    while changed:
        changed = False
        for name, node in defs.items():
            if name in touching:
                continue
            calls = {x.func.id for x in ast.walk(node) if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)}
            if calls & touching:
                touching.add(name)
                changed = True
    return touching


def entry_units(func: ast.AST, aliases: set[str], units, local_functions: set[str]) -> set[str] | None:
    """The units a CLOSED test function enters through ``harness.N``, or None when it is not closed.

    Closed: it calls no helper defined in the test module, passes no harness
    alias as an argument and never enters through the parser, so every harness
    entry it makes is visible in its own body.
    """
    entered: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in local_functions:
                return None
            is_patch = isinstance(node.func, ast.Attribute) and node.func.attr in PATCH_METHODS | {"getattr", "hasattr"}
            if not is_patch and any(isinstance(a, ast.Name) and a.id in aliases for a in node.args):
                return None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            if node.attr in DISPATCH_ENTRIES:
                return None
            entered.update(d for d, (_b, defined, _r) in units.items() if node.attr in defined)
    return entered or None


def file_entry_units(tree: ast.Module, aliases: set[str], units) -> set[str] | None:
    """The units the whole test FILE enters through ``harness.N`` (its helpers included), or None.

    None when any entry goes through the parser or ``main``, which can reach every unit.
    """
    entered: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            if node.attr in DISPATCH_ENTRIES:
                return None
            entered.update(d for d, (_b, defined, _r) in units.items() if node.attr in defined)
    return entered or None


def _segment(lines: list[str], node: ast.AST) -> str:
    if node.lineno == node.end_lineno:
        return lines[node.lineno - 1][node.col_offset:node.end_col_offset]
    head = [lines[node.lineno - 1][node.col_offset:]]
    body = lines[node.lineno:node.end_lineno - 1]
    tail = [lines[node.end_lineno - 1][:node.end_col_offset]]
    return "\n".join(head + body + tail)


def plan_file(path: Path, units) -> tuple[list[tuple], set[str], list[str], list[dict]]:
    """(edits, part modules to import, by-hand notes, sites) for one file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    sites = sites_in(path, units, tree)
    parents = _parents(tree)
    aliases = harness_aliases(tree)
    local_functions = harness_touching_helpers(tree, aliases)
    lines = source.split("\n")
    edits: list[tuple] = []
    imports: set[str] = set()
    notes: list[str] = []
    rel = path.relative_to(ROOT).as_posix()
    for site in sites:
        node, targets = site["node"], list(site["targets"])
        if site["verdict"] == "untouched":
            continue
        if site["verdict"] == "by-hand":
            notes.append(f"{rel}:{node.lineno} read {site['name']}")
            continue
        if site["verdict"] == "fanned":
            func = _enclosing(node, parents, (ast.FunctionDef, ast.AsyncFunctionDef))
            entered = entry_units(func, aliases, units, local_functions) if func is not None else None
            if entered is None:
                entered = file_entry_units(tree, aliases, units)
            if entered and set(targets) & entered:
                targets = [t for t in targets if t in entered]
            site["targets"] = targets
            site["verdict"] = "rewritten" if len(targets) == 1 else "fanned"
            if targets == [HARNESS_DOTTED]:
                site["verdict"] = "untouched"
                continue
        if site["form"] == "attr":
            (target,) = targets
            imports.add(target)
            edits.append((node.lineno, node.value.col_offset, node.value.end_lineno, node.value.end_col_offset, module_alias(target)))
        elif site["form"] == "string":
            if len(targets) != 1:
                notes.append(f"{rel}:{node.lineno} string patch {site['name']} -> {targets}")
                continue
            first = node.args[0]
            quote = lines[first.lineno - 1][first.col_offset]
            edits.append((first.lineno, first.col_offset, first.end_lineno, first.end_col_offset, f"{quote}{targets[0]}.{site['name']}{quote}"))
        elif len(targets) == 1:
            first = node.args[0]
            imports.add(targets[0])
            edits.append((first.lineno, first.col_offset, first.end_lineno, first.end_col_offset, module_alias(targets[0])))
        else:
            stmt = parents.get(id(node))
            value = node.args[2] if len(node.args) > 2 else None
            first = node.args[0]
            if not isinstance(stmt, ast.Expr) or not isinstance(value, SIMPLE_VALUES) or first.lineno != stmt.lineno:
                notes.append(f"{rel}:{node.lineno} fanned patch {site['name']} -> {targets} (not a plain statement)")
                continue
            text = _segment(lines, stmt)
            rel_col = first.col_offset - stmt.col_offset
            copies = []
            for target in targets:
                imports.add(target)
                copies.append(text[:rel_col] + (first.id if target == HARNESS_DOTTED else module_alias(target)) + text[rel_col + len(first.id):])
            indent = " " * stmt.col_offset
            edits.append((stmt.lineno, stmt.col_offset, stmt.end_lineno, stmt.end_col_offset, ("\n" + indent).join(copies)))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module == HARNESS_DOTTED and node.level == 0):
            continue
        groups: dict[str, list[str]] = {}
        for alias in node.names:
            target = read_target(alias.name, units) or HARNESS_DOTTED
            if target == "?":
                notes.append(f"{rel}:{node.lineno} from-import {alias.name}")
                target = HARNESS_DOTTED
            spelled = alias.name + (f" as {alias.asname}" if alias.asname else "")
            groups.setdefault(target, []).append(spelled)
            sites.append({"kind": "import", "verdict": "untouched" if target == HARNESS_DOTTED else "rewritten"})
        if set(groups) == {HARNESS_DOTTED}:
            continue
        indent = " " * node.col_offset
        statements = []
        for target, names in groups.items():
            if len(names) == 1:
                statements.append(f"from {target} import {names[0]}")
            else:
                statements.append(f"from {target} import (\n" + "".join(f"{indent}    {n},\n" for n in names) + f"{indent})")
        edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, ("\n" + indent).join(statements)))
    imports.discard(HARNESS_DOTTED)
    return edits, imports, notes, sites


def apply_edits(path: Path, edits: list[tuple], imports: set[str]) -> None:
    lines = path.read_text(encoding="utf-8").split("\n")
    for lineno, col, end_lineno, end_col, text in sorted(edits, reverse=True):
        before = lines[lineno - 1][:col]
        after = lines[end_lineno - 1][end_col:]
        lines[lineno - 1:end_lineno] = (before + text + after).split("\n")
    tree = ast.parse("\n".join(lines))
    have = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "hermes_cli.harness_parts":
            for a in node.names:
                dotted = f"hermes_cli.harness_parts.{a.name}"
                if (a.asname or a.name) == module_alias(dotted):
                    have.add(dotted)
    missing = sorted(imports - have)
    if missing:
        last = 0
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                last = node.end_lineno
            elif last or not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
                break
        stmts = []
        for dotted in missing:
            stem = dotted.rsplit(".", 1)[1]
            alias = module_alias(dotted)
            stmts.append(f"from hermes_cli.harness_parts import {stem}" + (f" as {alias}" if alias != stem else ""))
        lines[last:last] = stmts
    path.write_text("\n".join(lines), encoding="utf-8", newline="")


def write(rows) -> int:
    units = load_units()
    notes: list[str] = []
    tally: Counter = Counter()
    for path in test_files():
        edits, imports, file_notes, sites = plan_file(path, units)
        notes += file_notes
        tally.update((s["kind"], s["verdict"]) for s in sites)
        if edits:
            apply_edits(path, edits, imports)
    print("after entry-unit narrowing:")
    for (kind, verdict), count in sorted(tally.items()):
        print(f"{kind:5} {verdict:9} {count}")
    print(f"by-hand: {len(notes)}")
    for note in notes:
        print("  " + note)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--detail", action="store_true")
    args = parser.parse_args(argv)
    rows = census()
    tally = Counter((site["kind"], site["verdict"]) for _p, site in rows)
    for (kind, verdict), count in sorted(tally.items()):
        print(f"{kind:5} {verdict:9} {count}")
    if args.detail:
        for path, site in rows:
            if site["verdict"] != "untouched":
                rel = path.relative_to(ROOT).as_posix()
                print(f"  {rel}:{site['node'].lineno} {site['kind']} {site['name']} -> {','.join(site['targets'])} [{site['verdict']}]")
    if args.write:
        return write(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
