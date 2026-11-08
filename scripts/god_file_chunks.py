"""The census's per-chunk worker functions: what ``scripts/census_pool.py`` maps (FH-PREPUSH-CAP-TIGHT).

Each is a pure function of the tree on disk for one contiguous run of files, so the name census
gates (``tests/tooling/test_no_ladder_routing.py``, ``tests/agent_runtime/test_duplicate_helper_bodies.py``)
split their whole-tree walks over worker processes and merge the chunks in file order:

* :func:`vocabulary_chunk`, :func:`declared_chunk`, :func:`ladder_chunk` — W0-G5 (``god_file_probe.vocabulary``
  and ``ladder_census``);
* :func:`duplicate_chunk` — W0-G3 fork-wide (``god_file_probe.duplicate_census``);
* :func:`signature_hash_chunk` — W0-G3's agent_runtime arm, the test's ``_GRANDFATHERED`` rows:
  module-level functions only, the signature normalized and the other locals left alone.

They live outside ``god_file_probe.py`` so the probe stays under its own size ceiling; the probe
is imported when a chunk runs (it imports this module at its top).
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Iterable

_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _probe_module():
    try:  # imported as ``scripts.god_file_chunks`` (the gates)
        from scripts import god_file_probe as probe
    except ImportError:  # run as a script: ``scripts/`` is sys.path[0]
        import god_file_probe as probe
    return probe


def vocabulary_chunk(paths: Iterable[str], root: Path) -> set[str]:
    """``god_file_probe.vocabulary`` over one chunk: every word its files declare."""
    probe = _probe_module()
    words: set[str] = set()
    for path in paths:
        tree = probe._tree(root, path)
        if tree is not None:
            words |= probe._vocabulary_strings(tree)
    return words


def declared_chunk(paths: Iterable[str], root: Path) -> dict[str, frozenset[str]]:
    """``ladder_census``'s first pass over one chunk: what each module declares."""
    return _probe_module()._scope.declared_vocabularies(root, paths)


def ladder_chunk(
    paths: Iterable[str], root: Path, declared: dict[str, frozenset[str]]
) -> dict[tuple[str, str, str, str], int]:
    """``ladder_census``'s rows for one chunk, the vocabularies in reach read off ``declared``."""
    probe = _probe_module()
    scope_of = probe._scope
    out: dict[tuple[str, str, str, str], int] = {}
    for path in paths:
        tree = probe._tree(root, path)
        if tree is None:
            continue
        words = scope_of.visible_words(root, path, declared) or frozenset()
        scope = scope_of.file_scope(root, path)
        for unit in probe.iter_units(path, tree):
            for kind, subject, arms in probe._ladders_in(unit.node.body, scope.strlike):
                key = (path, unit.qualname, kind, subject)
                out[key] = max(out.get(key, 0), arms)
            for word, hits in probe._unit_vocab(unit, words, scope).items():
                out[(path, unit.qualname, "vocab", word)] = hits
    return out


def duplicate_chunk(paths: Iterable[str], root: Path) -> list[tuple[str, str, str, str]]:
    """``(digest, path, qualname, helper)`` per hashed unit of a chunk; ``helper`` is the name of a
    private module-level helper (``_x``, not dunder), else empty."""
    probe = _probe_module()
    out: list[tuple[str, str, str, str]] = []
    for path in paths:
        tree = probe._tree(root, path)
        if tree is None:
            continue
        for unit in probe.iter_units(path, tree):
            digest = probe.normalized_body_hash(unit.node)
            if digest is None:
                continue
            name = unit.node.name
            private = unit.module_level and name.startswith("_") and not name.startswith("__")
            out.append((digest, path, unit.qualname, name if private else ""))
    return out


def _is_str(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _normalize_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    """Erase everything a reader could rename without changing the function.

    The NAME first — that is what hid every family this gate was written for.
    But also the PARAMETER names and every annotation: ``read_model._rows``
    and ``snapshot._rows`` had identical bodies and differed only in that one
    of them annotated its argument ``Any`` and the other left it bare, and
    ``paths._safe_path_token`` vs ``realm_sync._safe_token`` differed only by
    ``str`` vs ``str | None``. A gate that hashes the signature verbatim
    would have missed both — which is to say, would have missed the two
    families the audit actually named.

    Defaults are NOT erased: a different default is a different function.
    """

    node.name = "_"
    node.returns = None
    args = node.args
    every = [
        *args.posonlyargs,
        *args.args,
        *([args.vararg] if args.vararg else []),
        *args.kwonlyargs,
        *([args.kwarg] if args.kwarg else []),
    ]
    mapping: dict[str, str] = {}
    for index, arg in enumerate(every):
        mapping[arg.arg] = f"a{index}"
        arg.arg = mapping[arg.arg]
        arg.annotation = None
    # ...and the parameter's USES in the body. Without this the gate is
    # defeated by `def f(raw)` vs `def f(value)`, which is a rename a copier
    # makes without thinking. Other locals are deliberately left alone: full
    # alpha-renaming would start matching functions that merely share a shape.
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in mapping:
            child.id = mapping[child.id]
        elif isinstance(child, ast.arg) and child.arg in mapping:
            child.arg = mapping[child.arg]
    ast.fix_missing_locations(node)


def signature_hash_chunk(paths: Iterable[str], root: Path, min_lines: int) -> list[tuple[str, str, str]]:
    """``(digest, path, function name)`` for every module-level function of a chunk whose
    docstring-stripped body renders to ``min_lines`` or more (the gate's own parse, read
    fresh: it never shares the source cache's trees, since it rewrites a clone)."""
    out: list[tuple[str, str, str]] = []
    for path in paths:
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover - a broken file is another gate's job
            continue
        for node in tree.body:
            if not isinstance(node, _FUNCS):
                continue
            clone = ast.parse(ast.unparse(node)).body[0]
            body = clone.body
            if body and isinstance(body[0], ast.Expr) and _is_str(body[0].value):
                clone.body = body[1:]
            rendered = "\n".join(ast.unparse(stmt) for stmt in clone.body)
            if len(rendered.splitlines()) < min_lines:
                continue
            _normalize_signature(clone)
            out.append((hashlib.sha256(ast.unparse(clone).encode()).hexdigest()[:12], path, node.name))
    return out
